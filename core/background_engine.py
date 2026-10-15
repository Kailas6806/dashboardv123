"""
V12 PRO MAX — Background Trading Engine
Runs an autonomous daemon scanner across all active indices (NIFTY, BANKNIFTY, FINNIFTY).
Continuously evaluates signals, manages open trades, executes risk rules, and persists to DB/CSV,
regardless of which UI tab the user is viewing or whether the browser is active.
"""
import os
import sys
import time
import datetime
import threading
import logging
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple

import config
from config import (
    INDEX_CONFIG, IST, MARKET_OPEN_TIME, MARKET_CLOSE_TIME,
    NO_NEW_TRADE_TIME, MIN_ENTRY_PRICE, MAX_DAILY_TRADES,
    MAX_DAILY_LOSSES, COOLDOWN_SECONDS, ATR_PERIOD, ATR_SL_MULTIPLIER,
    is_expiry_day, CAPITAL, AI_AUTO_TRADE_DEFAULT, AI_MIN_CONVICTION,
    LOG_DIR, LOG_COLS, BASE_DIR, MIN_CONFIDENCE_SCORE
)
from utils.logger import get_logger

logger = get_logger("background_engine")


class BackgroundTradingEngine:
    """Thread-safe background trading and multi-index market scanning daemon."""

    def __init__(
        self,
        fetcher: Any,
        signal_engine: Any,
        risk_mgr: Any,
        trade_mgr: Any,
        journal: Any,
        copilot: Optional[Any] = None,
    ) -> None:
        self.fetcher = fetcher
        self.signal_engine = signal_engine
        self.risk_mgr = risk_mgr
        self.trade_mgr = trade_mgr
        self.journal = journal
        self.copilot = copilot

        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Per-index state caches
        self._latest_state: Dict[str, Dict[str, Any]] = {}
        self._signal_buffers: Dict[str, List[str]] = {idx: [] for idx in INDEX_CONFIG}
        self._last_signals: Dict[str, str] = {idx: "WAIT" for idx in INDEX_CONFIG}
        self._spot_histories: Dict[str, List[float]] = {idx: [] for idx in INDEX_CONFIG}
        self._pcr_histories: Dict[str, List[float]] = {idx: [] for idx in INDEX_CONFIG}
        self._prev_dfs: Dict[str, Optional[pd.DataFrame]] = {idx: None for idx in INDEX_CONFIG}
        self._oi_baselines: Dict[str, Optional[pd.DataFrame]] = {idx: None for idx in INDEX_CONFIG}
        self._trade_logs: Dict[str, List[Dict[str, Any]]] = {idx: [] for idx in INDEX_CONFIG}
        self._last_sl_times: Dict[str, Optional[datetime.datetime]] = {idx: None for idx in INDEX_CONFIG}
        self._ai_analyses: Dict[str, Optional[Dict[str, Any]]] = {idx: None for idx in INDEX_CONFIG}

        # Configurable flags
        self.ai_auto_trade = AI_AUTO_TRADE_DEFAULT
        self.min_confidence_score = getattr(config, "MIN_CONFIDENCE_SCORE", 30)  # Rule engine score minimum

        # Signal audit & rejection log
        self._audit_history: List[Dict[str, Any]] = []
        self._audit_file = os.path.join(LOG_DIR, "signal_audit.jsonl")
        self._last_audit_times: Dict[str, float] = {idx: 0.0 for idx in INDEX_CONFIG}
        self._last_audit_signals: Dict[str, str] = {idx: "" for idx in INDEX_CONFIG}
        self._load_initial_audit_log()

        # Stats
        self.total_scans = 0
        self.last_scan_timestamp = None
        self.engine_status = "INITIALIZED"

        # Load existing trades on startup
        self._load_initial_trades()
        logger.info("BackgroundTradingEngine created successfully")

    def _load_initial_trades(self) -> None:
        """Load today's trade logs for all indices into memory on startup."""
        with self._lock:
            for idx in INDEX_CONFIG:
                try:
                    # 1. Try loading from TradeDB (Supabase)
                    today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
                    loaded = False
                    if hasattr(self.journal, "db") and self.journal.db:
                        all_db = self.journal.db.get_all_trades(instrument=idx)
                        if all_db:
                            today_trades = [t for t in all_db if str(t.get("date") or "")[:10] == today_str]
                            self._trade_logs[idx] = today_trades
                            loaded = True
                    # 2. Fallback to CSV
                    if not loaded and hasattr(self.trade_mgr, "load_log"):
                        self._trade_logs[idx] = self.trade_mgr.load_log(idx)
                except Exception as e:
                    logger.warning(f"Error loading initial trades for {idx}: {e}")
                    self._trade_logs[idx] = []

    def _load_initial_audit_log(self) -> None:
        """Load recent audit records from disk on startup."""
        if not os.path.exists(self._audit_file):
            return
        try:
            import json
            entries = []
            with open(self._audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            continue
            with self._lock:
                self._audit_history = entries[-2000:]
        except Exception as e:
            logger.warning(f"Error loading signal audit log: {e}")

    def _log_audit_event(
        self,
        idx: str,
        spot: float,
        md: Dict[str, Any],
        raw_signal: str,
        final_signal: str,
        final_conf: str,
        conf_score: int,
        ai_score: Optional[int],
        ai_rec: str,
        ai_reasoning: str,
        status: str,
        rejection_code: str,
        rejection_detail: str,
        now_ist: datetime.datetime,
        force_log: bool = False,
    ) -> None:
        """Record an evaluated signal and rejection/execution details."""
        import json
        import time as _time
        now_ts = _time.time()
        last_t = self._last_audit_times.get(idx, 0.0)
        last_sig = self._last_audit_signals.get(idx, "")

        # Throttle: Log if signal changed, if executed, or if > 60s has elapsed
        if not force_log and status != "EXECUTED":
            if final_signal == last_sig and (now_ts - last_t) < 60.0:
                return

        self._last_audit_times[idx] = now_ts
        self._last_audit_signals[idx] = final_signal

        entry = {
            "timestamp": now_ist.strftime("%Y-%m-%d %I:%M:%S %p"),
            "date": now_ist.strftime("%Y-%m-%d"),
            "time_str": now_ist.strftime("%I:%M:%S %p"),
            "idx": idx,
            "spot": round(float(spot), 2),
            "atm": int(md.get("atm_actual", 0)),
            "pcr": round(float(md.get("pcr", 1.0)), 2),
            "pcr_mom": md.get("pcr_momentum", "FLAT"),
            "spot_vs_vwap": md.get("spot_vs_vwap", ""),
            "vwap": round(float(md.get("vwap_proxy", spot)), 2),
            "support": int(md.get("support", 0)),
            "resistance": int(md.get("resistance", 0)),
            "ce_delta": int(md.get("total_ce_delta", 0)),
            "pe_delta": int(md.get("total_pe_delta", 0)),
            "tot_ce": int(md.get("tot_ce", 0)),
            "tot_pe": int(md.get("tot_pe", 0)),
            "raw_signal": raw_signal,
            "final_signal": final_signal,
            "final_conf": final_conf,
            "rule_score": int(conf_score),
            "ai_conviction": int(ai_score) if ai_score is not None else None,
            "ai_rec": ai_rec,
            "status": status,  # "EXECUTED" | "REJECTED" | "NEUTRAL_WAIT"
            "rejection_code": rejection_code,
            "rejection_detail": rejection_detail,
            "ai_reasoning": ai_reasoning,
        }

        with self._lock:
            self._audit_history.append(entry)
            if len(self._audit_history) > 2000:
                self._audit_history = self._audit_history[-2000:]

        try:
            os.makedirs(os.path.dirname(self._audit_file), exist_ok=True)
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Error persisting signal audit entry: {e}")

    def get_audit_log(
        self,
        limit: int = 1000,
        idx: Optional[str] = None,
        filter_status: Optional[str] = None,
        date_str: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return thread-safe slice of audit log filtered by date, index, or status."""
        with self._lock:
            records = list(self._audit_history)
        if date_str and date_str != "ALL":
            records = [r for r in records if (r.get("date") or str(r.get("timestamp", ""))[:10]) == date_str]
        if idx and idx != "ALL":
            records = [r for r in records if r.get("idx") == idx]
        if filter_status and filter_status != "ALL":
            records = [r for r in records if r.get("status") == filter_status or r.get("rejection_code") == filter_status]
        return records[-limit:][::-1]  # Most recent first

    def get_audit_stats(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """Return summary statistics across the audit history, optionally filtered by date."""
        with self._lock:
            records = list(self._audit_history)
        if date_str and date_str != "ALL":
            records = [r for r in records if (r.get("date") or str(r.get("timestamp", ""))[:10]) == date_str]
        total = len(records)
        executed = sum(1 for r in records if r.get("status") == "EXECUTED")
        rejected = sum(1 for r in records if r.get("status") == "REJECTED")
        neutral = sum(1 for r in records if r.get("status") == "NEUTRAL_WAIT")

        reasons: Dict[str, int] = {}
        for r in records:
            rc = r.get("rejection_code")
            if rc and rc not in ("NONE", "NO_SETUP"):
                reasons[rc] = reasons.get(rc, 0) + 1
        return {
            "total_setups": total,
            "executed": executed,
            "rejected": rejected,
            "neutral_wait": neutral,
            "rejection_breakdown": reasons,
        }

    def start(self) -> bool:
        """Start background scanner loop in a daemon thread."""
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return True

            self._running = True
            self.engine_status = "RUNNING"
            self._thread = threading.Thread(
                target=self._run_loop,
                name="V12-BackgroundScanner",
                daemon=True,
            )
            self._thread.start()
            logger.info("BackgroundTradingEngine daemon thread started")
            return True

    def stop(self) -> None:
        """Gracefully stop background scanner loop."""
        with self._lock:
            self._running = False
            self.engine_status = "STOPPED"
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("BackgroundTradingEngine daemon thread stopped")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ─────────────────────────────────────────────────────────────
    # MAIN WORKER LOOP
    # ─────────────────────────────────────────────────────────────
    def _run_loop(self) -> None:
        """Continuously iterate over all indices every ~3 seconds."""
        logger.info("Background scanner main loop active")
        while self._running:
            try:
                now_ist = datetime.datetime.now(IST)
                now_time = now_ist.time()
                in_window = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME)

                for idx in INDEX_CONFIG:
                    if not self._running:
                        break
                    try:
                        self._evaluate_index(idx, now_ist, in_window)
                    except Exception as e:
                        logger.error(f"Error during scan of {idx}: {e}", exc_info=True)

                    # Respect Angel One API rate limits (pace requests 0.6s)
                    time.sleep(0.6)

                with self._lock:
                    self.total_scans += 1
                    self.last_scan_timestamp = datetime.datetime.now(IST).strftime("%I:%M:%S %p")

                # Small sleep before next complete multi-index round
                time.sleep(1.0)

            except Exception as e:
                logger.error(f"Unexpected error in background scanner loop: {e}", exc_info=True)
                time.sleep(2.0)

    # ─────────────────────────────────────────────────────────────
    # SINGLE INDEX SCAN & TRADE EVALUATION
    # ─────────────────────────────────────────────────────────────
    def _evaluate_index(self, idx: str, now_ist: Optional[datetime.datetime] = None, in_window: Optional[bool] = None) -> None:
        """Evaluate one index: option chain, signals, risk, and autonomous trade execution."""
        if now_ist is None:
            now_ist = datetime.datetime.now(IST)
        if in_window is None:
            now_time = now_ist.time()
            in_window = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME)
        cfg = INDEX_CONFIG[idx]
        lot = cfg["lot"]
        step = cfg["step"]
        rng = cfg["rng"]

        # 1. Fetch live option chain
        data = None
        if self.fetcher:
            try:
                data = self.fetcher.fetch_option_chain(idx)
            except Exception as e:
                logger.warning(f"Background fetch error for {idx}: {e}")

        cache_file = os.path.join(BASE_DIR, f"last_data_{idx}.json")
        if data is None:
            if os.path.exists(cache_file):
                try:
                    import json
                    with open(cache_file, "r") as f:
                        data = json.load(f)
                except Exception:
                    pass
        else:
            try:
                import json
                with open(cache_file, "w") as f:
                    json.dump(data, f)
            except Exception:
                pass

        if not data or "records" not in data:
            return

        records = data["records"]["data"]
        spot = float(data["records"]["underlyingValue"])

        # Check live WebSocket tick for underlying spot
        if self.fetcher and hasattr(self.fetcher, "ws_mgr") and self.fetcher.ws_mgr:
            tok = self.fetcher.index_tokens.get(idx, {}).get("token")
            if tok:
                ws_spot = self.fetcher.ws_mgr.get_live_ltp(str(tok))
                if ws_spot and ws_spot > 0:
                    spot = float(ws_spot)
                    data["records"]["underlyingValue"] = ws_spot

        # 2. Build Strike DataFrame
        atm = round(spot / step) * step
        rows = []
        for item in records:
            s = item.get("strikePrice", 0)
            if abs(s - atm) <= rng:
                ce = item.get("CE") or {}
                pe = item.get("PE") or {}
                rows.append({
                    "Strike": s,
                    "CE LTP": ce.get("lastPrice", 0),
                    "CE OI": ce.get("openInterest", 0),
                    "PE LTP": pe.get("lastPrice", 0),
                    "PE OI": pe.get("openInterest", 0),
                })
        df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
        if df.empty:
            return

        # 3. 15-Minute Trend Filter
        trend_15m_info = {}
        if self.fetcher and hasattr(self.fetcher, "get_15m_trend"):
            try:
                trend_15m_info = self.fetcher.get_15m_trend(idx, current_spot=spot)
            except Exception:
                trend_15m_info = {"trend": "NEUTRAL", "ema20": 0.0}

        # 4. Market Data Computation
        with self._lock:
            prev_df = self._prev_dfs.get(idx)
            oi_baseline = self._oi_baselines.get(idx)
            pcr_history = self._pcr_histories.get(idx, [])
            spot_history = self._spot_histories.get(idx, [])

        try:
            md = self.signal_engine.compute_market_data(
                df, spot, step, idx, spot_history, pcr_history, prev_df, oi_baseline,
                trend_15m=trend_15m_info.get("trend", "NEUTRAL"),
                trend_15m_ema=trend_15m_info.get("ema20", 0.0),
            )
        except TypeError:
            md = self.signal_engine.compute_market_data(
                df, spot, step, idx, spot_history, pcr_history, prev_df, oi_baseline
            )
            if isinstance(md, dict):
                md["trend_15m"] = trend_15m_info.get("trend", "NEUTRAL")
                md["trend_15m_ema"] = trend_15m_info.get("ema20", 0.0)

        # Update running histories
        with self._lock:
            self._prev_dfs[idx] = md["prev_df"]
            self._oi_baselines[idx] = md["oi_baseline"]
            self._pcr_histories[idx] = md["pcr_history"]
            self._spot_histories[idx] = md["spot_history"]

        # 5. Signal Generation, Traps, Buffer Confirmation
        raw_signal, raw_conf, filter_reason = self.signal_engine.generate_signal(md, in_window)
        trap = self.signal_engine.detect_trap(
            spot, md["support"], md["resistance"],
            md["total_ce_delta"], md["total_pe_delta"]
        )

        with self._lock:
            buf = self._signal_buffers.get(idx, [])
            final_signal, final_conf, updated_buf = self.signal_engine.confirm_signal(
                raw_signal, raw_conf, buf
            )
            self._signal_buffers[idx] = updated_buf

        # 6. Check SL / Target / Trailing / Exits on Open Trades
        with self._lock:
            tlog = self._trade_logs.get(idx, [])

        events = []
        try:
            events = self.trade_mgr.update_live_prices(
                idx, tlog, records, now_ist, fetcher=self.fetcher
            )
        except Exception as e:
            logger.warning(f"Background SL/Target update error on {idx}: {e}")

        if events:
            with self._lock:
                for ev in events:
                    if ev.get("type") == "SL_HIT":
                        self._last_sl_times[idx] = now_ist
                    self._last_signals[idx] = "WAIT"
                self.trade_mgr.save_log(idx, tlog)

            for ev in events:
                trade = ev["trade"]
                if self.journal:
                    self.journal.update_trade(
                        trade.get("_journal_id", ""),
                        {
                            "Exit Time": trade.get("Exit Time"),
                            "Exit Price": trade.get("Exit Price"),
                            "Actual P&L ₹": trade.get("Actual P&L ₹"),
                            "Status": trade.get("Status"),
                            "Result": trade.get("Result"),
                        },
                        trade
                    )
                try:
                    if self.trade_mgr and hasattr(self.trade_mgr, "notifier") and self.trade_mgr.notifier:
                        res_str = str(trade.get("Result", "CLOSED"))
                        emoji = "🟢" if "WIN" in res_str else ("🔴" if "LOSS" in res_str or "SL" in res_str else "🛡️")
                        self.trade_mgr.notifier.send_exit_alert(
                            idx=idx,
                            signal=trade.get("Signal", ""),
                            result_emoji=emoji,
                            result_text=res_str,
                            strike=str(trade.get("Strike", "")),
                            entry=str(trade.get("Entry Price", "")),
                            exit_price=str(trade.get("Exit Price", "")),
                            pnl=str(trade.get("Actual P&L ₹", "")),
                            time_str=str(trade.get("Exit Time") or now_ist.strftime("%I:%M:%S %p")),
                        )
                except Exception as e_exit_ntf:
                    logger.warning(f"Error sending background exit alert for {idx}: {e_exit_ntf}")

        # 7. Don't enter if trade already open
        open_exists = any(t.get("Status") == "OPEN" for t in tlog)
        if open_exists and final_signal in ("BUY CE", "BUY PE"):
            final_signal = "WAIT"
            final_conf = "LOW"

        # 8. Confidence Score & Sideways Analysis
        conf_score = self.signal_engine.compute_confidence_score(md, raw_signal, trap)
        sideways_is, sideways_strength = self.signal_engine.detect_sideways(
            md["spot_history"], md["pcr"]
        )
        sideways_info = {"is_sideways": sideways_is, "strength": sideways_strength}

        # Portfolio-wide trade checks
        portfolio_today_trades = []
        with self._lock:
            for _i in INDEX_CONFIG:
                portfolio_today_trades.extend(self._trade_logs.get(_i, []))

        trades_today_count = len([t for t in portfolio_today_trades if t.get("Entry Time")])
        cooldown_info = self.risk_mgr.should_allow_trade(
            idx, tlog, now_ist, portfolio_trades=portfolio_today_trades
        )
        daily_limits = self.risk_mgr.check_daily_limits(portfolio_today_trades)

        # 9. Autonomous Trade Entry Evaluation
        if final_signal in ("BUY CE", "BUY PE") and final_conf in ("HIGH", "MEDIUM"):
            atm_row = md.get("atm_row", {})
            ce_price = round(float(atm_row.get("CE LTP", 0)), 2)
            pe_price = round(float(atm_row.get("PE LTP", 0)), 2)
            ep = ce_price if final_signal == "BUY CE" else pe_price

            qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade_with_atr(
                ep, lot, md["spot_history"]
            )

            # Guards
            too_late = now_ist.time() >= NO_NEW_TRADE_TIME
            expiry_today = is_expiry_day(idx)
            price_too_low = ep < MIN_ENTRY_PRICE and not expiry_today
            oi_unusual = md.get("oi_unusual_activity", False)
            daily_trades_exceeded = trades_today_count >= MAX_DAILY_TRADES
            trade_allowed = cooldown_info[0]
            daily_allowed = daily_limits[0]

            # Margin check
            can_afford = True
            try:
                cap_info = {"base_capital": CAPITAL, "current_balance": CAPITAL}
                if hasattr(self.journal, "db") and self.journal.db:
                    cap_info = self.journal.db.get_or_init_capital(CAPITAL)
                portfolio_stats = self.risk_mgr.calculate_portfolio_equity(
                    cap_info.get("base_capital", CAPITAL),
                    portfolio_today_trades,
                    all_time_pnl=cap_info.get("cumulative_realized_pnl", 0.0),
                )
                can_afford, _ = self.risk_mgr.can_afford_trade(ep, qty, portfolio_stats.get("available_margin", CAPITAL))
            except Exception:
                can_afford = True

            can_enter = (
                not too_late
                and not price_too_low
                and not oi_unusual
                and conf_score >= self.min_confidence_score
                and not daily_trades_exceeded
                and daily_allowed
                and trade_allowed
                and can_afford
            )

            with self._lock:
                last_sig = self._last_signals.get(idx)

            if can_enter and final_signal != last_sig:
                ai_conviction_ok = True
                ai_pre_score = conf_score
                ai_pre_rec = "BUY"
                ai_pre_summary = "Rule Engine Autonomous Signal"

                # AI Pre-Trade Validation
                if self.copilot and self.copilot.is_configured():
                    try:
                        ai_res = self.copilot.analyze_market_and_signals(
                            idx, md, final_signal, conf_score,
                            active_trades_count=len([t for t in tlog if t.get("Status") == "OPEN"])
                        )
                        with self._lock:
                            self._ai_analyses[idx] = ai_res
                        ai_pre_score = ai_res.get("conviction_score", 0)
                        ai_pre_rec = ai_res.get("recommendation", "AVOID_WAIT")
                        ai_pre_summary = ai_res.get("reasoning_summary") or ai_res.get("detailed_reasoning", "")

                        if self.ai_auto_trade:
                            if ai_pre_score < AI_MIN_CONVICTION or "BUY" not in ai_pre_rec:
                                ai_conviction_ok = False
                                logger.info(f"[{idx}] AI blocked trade: conviction {ai_pre_score}/{AI_MIN_CONVICTION}, rec={ai_pre_rec}")
                    except Exception as e:
                        logger.warning(f"[{idx}] AI validation exception: {e}")

                if ai_conviction_ok:
                    now_str = now_ist.strftime("%I:%M:%S %p")
                    trade_entry = {
                        "Entry Time": now_str,
                        "Exit Time": None,
                        "Index": idx,
                        "Signal": final_signal,
                        "Spot": round(spot, 2),
                        "Strike": md["atm_actual"],
                        "Entry Price": ep,
                        "Live Price": ep,
                        "Exit Price": None,
                        "Stop Loss": sl_p,
                        "Target": tgt_p,
                        "Qty": qty,
                        "Max Loss ₹": ml,
                        "Target P&L ₹": tp,
                        "Actual P&L ₹": None,
                        "Status": "OPEN",
                        "Result": "⏳ OPEN",
                        "Confidence Score": ai_pre_score if self.ai_auto_trade else conf_score,
                        "_ai_generated": self.ai_auto_trade,
                        "_ai_conviction": ai_pre_score,
                        "_ai_reasoning": ai_pre_summary,
                    }

                    with self._lock:
                        tlog.insert(0, trade_entry)
                        self._trade_logs[idx] = tlog
                        self.trade_mgr.save_log(idx, tlog)
                        self._last_signals[idx] = final_signal

                    # Record in Journal & Supabase
                    journal_id = ""
                    if self.journal:
                        try:
                            journal_id = self.journal.record_trade(trade_entry, {
                                "pcr": md["pcr"], "vwap": md["vwap_proxy"],
                                "oi_delta_ce": md["total_ce_delta"],
                                "oi_delta_pe": md["total_pe_delta"],
                                "confidence_score": ai_pre_score if self.ai_auto_trade else conf_score,
                                "pcr_momentum": md["pcr_momentum"],
                                "trap": trap, "buffer_state": updated_buf[-3:],
                                "ai_validated": self.ai_auto_trade,
                                "ai_reasoning": ai_pre_summary if self.ai_auto_trade else "",
                            })
                            trade_entry["_journal_id"] = journal_id
                        except Exception as e:
                            logger.error(f"Error journaling trade for {idx}: {e}")

                    # Telegram alert
                    try:
                        signal_label = f"🤖 [AUTONOMOUS AI✅] {final_signal}" if self.ai_auto_trade else f"⚡ [AUTO-BOT] {final_signal}"
                        self.trade_mgr.notifier.send_signal_alert(
                            idx=idx, signal=signal_label,
                            strike=md["atm_actual"], spot=round(spot, 2),
                            entry=ep, sl=sl_p, tgt=tgt_p,
                            qty=qty, ml=ml, tp=tp,
                            conf=final_conf, score=ai_pre_score if self.ai_auto_trade else conf_score,
                            time_str=now_str,
                        )
                    except Exception as e:
                        logger.warning(f"Telegram alert error: {e}")

                    logger.info(
                        f"[{idx}] AUTONOMOUS TRADE ENTERED: {final_signal} @ Strike {md['atm_actual']} | "
                        f"EP={ep} SL={sl_p} Tgt={tgt_p} Qty={qty} Score={ai_pre_score}"
                    )
                    # Audit record: EXECUTED
                    self._log_audit_event(
                        idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                        final_conf=final_conf, conf_score=conf_score, ai_score=ai_pre_score,
                        ai_rec=ai_pre_rec, ai_reasoning=ai_pre_summary, status="EXECUTED",
                        rejection_code="NONE",
                        rejection_detail=f"Executed {final_signal} at ₹{ep:.2f} (Rule: {conf_score}/100, AI: {ai_pre_score}/100)",
                        now_ist=now_ist, force_log=True
                    )
                else:
                    with self._lock:
                        self._last_signals[idx] = final_signal
                    # Audit record: REJECTED by AI
                    rej_code = "AI_CONVICTION_LOW" if ai_pre_score < AI_MIN_CONVICTION else "AI_REC_NOT_BUY"
                    rej_det = f"AI Conviction {ai_pre_score}/100 is below {AI_MIN_CONVICTION} target (Rec: {ai_pre_rec})."
                    self._log_audit_event(
                        idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                        final_conf=final_conf, conf_score=conf_score, ai_score=ai_pre_score,
                        ai_rec=ai_pre_rec, ai_reasoning=ai_pre_summary, status="REJECTED",
                        rejection_code=rej_code, rejection_detail=rej_det,
                        now_ist=now_ist, force_log=True
                    )
            elif not can_enter:
                # Audit record: REJECTED by Risk Guard
                if open_exists:
                    rej_code = "POSITION_ALREADY_OPEN"
                    rej_det = f"Open trade already active on {idx}. Multiple positions blocked."
                elif too_late:
                    rej_code = "TIME_CUTOFF"
                    rej_det = f"Time {now_ist.strftime('%I:%M %p')} is past {NO_NEW_TRADE_TIME.strftime('%I:%M %p')} cutoff."
                elif price_too_low:
                    rej_code = "PREMIUM_TOO_LOW"
                    rej_det = f"Option premium ₹{ep:.2f} is below ₹{MIN_ENTRY_PRICE} minimum."
                elif not trade_allowed:
                    rej_code = "COOLDOWN_ACTIVE"
                    rej_det = f"Cooldown active after recent stop loss ({cooldown_info[1]})."
                elif not daily_allowed:
                    rej_code = "DAILY_LIMIT_REACHED"
                    rej_det = f"Daily portfolio limits reached ({daily_limits[1]})."
                elif daily_trades_exceeded:
                    rej_code = "MAX_DAILY_TRADES"
                    rej_det = f"Maximum daily trades ({MAX_DAILY_TRADES}) reached for today."
                elif oi_unusual:
                    rej_code = "UNUSUAL_OI_SPIKE"
                    rej_det = "Single strike holds >30% of total OI delta."
                elif conf_score < self.min_confidence_score:
                    rej_code = "RULE_SCORE_LOW"
                    rej_det = f"Confidence score {conf_score}/100 is below minimum {self.min_confidence_score}."
                elif not can_afford:
                    rej_code = "INSUFFICIENT_MARGIN"
                    rej_det = "Available account margin is insufficient for 1 lot."
                else:
                    rej_code = "GUARD_BLOCKED"
                    rej_det = "Pre-trade risk guard blocked entry."

                self._log_audit_event(
                    idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                    final_conf=final_conf, conf_score=conf_score, ai_score=None,
                    ai_rec="BLOCKED_BY_GUARD", ai_reasoning="", status="REJECTED",
                    rejection_code=rej_code, rejection_detail=rej_det,
                    now_ist=now_ist, force_log=True
                )
        else:
            if raw_signal == "⚠️ SIDEWAYS":
                rej_code = "SIDEWAYS_CHOP"
                rej_det = f"PCR at {md['pcr']:.2f} is in the sideways band (0.85–1.15). No directional edge."
                self._log_audit_event(
                    idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                    final_conf=final_conf, conf_score=conf_score, ai_score=None, ai_rec="AVOID",
                    ai_reasoning=f"Sideways regime detected ({sideways_strength}).",
                    status="REJECTED", rejection_code=rej_code, rejection_detail=rej_det,
                    now_ist=now_ist
                )
            elif filter_reason:
                rej_code = "FILTER_BLOCKED"
                self._log_audit_event(
                    idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                    final_conf=final_conf, conf_score=conf_score, ai_score=None, ai_rec="WAIT",
                    ai_reasoning=filter_reason, status="REJECTED", rejection_code=rej_code,
                    rejection_detail=filter_reason, now_ist=now_ist
                )
            else:
                self._log_audit_event(
                    idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                    final_conf=final_conf, conf_score=conf_score, ai_score=None, ai_rec="WAIT",
                    ai_reasoning="Awaiting clear trend confirmation.", status="NEUTRAL_WAIT",
                    rejection_code="NO_SETUP",
                    rejection_detail=f"Spot {spot:.2f} vs VWAP {md['vwap_proxy']:.2f}, PCR {md['pcr']:.2f} ({md['pcr_momentum']}).",
                    now_ist=now_ist
                )

            if final_signal == "WAIT" and not open_exists:
                with self._lock:
                    if self._last_signals.get(idx) not in ("WAIT",):
                        self._last_signals[idx] = "WAIT"

        # 10. Cache snapshot for ultra-fast instant UI rendering (< 5ms)
        with self._lock:
            self._latest_state[idx] = {
                "idx": idx,
                "spot": spot,
                "atm": md["atm_actual"],
                "pcr": md["pcr"],
                "bias": md["bias"],
                "support": md["support"],
                "resistance": md["resistance"],
                "secondary_support": md.get("secondary_support"),
                "secondary_resistance": md.get("secondary_resistance"),
                "vwap_proxy": md["vwap_proxy"],
                "spot_vs_vwap": md["spot_vs_vwap"],
                "pcr_momentum": md["pcr_momentum"],
                "total_ce_delta": md["total_ce_delta"],
                "total_pe_delta": md["total_pe_delta"],
                "oi_active": md.get("oi_active", True),
                "oi_unusual": md.get("oi_unusual_activity", False),
                "trend_15m": md.get("trend_15m"),
                "trend_15m_ema": md.get("trend_15m_ema", 0.0),
                "raw_signal": raw_signal,
                "raw_conf": raw_conf,
                "final_signal": final_signal,
                "final_conf": final_conf,
                "conf_score": conf_score,
                "trap": trap,
                "filter_reason": filter_reason,
                "sideways_info": sideways_info,
                "cooldown_info": cooldown_info,
                "daily_limits": daily_limits,
                "df": df,
                "records": records,
                "market_data": md,
                "buffer": updated_buf,
                "tlog": list(tlog),
                "updated_at": datetime.datetime.now(IST).strftime("%I:%M:%S %p"),
                "is_live": True,
            }

    # ─────────────────────────────────────────────────────────────
    # PUBLIC ACCESSORS FOR UI
    # ─────────────────────────────────────────────────────────────
    def get_latest_state(self, idx: str) -> Optional[Dict[str, Any]]:
        """Return the latest evaluated snapshot for an index (thread-safe)."""
        with self._lock:
            return self._latest_state.get(idx)

    def get_trade_log(self, idx: str) -> List[Dict[str, Any]]:
        """Return the current trade log for an index."""
        with self._lock:
            return list(self._trade_logs.get(idx, []))

    def update_trade_log(self, idx: str, tlog: List[Dict[str, Any]]) -> None:
        """Update trade log from UI manual intervention (close, etc)."""
        with self._lock:
            self._trade_logs[idx] = list(tlog)

    def get_status_summary(self) -> Dict[str, Any]:
        """Diagnostic summary for Activity tab & header."""
        with self._lock:
            return {
                "running": self.is_running(),
                "status": self.engine_status,
                "total_scans": self.total_scans,
                "last_scan": self.last_scan_timestamp,
                "indices": list(self._latest_state.keys()),
            }


# ─────────────────────────────────────────────────────────────
# SINGLETON FACTORY
# ─────────────────────────────────────────────────────────────
_engine_lock = threading.Lock()
_global_engine: Optional[BackgroundTradingEngine] = None


def get_background_engine(
    fetcher: Any = None,
    signal_engine: Any = None,
    risk_mgr: Any = None,
    trade_mgr: Any = None,
    journal: Any = None,
    copilot: Optional[Any] = None,
) -> BackgroundTradingEngine:
    """Return the global BackgroundTradingEngine singleton, initializing if needed."""
    global _global_engine
    if _global_engine is None:
        with _engine_lock:
            if _global_engine is None:
                if fetcher is None:
                    from core.angelone_fetcher import get_fetcher
                    fetcher = get_fetcher()
                if signal_engine is None:
                    from core.signal_engine import SignalEngine
                    signal_engine = SignalEngine()
                if risk_mgr is None:
                    from core.risk_manager import RiskManager
                    risk_mgr = RiskManager()
                if trade_mgr is None:
                    from core.trade_manager import TradeManager
                    trade_mgr = TradeManager(notifier=None, risk_mgr=risk_mgr)
                if journal is None:
                    from analytics.trade_journal import TradeJournal
                    journal = TradeJournal()
                if copilot is None:
                    from core.ai_copilot import AICopilot
                    copilot = AICopilot()

                _global_engine = BackgroundTradingEngine(
                    fetcher=fetcher,
                    signal_engine=signal_engine,
                    risk_mgr=risk_mgr,
                    trade_mgr=trade_mgr,
                    journal=journal,
                    copilot=copilot,
                )
    return _global_engine
