"""
V12 PRO MAX — Per-index renderer and open trades renderer.
Orchestrates signal engine, trade manager, risk manager, and UI components.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import datetime

from config import (
    INDEX_CONFIG, CAPITAL, DAILY_TGT, IST, LOG_COLS,
    MARKET_OPEN_TIME, MARKET_CLOSE_TIME,
    NO_NEW_TRADE_TIME, MIN_ENTRY_PRICE, is_expiry_day,
    MAX_DAILY_LOSSES, COOLDOWN_SECONDS,
    BASE_DIR, LOG_DIR,
)
from ui.components import (
    render_kpi_grid, render_filter_grid, render_signal_card,
    render_trade_entry_card, render_trap_alert, render_tracker_grid,
    render_risk_card, render_open_positions_summary, render_open_trade_detail,
    render_expander_open_trade, render_empty_open_trades,
    normalize_trade, render_trade_card_html,
)
from utils.logger import get_logger

logger = get_logger("renderer")

# ── SESSION KEY HELPER ──
def sk(idx, key):
    return f"{idx}_{key}"


def init_state(idx):
    """Initialize per-index session state keys."""
    defaults = [
        ("trade_log", []),
        ("last_signal", "WAIT"),
        ("last_played", "WAIT"),
        ("signal_buffer", []),
        ("pcr_history", []),
        ("spot_history", []),
        ("prev_df", None),
        ("oi_baseline", None),
        ("last_sl_time", None),       # cooldown tracking
    ]
    for k, v in defaults:
        if sk(idx, k) not in st.session_state:
            st.session_state[sk(idx, k)] = v


def load_log(idx):
    """Load trade log from CSV file for today."""
    import os
    f = os.path.join(LOG_DIR, f"trade_log_{idx}_{datetime.datetime.now(IST).strftime('%Y-%m-%d')}.csv")
    if os.path.exists(f):
        df = pd.read_csv(f, encoding="utf-8")
        for c in LOG_COLS:
            if c not in df.columns:
                df[c] = None
        return df[LOG_COLS].to_dict("records")
    return []


def render_index(idx, fetcher, signal_engine, risk_mgr, trade_mgr, journal):
    """
    Render a full index tab (NIFTY / BANKNIFTY / FINNIFTY).
    Fetches data, generates signals, manages trades, renders UI.
    Core signal logic is UNTOUCHED — called via signal_engine.
    """
    cfg = INDEX_CONFIG[idx]
    lot = cfg["lot"]
    step = cfg["step"]
    rng = cfg["rng"]
    tlog_key = sk(idx, "trade_log")

    # ── MARKET TIME CHECK ──
    import json
    import os
    now_ist = datetime.datetime.now(IST)
    now_time = now_ist.time()
    in_window = MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME
    cache_file = os.path.join(BASE_DIR, f"last_data_{idx}.json")

    data = None
    if not in_window:
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                logger.info(f"Loaded off-market cache for {idx} from file")
            except Exception as e:
                logger.warning(f"Failed to load cache file for {idx}: {e}")

    if data is None:
        data = fetcher.fetch_option_chain(idx)
        if data is None:
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as f:
                        data = json.load(f)
                    logger.warning(f"Live fetch failed. Fallback to cache for {idx}")
                except Exception:
                    pass
        else:
            # Save cache file for off-market hours
            try:
                with open(cache_file, "w") as f:
                    json.dump(data, f)
            except Exception as e:
                logger.warning(f"Failed to save cache file for {idx}: {e}")

    if data is None:
        st.error(f"❌ {idx} data unavailable. Retrying...")
        return

    records = data["records"]["data"]
    spot = data["records"]["underlyingValue"]

    # ── BUILD DATAFRAME ──
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
        st.warning(f"No {idx} data. Market may be closed.")
        return

    # ── COMPUTE MARKET DATA (via signal engine) ──
    prev_df = st.session_state[sk(idx, "prev_df")]
    oi_baseline = st.session_state[sk(idx, "oi_baseline")]
    pcr_history = st.session_state[sk(idx, "pcr_history")]
    spot_history = st.session_state[sk(idx, "spot_history")]

    md = signal_engine.compute_market_data(
        df, spot, step, idx, spot_history, pcr_history, prev_df, oi_baseline
    )

    # Save updated state
    st.session_state[sk(idx, "prev_df")] = md["prev_df"]
    st.session_state[sk(idx, "oi_baseline")] = md["oi_baseline"]
    st.session_state[sk(idx, "pcr_history")] = md["pcr_history"]
    st.session_state[sk(idx, "spot_history")] = md["spot_history"]
    df = md["df"]

    # ── FILTERS ──
    now_ist = datetime.datetime.now(IST)
    now_time = now_ist.time()
    in_window = MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME

    # ── GENERATE SIGNAL (VERBATIM core logic) ──
    signal, confidence, filter_reason = signal_engine.generate_signal(md, in_window)

    # ── TRAP DETECTION (VERBATIM) ──
    trap = signal_engine.detect_trap(
        spot, md["support"], md["resistance"],
        md["total_ce_delta"], md["total_pe_delta"]
    )

    # ── SIGNAL BUFFER CONFIRMATION (VERBATIM) ──
    buf = st.session_state[sk(idx, "signal_buffer")]
    final_signal, final_conf, updated_buf = signal_engine.confirm_signal(
        signal, confidence, buf
    )
    st.session_state[sk(idx, "signal_buffer")] = updated_buf

    # ── DON'T ENTER IF TRADE ALREADY OPEN ──
    open_exists = any(t.get("Status") == "OPEN" for t in st.session_state[tlog_key])
    if open_exists and final_signal in ("BUY CE", "BUY PE"):
        final_signal = "WAIT"
        final_conf = "LOW"

    # ── CONFIDENCE SCORE (display only) ──
    conf_score = signal_engine.compute_confidence_score(md, signal, trap)

    # ── SIDEWAYS DETECTION (advisory) ──
    sideways_is, sideways_strength = signal_engine.detect_sideways(
        md["spot_history"], md["pcr"]
    )
    sideways_info = {"is_sideways": sideways_is, "strength": sideways_strength}

    # ── RISK CHECKS ──
    cooldown_info = risk_mgr.should_allow_trade(
        idx, st.session_state[tlog_key], now_ist
    )

    ce_price = round(float(md["atm_row"]["CE LTP"]), 2)
    pe_price = round(float(md["atm_row"]["PE LTP"]), 2)

    # ── CHECK SL/TARGET ON OPEN TRADES ──
    events = trade_mgr.update_live_prices(
        idx, st.session_state[tlog_key], records, now_ist
    )
    if events:
        for ev in events:
            if ev["type"] == "SL_HIT":
                st.session_state[sk(idx, "last_sl_time")] = now_ist
            st.session_state[sk(idx, "last_signal")] = "WAIT"
        trade_mgr.save_log(idx, st.session_state[tlog_key])
        # Record exits in journal
        for ev in events:
            trade = ev["trade"]
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

    # ── KPI DISPLAY ──
    st.markdown(render_kpi_grid(
        idx, spot, md["atm_actual"], md["pcr"], md["bias"],
        md["support"], md["resistance"],
        md.get("secondary_support"), md.get("secondary_resistance")
    ), unsafe_allow_html=True)

    # ── FILTER STATUS ──
    oi_active = md.get("oi_active", True)
    st.markdown(render_filter_grid(
        in_window, oi_active, md["spot_vs_vwap"], md["vwap_proxy"],
        md["pcr_momentum"], md["total_ce_delta"], md["total_pe_delta"],
        sideways_info=sideways_info, cooldown_info=cooldown_info
    ), unsafe_allow_html=True)

    # ── TRAP / SIGNAL ──
    if trap != "NONE":
        st.markdown(render_trap_alert(trap), unsafe_allow_html=True)

    st.markdown(render_signal_card(
        idx, final_signal, final_conf, signal, confidence,
        md["pcr"], updated_buf, filter_reason, conf_score,
        oi_unusual=md.get("oi_unusual_activity", False),
        spot=spot, atm=md["atm_actual"]
    ), unsafe_allow_html=True)

    # ── RISK MANAGEMENT CARD ──
    # Show ATR SL info if we have enough history
    atr_sl_display = None
    if len(md["spot_history"]) >= 14:
        from config import ATR_PERIOD, ATR_SL_MULTIPLIER
        import statistics
        diffs = [abs(md["spot_history"][i] - md["spot_history"][i-1])
                 for i in range(1, len(md["spot_history"]))]
        if len(diffs) >= ATR_PERIOD:
            atr_val = statistics.mean(diffs[-ATR_PERIOD:])
            atr_sl_display = round(atr_val * ATR_SL_MULTIPLIER, 2)

    daily_limits = risk_mgr.check_daily_limits(st.session_state[tlog_key])
    consec_losses = 0
    closed_trades = [t for t in st.session_state[tlog_key] if t.get("Status") == "CLOSED"]
    for t in closed_trades:
        if "LOSS" in str(t.get("Result", "")):
            consec_losses += 1
        else:
            break

    cooldown_remaining = 0
    closed_trades_idx = [t for t in st.session_state[tlog_key] if t.get("Status") == "CLOSED" and t.get("Result", "")]
    if closed_trades_idx:
        last_closed = closed_trades_idx[0]
        if "LOSS" in str(last_closed.get("Result", "")):
            exit_time_str = last_closed.get("Exit Time", "")
            if exit_time_str:
                try:
                    exit_time = datetime.datetime.strptime(
                        exit_time_str, "%I:%M:%S %p"
                    ).replace(
                        year=now_ist.year,
                        month=now_ist.month,
                        day=now_ist.day,
                        tzinfo=IST,
                    )
                    # Handle midnight rollover
                    if exit_time > now_ist:
                        exit_time -= datetime.timedelta(days=1)
                    elapsed = (now_ist - exit_time).total_seconds()
                    if elapsed < COOLDOWN_SECONDS:
                        cooldown_remaining = int(COOLDOWN_SECONDS - elapsed)
                except Exception:
                    pass

    risk_html = render_risk_card(
        atr_sl=atr_sl_display,
        cooldown_remaining=cooldown_remaining,
        daily_losses=consec_losses,
        max_daily_losses=MAX_DAILY_LOSSES
    )
    if risk_html:
        st.markdown(risk_html, unsafe_allow_html=True)

    # ── LOG SIGNAL (ENTER TRADE) ──
    if final_signal in ("BUY CE", "BUY PE") and final_conf in ("HIGH", "MEDIUM"):
        ep = ce_price if final_signal == "BUY CE" else pe_price
        lbl = "CE LTP" if final_signal == "BUY CE" else "PE LTP"
        qty, sl_p, tgt_p, ml, tp = risk_mgr.calc_trade_with_atr(
            ep, lot, md["spot_history"]
        )

        st.markdown(render_trade_entry_card(
            lbl, md["atm_actual"], ep, sl_p, tgt_p, qty, ml, tp
        ), unsafe_allow_html=True)

        # Check cooldown and daily limits before entering
        trade_allowed = cooldown_info[0]
        daily_allowed = daily_limits[0]

        # ── PRE-ENTRY GUARDS ──
        # 1. Block new entries after 3:20 PM (auto-square at 3:25 — not worth entering)
        too_late = now_ist.time() >= NO_NEW_TRADE_TIME
        # 2. Block if option premium is too cheap (illiquid / worthless)
        #    EXCEPTION: skip on expiry day — cheap options move very fast
        expiry_today = is_expiry_day(idx)
        price_too_low = ep < MIN_ENTRY_PRICE and not expiry_today
        # 3. Block if unusual OI spike detected (manipulation risk)
        oi_unusual = md.get("oi_unusual_activity", False)

        if too_late:
            st.warning(f"⏰ No new entries after {NO_NEW_TRADE_TIME.strftime('%I:%M %p')} — auto-square soon")
        elif price_too_low:
            st.warning(f"⚠️ Option price ₹{ep} is too low (min ₹{MIN_ENTRY_PRICE}) — skipping")
        elif oi_unusual:
            st.warning("🚨 Unusual OI activity detected — holding off entry")
        elif conf_score < 30:
            st.warning(f"⚠️ Confidence score ({conf_score}) is too low to enter trade (Minimum: 30)")
        elif expiry_today and ep < MIN_ENTRY_PRICE:
            st.info(f"📅 Expiry day — cheap option ₹{ep} allowed (fast moves expected)")

        can_enter = not too_late and not price_too_low and not oi_unusual and conf_score >= 30

        if (final_signal != st.session_state[sk(idx, "last_signal")]
                and trade_allowed and daily_allowed and can_enter):
            now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            trade_entry = {
                "Entry Time": now_str, "Exit Time": None,
                "Index": idx, "Signal": final_signal,
                "Spot": round(spot, 2), "Strike": md["atm_actual"],
                "Entry Price": ep, "Live Price": ep,
                "Exit Price": None, "Stop Loss": sl_p,
                "Target": tgt_p, "Qty": qty,
                "Max Loss ₹": ml, "Target P&L ₹": tp,
                "Actual P&L ₹": None, "Status": "OPEN",
                "Result": "⏳ OPEN",
            }
            st.session_state[tlog_key].insert(0, trade_entry)
            trade_mgr.save_log(idx, st.session_state[tlog_key])
            st.session_state[sk(idx, "last_signal")] = final_signal

            # Record in journal
            journal_id = journal.record_trade(trade_entry, {
                "pcr": md["pcr"], "vwap": md["vwap_proxy"],
                "oi_delta_ce": md["total_ce_delta"],
                "oi_delta_pe": md["total_pe_delta"],
                "confidence_score": conf_score,
                "pcr_momentum": md["pcr_momentum"],
                "trap": trap, "buffer_state": updated_buf[-3:],
            })
            trade_entry["_journal_id"] = journal_id

            # Telegram alert
            trade_mgr.notifier.send_signal_alert(
                idx=idx, signal=final_signal,
                strike=md["atm_actual"], spot=round(spot, 2),
                entry=ep, sl=sl_p, tgt=tgt_p,
                qty=qty, ml=ml, tp=tp,
                conf=final_conf, score=conf_score,
                time_str=now_str,
            )
            logger.info(
                f"[{idx}] TRADE ENTERED: {final_signal} | Strike: {md['atm_actual']} | "
                f"Entry: {ep} | SL: {sl_p} | Tgt: {tgt_p} | Conf: {final_conf} | Score: {conf_score}"
            )

        if final_signal != st.session_state[sk(idx, "last_played")]:
            st.markdown(
                '<audio autoplay style="display:none"><source '
                'src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" '
                'type="audio/ogg"></audio>',
                unsafe_allow_html=True,
            )
            st.session_state[sk(idx, "last_played")] = final_signal
        st.success(f"🚨 {idx} {final_conf} CONFIDENCE SIGNAL — {final_signal} CONFIRMED")
    else:
        # Reset last_signal when signal disappears (only if no open trade)
        if (final_signal == "WAIT"
                and st.session_state[sk(idx, "last_signal")] not in ("WAIT",)):
            if not open_exists:
                st.session_state[sk(idx, "last_signal")] = "WAIT"
                st.session_state[sk(idx, "last_played")] = "WAIT"

    # ── TRACKER ──
    log_df = (pd.DataFrame(st.session_state[tlog_key])
              if st.session_state[tlog_key]
              else pd.DataFrame(columns=LOG_COLS))
    closed = log_df[log_df["Status"] == "CLOSED"] if not log_df.empty else pd.DataFrame()
    rpnl = (closed["Actual P&L ₹"].apply(pd.to_numeric, errors="coerce").sum()
            if not closed.empty else 0)
    rc = CAPITAL + rpnl
    prog = max(0.0, min(1.0, rpnl / DAILY_TGT))

    hdr, rcol, tcol = st.columns([4, 1, 1])
    with hdr:
        st.subheader(f"💼 {idx} Tracker")
    with rcol:
        st.write("")
        if st.button("🔄 Reset", key=f"reset_{idx}", use_container_width=True):
            st.session_state[tlog_key] = []
            st.session_state[sk(idx, "last_signal")] = "WAIT"
            st.session_state[sk(idx, "last_played")] = "WAIT"
            st.session_state[sk(idx, "signal_buffer")] = []
            st.session_state[sk(idx, "oi_baseline")] = None
            st.session_state[sk(idx, "prev_df")] = None
            import os
            f = os.path.join(LOG_DIR, f"trade_log_{idx}_{datetime.datetime.now(IST).strftime('%Y-%m-%d')}.csv")
            if os.path.exists(f):
                os.remove(f)
            st.rerun()
    with tcol:
        st.write("")
        if st.button("📨 Test", key=f"test_{idx}", use_container_width=True):
            now_t = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            trade_mgr.notifier.send(
                f"🧪 *V12 {idx} TEST ALERT*\n🟢 SIGNAL: BUY CE\n"
                f"📍 Strike: `{md['atm_actual']}` | Spot: `{round(spot,2)}`\n"
                f"⏰ Time: `{now_t}` ← TEST"
            )
            st.success("📨 Test sent!")

    st.markdown(render_tracker_grid(idx, CAPITAL, len(closed), rpnl, rc, prog),
                unsafe_allow_html=True)
    st.progress(prog, text=f"{idx}: ₹{rpnl:,.0f} / ₹{DAILY_TGT:,} daily target")

    # ── OPTION CHAIN ──
    disp = df.drop(columns=["dist"], errors="ignore")

    def hl(v):
        if isinstance(v, (int, float)):
            if v > 0:
                return "background-color:rgba(16,185,129,0.2);color:#10b981;"
            if v < 0:
                return "background-color:rgba(239,68,68,0.2);color:#ef4444;"
        return ""

    with st.expander(f"{idx} Option Chain & Charts"):
        st.dataframe(
            disp.style.map(hl, subset=["CE OI Δ", "PE OI Δ"]),
            use_container_width=True,
        )
        
        fig1 = px.bar(disp, x="Strike", y=["CE OI", "PE OI"], barmode="group",
                      color_discrete_map={"CE OI": "#10b981", "PE OI": "#ef4444"})
        fig1.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='#a1a1aa', margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig1, use_container_width=True)
        
        fig2 = px.bar(disp, x="Strike", y=["CE OI Δ", "PE OI Δ"], barmode="group",
                      color_discrete_map={"CE OI Δ": "#34d399", "PE OI Δ": "#f87171"})
        fig2.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='#a1a1aa', margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig2, use_container_width=True)

    # ── POSITIONS ──
    with st.expander(f"{idx} Trade Positions"):
        t1, t2 = st.tabs(["🟢 Open", "📋 History"])
        with t1:
            opens = [t for t in st.session_state[tlog_key] if t.get("Status") == "OPEN"]
            if opens:
                ot = opens[0]
                sc = "#34D399" if "CE" in str(ot.get("Signal")) else "#F87171"
                st.markdown(render_expander_open_trade(ot, sc), unsafe_allow_html=True)
                st.write("")
                if st.button(
                    f"❌ Close Position ({idx} {ot.get('Signal')} {ot.get('Strike')})",
                    key=f"close_{idx}_expander",
                    type="primary", use_container_width=True,
                ):
                    lp = float(ot.get("Live Price") or ot.get("Entry Price") or 0)
                    trade_mgr.close_manually(idx, ot, lp)
                    st.session_state[sk(idx, "signal_buffer")] = []
                    st.session_state[sk(idx, "last_signal")] = "WAIT"
                    trade_mgr.save_log(idx, st.session_state[tlog_key])
                    journal.update_trade(ot.get("_journal_id", ""), {
                        "Exit Time": ot.get("Exit Time"),
                        "Exit Price": ot.get("Exit Price"),
                        "Actual P&L ₹": ot.get("Actual P&L ₹"),
                        "Status": "CLOSED", "Result": "🟡 MANUAL",
                    }, ot)
                    st.rerun()
            else:
                st.info("No open position. Waiting for signal...")
        with t2:
            if st.session_state[tlog_key]:
                cols = [
                    "Entry Time", "Exit Time", "Signal", "Strike",
                    "Entry Price", "Exit Price", "Qty",
                    "Actual P&L ₹", "Status", "Result",
                ]
                hdf = pd.DataFrame(st.session_state[tlog_key])
                for c in cols:
                    if c not in hdf.columns:
                        hdf[c] = None

                def cp(v):
                    try:
                        f = float(v)
                        return ("color:#10b981;font-weight:800" if f >= 0
                                else "color:#ef4444;font-weight:800")
                    except (ValueError, TypeError):
                        return ""

                st.dataframe(
                    hdf[cols].style.map(cp, subset=["Actual P&L ₹"]),
                    use_container_width=True,
                )
                pnl_s = hdf["Actual P&L ₹"].apply(pd.to_numeric, errors="coerce")
                ca, cb, cc2 = st.columns(3)
                ca.metric("Trades", len(hdf))
                cb.metric("Win/Loss", f"{(pnl_s>0).sum()}/{(pnl_s<=0).sum()}")
                cc2.metric("Net P&L", f"₹{pnl_s.sum():,.0f}",
                           delta=f"{pnl_s.sum():+.0f}")
            else:
                st.info("Waiting for first signal...")


def render_open_trades_tab(trade_mgr, fetcher):
    """Render the 'Open Trades' tab showing all open trades across all indices."""
    # Update prices for open trades
    for idx in INDEX_CONFIG:
        tlog = st.session_state.get(sk(idx, "trade_log"), [])
        has_open = any(t.get("Status") == "OPEN" for t in tlog)
        if not has_open:
            continue
        try:
            import os
            import json
            now = datetime.datetime.now(IST)
            now_time = now.time()
            in_window = MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME
            cache_file = os.path.join(BASE_DIR, f"last_data_{idx}.json")

            d = None
            if not in_window:
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r") as f:
                            d = json.load(f)
                    except Exception:
                        pass

            if d is None:
                d = fetcher.fetch_option_chain(idx)

            if not d or "records" not in d:
                continue

            events = trade_mgr.update_live_prices(idx, tlog, d["records"]["data"], now)
            if events:
                trade_mgr.save_log(idx, tlog)
                for ev in events:
                    if ev["type"] == "SL_HIT":
                        st.session_state[sk(idx, "last_sl_time")] = now
                    st.session_state[sk(idx, "last_signal")] = "WAIT"
                    
                    # Record exit in journal
                    journal = st.session_state.get("_journal")
                    if journal:
                        trade = ev["trade"]
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
        except Exception as e:
            logger.warning(f"Open trades update error for {idx}: {e}")

    all_open = []
    closed_today = []
    for idx in INDEX_CONFIG:
        tlog = st.session_state.get(sk(idx, "trade_log"), [])
        for t in tlog:
            if t.get("Status") == "OPEN":
                all_open.append(t)
            elif t.get("Status") == "CLOSED":
                closed_today.append(t)

    # ── Summary KPI calculations (Real data only) ──
    trades_count = len(all_open)
    realized_pnl = sum(float(t.get("Actual P&L ₹") or 0) for t in closed_today)
    unrealized_pnl = 0.0
    total_max_loss = 0.0
    for t in all_open:
        ev = float(t.get("Entry Price") or 0)
        lv = float(t.get("Live Price") or ev)
        qty = int(t.get("Qty") or 0)
        unrealized_pnl += (lv - ev) * qty
        try:
            total_max_loss += float(t.get("Max Loss ₹") or 0)
        except (ValueError, TypeError):
            pass

    today_pnl = (realized_pnl + unrealized_pnl) if (all_open or closed_today) else 0.0
    if total_max_loss == 0 and all_open:
        from config import MAX_LOSS
        total_max_loss = float(MAX_LOSS * len(all_open))

    wins = sum(1 for t in closed_today if float(t.get("Actual P&L ₹") or 0) > 0)
    win_rate = (wins / len(closed_today) * 100.0) if closed_today else None

    # ── 1. Summary Cards ──
    st.markdown(
        render_open_positions_summary(trades_count, today_pnl, total_max_loss, win_rate),
        unsafe_allow_html=True,
    )

    # ── 2. Open Positions Cards & Confirmation UX ──
    if not all_open:
        st.markdown(render_empty_open_trades(), unsafe_allow_html=True)
    else:
        for i_t, t in enumerate(all_open):
            norm = normalize_trade(t)
            idx = norm["instrument"]
            sig = norm["signal"]
            strk = norm["strike"]
            trade_id = f"{idx}_{norm['entry_time']}_{strk}_{sig}".replace(" ", "_")

            # Render normalized card
            st.markdown(render_trade_card_html(norm), unsafe_allow_html=True)

            # Confirmation UX for Close Position
            if st.session_state.get("_confirm_close") == trade_id:
                with st.container():
                    st.markdown(f"""
                    <div class="confirm-box">
                      <div style="font-family:'Space Grotesk',sans-serif;font-weight:700;color:#ffffff;font-size:14px;">
                        ⚠️ Close {idx} {strk} {norm['option_type']} at market price?
                      </div>
                      <div style="font-size:12px;color:var(--text-1);">
                        Current P&L: <b>{norm['pnl_disp']}</b> &nbsp;•&nbsp; 
                        Quantity: <b>{norm['quantity']}</b> &nbsp;•&nbsp; 
                        Live Price: <b>₹{norm['live_price']:.2f}</b>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)
                    c_cancel, c_confirm = st.columns([1, 1])
                    with c_cancel:
                        if st.button("✕ CANCEL", key=f"cancel_{trade_id}", use_container_width=True):
                            st.session_state["_confirm_close"] = None
                            st.rerun()
                    with c_confirm:
                        if st.button("✓ CONFIRM CLOSE", key=f"confirm_{trade_id}", type="primary", use_container_width=True):
                            st.session_state["_confirm_close"] = None
                            lp = float(t.get("Live Price") or t.get("Entry Price") or 0)
                            trade_mgr.close_manually(idx, t, lp)
                            tlog_key = sk(idx, "trade_log")
                            st.session_state[sk(idx, "signal_buffer")] = []
                            st.session_state[sk(idx, "last_signal")] = "WAIT"
                            trade_mgr.save_log(idx, st.session_state.get(tlog_key, []))

                            journal = st.session_state.get("_journal")
                            if journal:
                                journal.update_trade(
                                    t.get("_journal_id", ""),
                                    {
                                        "Exit Time": t.get("Exit Time"),
                                        "Exit Price": t.get("Exit Price"),
                                        "Actual P&L ₹": t.get("Actual P&L ₹"),
                                        "Status": "CLOSED",
                                        "Result": "🟡 MANUAL",
                                    },
                                    t
                                )
                            st.toast(f"Closed {idx} {strk} at ₹{lp:.2f}", icon="✅")
                            st.rerun()
            else:
                c_sp, c_close = st.columns([3, 2])
                with c_close:
                    if st.button("CLOSE POSITION", key=f"req_close_{trade_id}", type="primary", use_container_width=True):
                        st.session_state["_confirm_close"] = trade_id
                        st.rerun()

            st.markdown("<div style='margin-bottom: 16px;'></div>", unsafe_allow_html=True)


# ──────────────────────────────────────────────────
# TRADE HISTORY TAB
# ──────────────────────────────────────────────────
def render_trade_history_tab(journal):
    """
    Renders dedicated Trade History with interactive filters:
    Instrument, Outcome, and Search query.
    """
    st.markdown('<div class="label" style="font-size:12px !important;color:#ffffff !important;font-weight:700;margin-bottom:12px;">TRADE HISTORY</div>', unsafe_allow_html=True)

    all_trades = []
    # 1. Gather closed trades from session state logs
    for idx in INDEX_CONFIG:
        for t in st.session_state.get(sk(idx, "trade_log"), []):
            if t.get("Status") == "CLOSED":
                all_trades.append(t)

    # 2. Merge from persistent journal
    if journal:
        for jt in journal.get_all_trades():
            if jt.get("Status") == "CLOSED":
                key = (jt.get("Index"), jt.get("Entry Time"), str(jt.get("Strike")), jt.get("Signal"))
                exists = any(
                    (t.get("Index"), t.get("Entry Time"), str(t.get("Strike")), t.get("Signal")) == key
                    for t in all_trades
                )
                if not exists:
                    all_trades.append(jt)

    if not all_trades:
        st.markdown("""
        <div class="empty-state">
          <div class="icon">📜</div>
          <div class="msg">NO TRADE HISTORY</div>
          <div class="sub">Closed positions and historical execution logs will automatically display here.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Normalize trades
    normalized = [normalize_trade(t) for t in all_trades]

    # Filters row
    c_inst, c_res, c_search = st.columns([2, 2, 3])
    with c_inst:
        selected_inst = st.selectbox(
            "Instrument",
            options=["ALL"] + list(INDEX_CONFIG.keys()),
            key="hist_filter_inst",
        )
    with c_res:
        selected_res = st.selectbox(
            "Outcome",
            options=["ALL", "WINS ONLY", "LOSSES ONLY"],
            key="hist_filter_res",
        )
    with c_search:
        search_query = st.text_input(
            "Search (Strike / Signal)",
            placeholder="e.g. 23350, BUY CE...",
            key="hist_filter_search",
        )

    # Filter trades
    filtered = []
    for t in normalized:
        if selected_inst != "ALL" and t["instrument"] != selected_inst:
            continue
        if selected_res == "WINS ONLY" and t["pnl"] <= 0:
            continue
        if selected_res == "LOSSES ONLY" and t["pnl"] > 0:
            continue
        if search_query:
            q = search_query.strip().lower()
            match_txt = f"{t['instrument']} {t['signal']} {t['strike']} {t['raw'].get('Result', '')}".lower()
            if q not in match_txt:
                continue
        filtered.append(t)

    if not filtered:
        st.info("No trades match the selected filters.")
        return

    # Render tabular view
    rows = []
    for t in filtered:
        pnl = t["pnl"]
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_arrow = "▲" if pnl >= 0 else "▼"
        pnl_disp = f"{pnl_arrow} {pnl_sign}₹{pnl:,.0f}"

        exit_p = t["raw"].get("Exit Price")
        exit_disp = f"₹{float(exit_p):.2f}" if exit_p else "—"
        exit_time = t["raw"].get("Exit Time") or "—"
        res = t["raw"].get("Result") or "CLOSED"

        rows.append({
            "Time": t["entry_time"],
            "Exit Time": exit_time,
            "Instrument": t["instrument"],
            "Signal": t["signal"],
            "Strike": t["strike"],
            "Entry": f"₹{t['entry_price']:.2f}",
            "Exit": exit_disp,
            "Qty": t["quantity"],
            "P&L": pnl_disp,
            "Result": res,
        })

    df_hist = pd.DataFrame(rows)
    st.dataframe(
        df_hist,
        use_container_width=True,
        hide_index=True,
    )


# ──────────────────────────────────────────────────
# SETTINGS & CONTROLS TAB
# ──────────────────────────────────────────────────
def render_settings_tab(trade_mgr, journal):
    """
    Renders Settings & System Controls:
    - Manual Daily Report generation with Telegram feedback
    - Engine parameters HUD
    - Telegram connection status
    """
    import os
    from config import (
        CAPITAL, MAX_LOSS, DAILY_TGT,
        COOLDOWN_SECONDS, MARKET_OPEN_TIME, MARKET_CLOSE_TIME,
        AUTO_SQUARE_OFF_TIME, NO_NEW_TRADE_TIME, LOG_DIR,
        TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    )

    st.markdown('<div class="label" style="font-size:12px !important;color:#ffffff !important;font-weight:700;margin-bottom:12px;">SYSTEM SETTINGS & CONTROLS</div>', unsafe_allow_html=True)

    # 1. Telegram & Daily Report
    with st.container():
        st.markdown('<div class="card" style="padding:16px 18px;margin-bottom:16px;"><div class="label">TELEGRAM NOTIFICATIONS & DAILY REPORT</div>', unsafe_allow_html=True)
        col_tg, col_btn = st.columns([3, 2])
        with col_tg:
            has_token = bool(TELEGRAM_TOKEN or os.environ.get("TELEGRAM_TOKEN"))
            has_chat = bool(TELEGRAM_CHAT_ID or os.environ.get("TELEGRAM_CHAT_ID"))
            if has_token and has_chat:
                st.markdown('<span class="badge badge-ce">● TELEGRAM CONFIGURED</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="badge badge-warning">● TELEGRAM NOT CONFIGURED</span>', unsafe_allow_html=True)
            st.caption("Daily P&L summaries and automated trade alerts are dispatched to your configured Telegram channel.")
        with col_btn:
            if st.button("📨 SEND DAILY REPORT NOW", key="btn_send_report_settings", use_container_width=True):
                with st.spinner("Compiling and sending report..."):
                    current_date = datetime.datetime.now(IST).strftime("%Y-%m-%d")
                    total_pnl = 0
                    total_trades = 0
                    wins = 0
                    losses = 0
                    report_lines = [f"📊 *DAILY P&L REPORT — {current_date}*\n"]

                    for idx in INDEX_CONFIG:
                        tlog = st.session_state.get(sk(idx, "trade_log"), [])
                        if not tlog:
                            continue
                        df = pd.DataFrame(tlog)
                        closed = df[df["Status"] == "CLOSED"] if not df.empty else pd.DataFrame()
                        if closed.empty:
                            continue

                        pnl_s = closed["Actual P&L ₹"].apply(pd.to_numeric, errors="coerce")
                        idx_pnl = pnl_s.sum()
                        idx_trades = len(closed)
                        idx_wins = (pnl_s > 0).sum()
                        idx_losses = (pnl_s <= 0).sum()

                        total_pnl += idx_pnl
                        total_trades += idx_trades
                        wins += idx_wins
                        losses += idx_losses

                        emoji = "🟢" if idx_pnl >= 0 else "🔴"
                        report_lines.append(f"{emoji} *{idx}*: ₹{idx_pnl:,.0f} ({idx_wins}W/{idx_losses}L)")

                    report_lines.append(f"\n📈 *TOTAL TRADES*: {total_trades} ({wins}W / {losses}L)")
                    final_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    report_lines.append(f"{final_emoji} *NET P&L*: ₹{total_pnl:,.0f}")

                    if total_trades > 0:
                        trade_mgr.notifier.send_daily_report(report_lines)
                        lock_file = os.path.join(LOG_DIR, f"daily_report_{current_date}.lock")
                        os.makedirs(LOG_DIR, exist_ok=True)
                        try:
                            with open(lock_file, "w") as f:
                                f.write(f"sent_at: {datetime.datetime.now(IST).isoformat()} (manual)\n")
                        except Exception:
                            pass
                        st.success(f"Report sent to Telegram! Net P&L: ₹{total_pnl:,.0f}")
                    else:
                        st.warning("No closed trades recorded today yet.")
        st.markdown('</div>', unsafe_allow_html=True)

    # 2. Risk & Core Parameters HUD
    st.markdown(f"""
    <div class="card" style="padding:16px 18px;margin-bottom:16px;">
      <div class="label">CORE ENGINE RISK & EXECUTION PARAMETERS</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:10px;margin-top:10px;">
        <div class="card-inset"><div class="label">CAPITAL</div><div class="kpi num">₹{CAPITAL:,}</div></div>
        <div class="card-inset"><div class="label">DAILY TARGET</div><div class="kpi num c-ce">₹{DAILY_TGT:,}</div></div>
        <div class="card-inset"><div class="label">MAX DAILY LOSS</div><div class="kpi num c-pe">₹{MAX_LOSS:,}</div></div>
        <div class="card-inset"><div class="label">SL COOLDOWN</div><div class="kpi num">{COOLDOWN_SECONDS}s</div></div>
        <div class="card-inset"><div class="label">MARKET HOURS</div><div class="kpi-sm num" style="color:#ffffff;">{MARKET_OPEN_TIME} – {MARKET_CLOSE_TIME}</div></div>
        <div class="card-inset"><div class="label">AUTO SQUARE-OFF</div><div class="kpi-sm num c-amber">{AUTO_SQUARE_OFF_TIME}</div></div>
        <div class="card-inset"><div class="label">NO NEW TRADES</div><div class="kpi-sm num">{NO_NEW_TRADE_TIME}</div></div>
      </div>
    </div>
    """, unsafe_allow_html=True)
