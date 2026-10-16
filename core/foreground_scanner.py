"""
V12 PRO MAX — 100% Foreground Multi-Index Scanner
Executes sequential scanning of NIFTY, BANKNIFTY, and FINNIFTY directly in the Streamlit foreground.
Evaluates signals, enforces risk rules (strict 1 open trade per index), trails SL/TP,
executes autonomous entries & exits, sends Telegram alerts, and updates Supabase DB/CSV.
"""
import os
import sys
import json
import time
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple

import config
from config import (
    INDEX_CONFIG, IST, MARKET_OPEN_TIME, MARKET_CLOSE_TIME,
    NO_NEW_TRADE_TIME, MIN_ENTRY_PRICE, MAX_DAILY_TRADES,
    MAX_DAILY_LOSSES, COOLDOWN_SECONDS, ATR_PERIOD, ATR_SL_MULTIPLIER,
    is_expiry_day, CAPITAL, AI_AUTO_TRADE_DEFAULT, AI_MIN_CONVICTION,
    LOG_DIR, LOG_COLS, BASE_DIR, MIN_CONFIDENCE_SCORE,
    MAX_OPTION_CHAIN_AGE_SECONDS,
)
from utils.logger import get_logger
from core.signal_audit import get_signal_auditor
from core.ai_copilot import build_ai_trade_metadata

logger = get_logger("foreground_scanner")


def _is_fresh_option_chain(data: Dict[str, Any], now_ts: Optional[float] = None) -> bool:
    """Only allow automatic entries using a timestamped, recent option-chain snapshot."""
    try:
        age = (time.time() if now_ts is None else now_ts) - float(data["_fetched_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= age <= MAX_OPTION_CHAIN_AGE_SECONDS


def _validate_ai_entry(
    copilot: Optional[Any],
    idx: str,
    market_data: Dict[str, Any],
    signal: str,
    conf_score: int,
    ai_auto_trade: bool,
    active_trades_count: int,
) -> Tuple[bool, int, str, str, Dict[str, Any]]:
    """Validate automatic entries with AI; never treat a validation failure as approval."""
    if not ai_auto_trade:
        return True, conf_score, "BUY", "Rule Engine Autonomous Signal", {}

    try:
        if not copilot or not copilot.is_configured():
            raise RuntimeError("AI validator is not configured")
        result = copilot.analyze_market_and_signals(
            idx, market_data, signal, conf_score,
            active_trades_count=active_trades_count,
        )
        score = int(result.get("conviction_score", 0))
        recommendation = str(result.get("recommendation", "AVOID_WAIT"))
        analysis = dict(result)
        summary = build_ai_trade_metadata(analysis)["ai_reasoning"]
        approved = score >= AI_MIN_CONVICTION and "BUY" in recommendation
        return approved, score, recommendation, str(summary), analysis
    except Exception as exc:
        logger.warning("[%s] AI validation failed; blocking entry: %s", idx, exc)
        failure = {
            "recommendation": "AI_VALIDATION_FAILED",
            "reasoning_summary": f"AI validation failed: {exc}",
        }
        return False, 0, "AI_VALIDATION_FAILED", failure["reasoning_summary"], failure


# Module-level state cache across foreground refreshes
_scanner_state: Dict[str, Any] = {
    "latest_states": {},
    "signal_buffers": {idx: [] for idx in INDEX_CONFIG},
    "last_signals": {idx: "WAIT" for idx in INDEX_CONFIG},
    "spot_histories": {idx: [] for idx in INDEX_CONFIG},
    "pcr_histories": {idx: [] for idx in INDEX_CONFIG},
    "prev_dfs": {idx: None for idx in INDEX_CONFIG},
    "oi_baselines": {idx: None for idx in INDEX_CONFIG},
    "trade_logs": {idx: [] for idx in INDEX_CONFIG},
    "last_sl_times": {idx: None for idx in INDEX_CONFIG},
    "ai_analyses": {idx: None for idx in INDEX_CONFIG},
    "total_scans": 0,
    "last_scan_time": None,
    "last_scan_ts": 0.0,
    "status": "READY",
}


def get_scanner_status() -> Dict[str, Any]:
    """Return diagnostic telemetry for Activity/Health tab and app header."""
    enabled = bool(getattr(config, "ENABLE_BACKGROUND_SCANNER", True))
    return {
        "running": enabled,
        "status": "RUNNING (100% Foreground Loop)" if enabled else "DISABLED",
        "total_scans": _scanner_state["total_scans"],
        "last_scan": _scanner_state["last_scan_time"] or "Awaiting first cycle",
        "indices": list(INDEX_CONFIG.keys()),
    }


def get_latest_index_state(idx: str) -> Optional[Dict[str, Any]]:
    """Return latest evaluated snapshot for a specific index."""
    return _scanner_state["latest_states"].get(idx)


def get_index_trade_log(idx: str) -> List[Dict[str, Any]]:
    """Return current trade log for a specific index."""
    return list(_scanner_state["trade_logs"].get(idx, []))


def set_index_trade_log(idx: str, tlog: List[Dict[str, Any]]) -> None:
    """Update in-memory trade log for an index."""
    _scanner_state["trade_logs"][idx] = list(tlog)


def run_foreground_market_scan(
    fetcher: Any,
    signal_engine: Any,
    risk_mgr: Any,
    trade_mgr: Any,
    journal: Any,
    copilot: Optional[Any] = None,
    ai_auto_trade: Optional[bool] = None,
    min_interval: float = 1.5,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Run sequential foreground scan across NIFTY, BANKNIFTY, and FINNIFTY.
    Throttled by min_interval (default 1.5s) to prevent redundant API spam.
    """
    if not getattr(config, "ENABLE_BACKGROUND_SCANNER", True):
        _scanner_state["status"] = "DISABLED"
        return _scanner_state["latest_states"]

    now_ts = time.time()
    if not force and (now_ts - _scanner_state["last_scan_ts"]) < min_interval:
        return _scanner_state["latest_states"]

    _scanner_state["last_scan_ts"] = now_ts
    auditor = get_signal_auditor()

    if ai_auto_trade is None:
        try:
            import streamlit as st
            ai_auto_trade = st.session_state.get("ai_auto_trade", AI_AUTO_TRADE_DEFAULT)
        except Exception:
            ai_auto_trade = AI_AUTO_TRADE_DEFAULT

    now_ist = datetime.datetime.now(IST)
    now_time = now_ist.time()
    in_window = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME)
    min_conf_score = getattr(config, "MIN_CONFIDENCE_SCORE", 30)

    # Load initial trade logs if empty
    for idx in INDEX_CONFIG:
        if not _scanner_state["trade_logs"][idx]:
            try:
                import streamlit as st
                session_tlog = st.session_state.get(f"trade_log_{idx}", [])
                if session_tlog:
                    _scanner_state["trade_logs"][idx] = session_tlog
                elif hasattr(trade_mgr, "load_log"):
                    _scanner_state["trade_logs"][idx] = trade_mgr.load_log(idx)
            except Exception:
                if hasattr(trade_mgr, "load_log"):
                    _scanner_state["trade_logs"][idx] = trade_mgr.load_log(idx)

    # ─────────────────────────────────────────────────────────────
    # SEQUENTIAL SCAN: NIFTY -> BANKNIFTY -> FINNIFTY
    # ─────────────────────────────────────────────────────────────
    for idx in INDEX_CONFIG:
        try:
            _scan_single_index(
                idx=idx,
                fetcher=fetcher,
                signal_engine=signal_engine,
                risk_mgr=risk_mgr,
                trade_mgr=trade_mgr,
                journal=journal,
                copilot=copilot,
                auditor=auditor,
                now_ist=now_ist,
                in_window=in_window,
                ai_auto_trade=ai_auto_trade,
                min_conf_score=min_conf_score,
            )
        except Exception as e:
            logger.error("Error during foreground scan of %s: %s", idx, e, exc_info=True)

    _scanner_state["total_scans"] += 1
    _scanner_state["last_scan_time"] = now_ist.strftime("%I:%M:%S %p")
    _scanner_state["status"] = "RUNNING"

    # Push updated state to Streamlit session_state if available
    try:
        import streamlit as st
        for idx in INDEX_CONFIG:
            st.session_state[f"latest_state_{idx}"] = _scanner_state["latest_states"].get(idx)
            st.session_state[f"trade_log_{idx}"] = _scanner_state["trade_logs"].get(idx, [])
            st.session_state[f"signal_buffer_{idx}"] = _scanner_state["signal_buffers"].get(idx, [])
            st.session_state[f"last_signal_{idx}"] = _scanner_state["last_signals"].get(idx, "WAIT")
        st.session_state["_scanner_telemetry"] = get_scanner_status()
    except Exception:
        pass

    return _scanner_state["latest_states"]


def _scan_single_index(
    idx: str,
    fetcher: Any,
    signal_engine: Any,
    risk_mgr: Any,
    trade_mgr: Any,
    journal: Any,
    copilot: Optional[Any],
    auditor: Any,
    now_ist: datetime.datetime,
    in_window: bool,
    ai_auto_trade: bool,
    min_conf_score: int,
) -> None:
    """Evaluate one index: option chain, signals, open trade exits, and autonomous entries."""
    cfg = INDEX_CONFIG[idx]
    lot = cfg["lot"]
    step = cfg["step"]
    rng = cfg["rng"]

    # 1. Fetch live option chain
    data = None
    if fetcher:
        try:
            data = fetcher.fetch_option_chain(idx)
        except Exception as e:
            logger.warning("Foreground fetch error for %s: %s", idx, e)

    cache_file = os.path.join(BASE_DIR, f"last_data_{idx}.json")
    if data is None:
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
    else:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    if not data or "records" not in data:
        return

    market_data_fresh = _is_fresh_option_chain(data)

    records = data["records"]["data"]
    spot = float(data["records"]["underlyingValue"])

    # Check live WebSocket tick for underlying spot if active
    if fetcher and hasattr(fetcher, "ws_mgr") and fetcher.ws_mgr:
        tok = fetcher.index_tokens.get(idx, {}).get("token")
        if tok:
            ws_spot = fetcher.ws_mgr.get_live_ltp(str(tok))
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
    if fetcher and hasattr(fetcher, "get_15m_trend"):
        try:
            trend_15m_info = fetcher.get_15m_trend(idx, current_spot=spot)
        except Exception:
            trend_15m_info = {"trend": "NEUTRAL", "ema20": 0.0}

    # 4. Market Data Computation
    prev_df = _scanner_state["prev_dfs"].get(idx)
    oi_baseline = _scanner_state["oi_baselines"].get(idx)
    pcr_history = _scanner_state["pcr_histories"].get(idx, [])
    spot_history = _scanner_state["spot_histories"].get(idx, [])

    try:
        md = signal_engine.compute_market_data(
            df, spot, step, idx, spot_history, pcr_history, prev_df, oi_baseline,
            trend_15m=trend_15m_info.get("trend", "NEUTRAL"),
            trend_15m_ema=trend_15m_info.get("ema20", 0.0),
        )
    except TypeError:
        md = signal_engine.compute_market_data(
            df, spot, step, idx, spot_history, pcr_history, prev_df, oi_baseline
        )
        if isinstance(md, dict):
            md["trend_15m"] = trend_15m_info.get("trend", "NEUTRAL")
            md["trend_15m_ema"] = trend_15m_info.get("ema20", 0.0)

    # Update running histories
    _scanner_state["prev_dfs"][idx] = md.get("prev_df")
    _scanner_state["oi_baselines"][idx] = md.get("oi_baseline")
    _scanner_state["pcr_histories"][idx] = md.get("pcr_history", [])
    _scanner_state["spot_histories"][idx] = md.get("spot_history", [])

    # 5. Signal Generation, Traps, Buffer Confirmation
    raw_signal, raw_conf, filter_reason = signal_engine.generate_signal(md, in_window)
    trap = signal_engine.detect_trap(
        spot, md["support"], md["resistance"],
        md["total_ce_delta"], md["total_pe_delta"]
    )

    buf = _scanner_state["signal_buffers"].get(idx, [])
    final_signal, final_conf, updated_buf = signal_engine.confirm_signal(
        raw_signal, raw_conf, buf
    )
    _scanner_state["signal_buffers"][idx] = updated_buf

    # 6. Check SL / Target / Trailing / Exits on Open Trades
    tlog = _scanner_state["trade_logs"].get(idx, [])
    stop_losses_before = {
        id(trade): trade.get("Stop Loss")
        for trade in tlog
        if trade.get("Status") == "OPEN"
    }
    events = []
    try:
        events = trade_mgr.update_live_prices(
            idx,
            tlog,
            records,
            now_ist,
            fetcher=fetcher,
            quote_observed_at=data.get("_fetched_at"),
        )
    except Exception as e:
        logger.warning("Foreground SL/Target update error on %s: %s", idx, e)

    trade_db = getattr(journal, "db", None)
    if trade_db:
        for trade in tlog:
            if (
                trade.get("Status") != "OPEN"
                or trade.get("_live_price_is_stale")
                or not trade.get("_live_price_updated_at")
            ):
                continue
            try:
                trade_db.update_trade_live_price(
                    trade.get("trade_id") or trade.get("_journal_id", ""),
                    trade.get("Live Price"),
                    trade["_live_price_updated_at"],
                )
            except Exception as price_error:
                logger.warning(
                    "Failed to persist live price for %s trade %s: %s",
                    idx,
                    trade.get("trade_id") or trade.get("_journal_id", "unknown"),
                    price_error,
                )

    for trade in tlog:
        old_stop = stop_losses_before.get(id(trade))
        if old_stop is None or trade.get("Status") != "OPEN":
            continue
        try:
            stop_changed = float(trade.get("Stop Loss") or 0) != float(old_stop or 0)
        except (TypeError, ValueError):
            stop_changed = trade.get("Stop Loss") != old_stop
        if stop_changed and journal and hasattr(journal, "update_trade_stop_loss"):
            journal.update_trade_stop_loss(
                trade.get("_journal_id", ""),
                float(trade.get("Stop Loss") or 0),
                trade,
            )

    if events:
        for ev in events:
            if ev.get("type") == "SL_HIT":
                _scanner_state["last_sl_times"][idx] = now_ist
            _scanner_state["last_signals"][idx] = "WAIT"

        trade_mgr.save_log(idx, tlog)

        for ev in events:
            trade = ev["trade"]
            if journal:
                try:
                    journal.update_trade(
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
                except Exception as e_j:
                    logger.warning("Error updating journal on exit: %s", e_j)

            # Send Telegram exit alert
            try:
                if trade_mgr and hasattr(trade_mgr, "notifier") and trade_mgr.notifier:
                    res_str = str(trade.get("Result", "CLOSED"))
                    emoji = "🟢" if "WIN" in res_str else ("🔴" if "LOSS" in res_str or "SL" in res_str else "🛡️")
                    trade_mgr.notifier.send_exit_alert(
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
                logger.warning("Error sending exit alert for %s: %s", idx, e_exit_ntf)

    # 7. Don't enter if trade already open for this index (Strict: 1 open trade per index)
    open_exists = any(t.get("Status") == "OPEN" for t in tlog)
    if not open_exists and hasattr(journal, "get_all_trades"):
        try:
            open_exists = any(t.get("Status") == "OPEN" and str(t.get("Index") or "").upper() == idx for t in journal.get_all_trades())
        except Exception:
            pass

    if open_exists and final_signal in ("BUY CE", "BUY PE"):
        final_signal = "WAIT"
        final_conf = "LOW"

    # 8. Confidence Score & Sideways Analysis
    conf_score = signal_engine.compute_confidence_score(md, raw_signal, trap)
    sideways_is, sideways_strength = signal_engine.detect_sideways(
        md["spot_history"], md["pcr"]
    )
    sideways_info = {"is_sideways": sideways_is, "strength": sideways_strength}

    # Portfolio-wide trade checks
    portfolio_today_trades = []
    for _i in INDEX_CONFIG:
        portfolio_today_trades.extend(_scanner_state["trade_logs"].get(_i, []))

    trades_today_count = len([t for t in portfolio_today_trades if t.get("Entry Time")])
    cooldown_info = risk_mgr.should_allow_trade(
        idx, tlog, now_ist, portfolio_trades=portfolio_today_trades
    )
    daily_limits = risk_mgr.check_daily_limits(portfolio_today_trades)

    # 9. Autonomous Trade Entry Evaluation
    if final_signal in ("BUY CE", "BUY PE") and final_conf in ("HIGH", "MEDIUM"):
        atm_row = md.get("atm_row", {})
        ce_price = round(float(atm_row.get("CE LTP", 0)), 2)
        pe_price = round(float(atm_row.get("PE LTP", 0)), 2)
        ep = ce_price if final_signal == "BUY CE" else pe_price

        qty, sl_p, tgt_p, ml, tp = risk_mgr.calc_trade_with_atr(
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
        can_afford = False
        margin_check_error = False
        try:
            cap_info = {"base_capital": CAPITAL, "current_balance": CAPITAL}
            if hasattr(journal, "db") and journal.db:
                cap_info = journal.db.get_or_init_capital(CAPITAL)
            if cap_info.get("_source") == "local_cache":
                margin_check_error = True
                logger.warning(
                    "[%s] Blocking entry because shared capital is unavailable; "
                    "this process has only a local cache.",
                    idx,
                )
            else:
                portfolio_stats = risk_mgr.calculate_portfolio_equity(
                    cap_info.get("base_capital", CAPITAL),
                    portfolio_today_trades,
                    all_time_pnl=cap_info.get("cumulative_realized_pnl", 0.0),
                )
                can_afford, _ = risk_mgr.can_afford_trade(ep, qty, portfolio_stats.get("available_margin", CAPITAL))
        except Exception:
            margin_check_error = True

        can_enter = (
            not open_exists
            and market_data_fresh
            and not too_late
            and not price_too_low
            and not oi_unusual
            and conf_score >= min_conf_score
            and not daily_trades_exceeded
            and daily_allowed
            and trade_allowed
            and can_afford
        )

        last_sig = _scanner_state["last_signals"].get(idx)

        if can_enter and final_signal != last_sig:
            ai_conviction_ok, ai_pre_score, ai_pre_rec, ai_pre_summary, ai_analysis = _validate_ai_entry(
                copilot=copilot,
                idx=idx,
                market_data=md,
                signal=final_signal,
                conf_score=conf_score,
                ai_auto_trade=ai_auto_trade,
                active_trades_count=len([t for t in tlog if t.get("Status") == "OPEN"]),
            )
            if ai_auto_trade and ai_conviction_ok:
                _scanner_state["ai_analyses"][idx] = {
                    "conviction_score": ai_pre_score,
                    "recommendation": ai_pre_rec,
                    "reasoning_summary": ai_pre_summary,
                    **ai_analysis,
                }
            if ai_auto_trade and not ai_conviction_ok:
                logger.info("[%s] AI blocked trade: conviction %d/%d, rec=%s", idx, ai_pre_score, AI_MIN_CONVICTION, ai_pre_rec)

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
                    "Confidence Score": ai_pre_score if ai_auto_trade else conf_score,
                    "_ai_generated": ai_auto_trade,
                    "_ai_conviction": ai_pre_score,
                    "_ai_reasoning": ai_pre_summary,
                }
                ai_metadata = build_ai_trade_metadata(
                    ai_analysis,
                    ai_pre_summary,
                    "AUTONOMOUS_AI" if ai_auto_trade else "RULE_ENGINE",
                )
                trade_entry["_ai_reasoning"] = ai_metadata["ai_reasoning"]
                trade_entry["_ai_conviction"] = ai_metadata["ai_conviction"] if ai_metadata["ai_conviction"] is not None else ai_pre_score
                trade_entry["_ai_generated"] = ai_auto_trade

                journal_id = ""
                try:
                    if journal:
                        journal_id = journal.record_trade(trade_entry, {
                            "pcr": md["pcr"], "vwap": md["vwap_proxy"],
                            "oi_delta_ce": md["total_ce_delta"],
                            "oi_delta_pe": md["total_pe_delta"],
                            "confidence_score": ai_pre_score if ai_auto_trade else conf_score,
                            "pcr_momentum": md["pcr_momentum"],
                            "trap": trap, "buffer_state": updated_buf[-3:],
                            "ai_validated": ai_auto_trade,
                            **ai_metadata,
                        }, require_no_open=True)
                except Exception as e:
                    logger.error("Atomic position reservation failed for %s: %s", idx, e)

                if not journal_id:
                    _scanner_state["last_signals"][idx] = final_signal
                    auditor.log_event(
                        idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                        final_conf=final_conf, conf_score=conf_score, ai_score=ai_pre_score,
                        ai_rec="POSITION_GUARD_BLOCKED", ai_reasoning="Atomic open-position reservation failed or another scanner already opened a position.",
                        status="REJECTED", rejection_code="POSITION_RESERVATION_FAILED",
                        rejection_detail="No trade was opened because the atomic open-position guard did not approve the reservation.",
                        now_ist=now_ist, force_log=True
                    )
                else:
                    trade_entry["_journal_id"] = journal_id
                    tlog.insert(0, trade_entry)
                    _scanner_state["trade_logs"][idx] = tlog
                    trade_mgr.save_log(idx, tlog)
                    _scanner_state["last_signals"][idx] = final_signal

                    # Telegram alert
                    try:
                        signal_label = f"🤖 [AUTONOMOUS AI✅] {final_signal}" if ai_auto_trade else f"⚡ [AUTO-BOT] {final_signal}"
                        trade_mgr.notifier.send_signal_alert(
                            idx=idx, signal=signal_label,
                            strike=md["atm_actual"], spot=round(spot, 2),
                            entry=ep, sl=sl_p, tgt=tgt_p,
                            qty=qty, ml=ml, tp=tp,
                            conf=final_conf, score=ai_pre_score if ai_auto_trade else conf_score,
                            time_str=now_str,
                        )
                    except Exception as e:
                        logger.warning("Telegram alert error: %s", e)

                    logger.info(
                        "[%s] FOREGROUND AUTONOMOUS TRADE ENTERED: %s @ Strike %s | EP=%s SL=%s Tgt=%s Qty=%s Score=%s",
                        idx, final_signal, md["atm_actual"], ep, sl_p, tgt_p, qty, ai_pre_score
                    )
                    auditor.log_event(
                        idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                        final_conf=final_conf, conf_score=conf_score, ai_score=ai_pre_score,
                        ai_rec=ai_pre_rec, ai_reasoning=ai_pre_summary, status="EXECUTED",
                        rejection_code="NONE",
                        rejection_detail=f"Executed {final_signal} at ₹{ep:.2f} (Rule: {conf_score}/100, AI: {ai_pre_score}/100)",
                        now_ist=now_ist, force_log=True
                    )
            else:
                _scanner_state["last_signals"][idx] = final_signal
                rej_code = "AI_CONVICTION_LOW" if ai_pre_score < AI_MIN_CONVICTION else "AI_REC_NOT_BUY"
                rej_det = f"AI Conviction {ai_pre_score}/100 is below {AI_MIN_CONVICTION} target (Rec: {ai_pre_rec})."
                auditor.log_event(
                    idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                    final_conf=final_conf, conf_score=conf_score, ai_score=ai_pre_score,
                    ai_rec=ai_pre_rec, ai_reasoning=ai_pre_summary, status="REJECTED",
                    rejection_code=rej_code, rejection_detail=rej_det,
                    now_ist=now_ist, force_log=True
                )
        elif not can_enter:
            if open_exists:
                rej_code = "POSITION_ALREADY_OPEN"
                rej_det = f"Open trade already active on {idx}. Multiple positions blocked (Strict 1 open trade rule)."
            elif too_late:
                rej_code = "TIME_CUTOFF"
                rej_det = f"Time {now_ist.strftime('%I:%M %p')} is past {NO_NEW_TRADE_TIME.strftime('%I:%M %p')} cutoff."
            elif price_too_low:
                rej_code = "PREMIUM_TOO_LOW"
                rej_det = f"Option premium ₹{ep:.2f} is below ₹{MIN_ENTRY_PRICE} minimum."
            elif not market_data_fresh:
                rej_code = "STALE_MARKET_DATA"
                rej_det = f"Option-chain data is missing a fresh timestamp or is older than {MAX_OPTION_CHAIN_AGE_SECONDS} seconds."
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
            elif conf_score < min_conf_score:
                rej_code = "RULE_SCORE_LOW"
                rej_det = f"Confidence score {conf_score}/100 is below minimum {min_conf_score}."
            elif not can_afford:
                if margin_check_error:
                    rej_code = "MARGIN_CHECK_FAILED"
                    rej_det = "Account margin could not be verified; entry blocked."
                else:
                    rej_code = "INSUFFICIENT_MARGIN"
                    rej_det = "Available account margin is insufficient for 1 lot."
            else:
                rej_code = "GUARD_BLOCKED"
                rej_det = "Pre-trade risk guard blocked entry."

            auditor.log_event(
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
            auditor.log_event(
                idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                final_conf=final_conf, conf_score=conf_score, ai_score=None, ai_rec="AVOID",
                ai_reasoning=f"Sideways regime detected ({sideways_strength}).",
                status="REJECTED", rejection_code=rej_code, rejection_detail=rej_det,
                now_ist=now_ist
            )
        elif filter_reason:
            rej_code = "FILTER_BLOCKED"
            auditor.log_event(
                idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                final_conf=final_conf, conf_score=conf_score, ai_score=None, ai_rec="WAIT",
                ai_reasoning=filter_reason, status="REJECTED", rejection_code=rej_code,
                rejection_detail=filter_reason, now_ist=now_ist
            )
        else:
            auditor.log_event(
                idx=idx, spot=spot, md=md, raw_signal=raw_signal, final_signal=final_signal,
                final_conf=final_conf, conf_score=conf_score, ai_score=None, ai_rec="WAIT",
                ai_reasoning="Awaiting clear trend confirmation.", status="NEUTRAL_WAIT",
                rejection_code="NO_SETUP",
                rejection_detail=f"Spot {spot:.2f} vs VWAP {md['vwap_proxy']:.2f}, PCR {md['pcr']:.2f} ({md['pcr_momentum']}).",
                now_ist=now_ist
            )

        if final_signal == "WAIT" and not open_exists:
            if _scanner_state["last_signals"].get(idx) not in ("WAIT",):
                _scanner_state["last_signals"][idx] = "WAIT"

    # 10. Cache snapshot for instant UI rendering (< 5ms)
    _scanner_state["latest_states"][idx] = {
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
        "updated_at": now_ist.strftime("%I:%M:%S %p"),
        "is_live": True,
    }
