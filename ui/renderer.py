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
    MARKET_OPEN_TIME, MARKET_CLOSE_TIME, AUTO_SQUARE_OFF_TIME,
    NO_NEW_TRADE_TIME, MIN_ENTRY_PRICE, is_expiry_day,
    MAX_LOSS, MAX_DAILY_LOSS, MAX_DAILY_LOSSES, MAX_DAILY_TRADES, COOLDOWN_SECONDS,
    BASE_DIR, LOG_DIR, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
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


def render_index(idx, fetcher, signal_engine, risk_mgr, trade_mgr, journal, copilot=None):
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
    in_window = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME)
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
    in_window = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME)

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

    # ── PORTFOLIO-WIDE TODAY TRADES ──
    portfolio_today_trades = []
    for _idx in INDEX_CONFIG:
        portfolio_today_trades.extend(st.session_state.get(sk(_idx, "trade_log"), []))
    valid_today_trades = [t for t in portfolio_today_trades if t.get("Entry Time")]
    trades_today_count = len(valid_today_trades)

    # ── RISK CHECKS ──
    cooldown_info = risk_mgr.should_allow_trade(
        idx, st.session_state[tlog_key], now_ist, portfolio_trades=portfolio_today_trades
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

    # ── AI SIGNAL VALIDATION SNIPPET ──
    if copilot and copilot.is_configured():
        ai_res = st.session_state.get(sk(idx, "ai_analysis"))
        with st.container():
            col_ai_btn, col_ai_txt = st.columns([2, 5])
            with col_ai_btn:
                if st.button(f"🧠 AI VALIDATE {idx}", key=f"btn_quick_ai_{idx}", use_container_width=True):
                    with st.spinner("NVIDIA Nemotron evaluating signal..."):
                        ai_res = copilot.analyze_market_and_signals(
                            idx, md, final_signal, conf_score,
                            active_trades_count=len([t for t in st.session_state[tlog_key] if t.get("Status") == "OPEN"])
                        )
                        st.session_state[sk(idx, "ai_analysis")] = ai_res
                        st.rerun()
            with col_ai_txt:
                if ai_res:
                    rec = ai_res.get("recommendation", "AVOID_WAIT").replace("_", " ")
                    conv = ai_res.get("conviction_score", 0)
                    summary = ai_res.get("reasoning_summary", "")
                    st.caption(f"🤖 **AI Verdict:** `{rec}` (Conviction: **{conv}/100**) — {summary[:120]}...")
                else:
                    st.caption("🤖 NVIDIA Nemotron 550B ready to validate option chain signals.")

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

    daily_limits = risk_mgr.check_daily_limits(portfolio_today_trades)
    consec_losses = 0
    closed_trades = [t for t in portfolio_today_trades if t.get("Status") == "CLOSED"]
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
        max_daily_losses=MAX_DAILY_LOSSES,
        trades_today=trades_today_count,
        max_trades_today=MAX_DAILY_TRADES,
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
        # 4. Strict daily trade limit: max 3 trades per day across portfolio
        daily_trades_exceeded = trades_today_count >= MAX_DAILY_TRADES

        if daily_trades_exceeded:
            st.warning(f"🛑 Daily limit reached ({trades_today_count}/{MAX_DAILY_TRADES} trades taken today across portfolio) — trading paused")
        elif not daily_allowed:
            st.warning(f"🛑 {daily_limits[1]}")
        elif too_late:
            st.warning(f"⏰ No new entries after {NO_NEW_TRADE_TIME.strftime('%I:%M %p')} — auto-square soon")
        elif price_too_low:
            st.warning(f"⚠️ Option price ₹{ep} is too low (min ₹{MIN_ENTRY_PRICE}) — skipping")
        elif oi_unusual:
            st.warning("🚨 Unusual OI activity detected — holding off entry")
        elif conf_score < 30:
            st.warning(f"⚠️ Confidence score ({conf_score}) is too low to enter trade (Minimum: 30)")
        elif expiry_today and ep < MIN_ENTRY_PRICE:
            st.info(f"📅 Expiry day — cheap option ₹{ep} allowed (fast moves expected)")

        can_enter = (
            not too_late
            and not price_too_low
            and not oi_unusual
            and conf_score >= 30
            and not daily_trades_exceeded
            and daily_allowed
        )

        if (final_signal != st.session_state[sk(idx, "last_signal")]
                and trade_allowed and daily_allowed and can_enter):

            # ── AI PRE-TRADE VALIDATION ──
            ai_auto_on = st.session_state.get("ai_auto_trade", AI_AUTO_TRADE_DEFAULT)
            ai_conviction_ok = True       # default: allow trade
            ai_pre_score = conf_score     # fallback to rule-engine score
            ai_pre_summary = "Rule engine signal"
            
            if copilot and copilot.is_configured():
                from config import AI_MIN_CONVICTION
                with st.spinner(f"🧠 AI analyzing {idx} {final_signal} signal..."):
                    ai_pre = copilot.analyze_market_and_signals(
                        idx, md, final_signal, conf_score,
                        active_trades_count=len([t for t in st.session_state[tlog_key] if t.get("Status") == "OPEN"])
                    )
                    st.session_state[sk(idx, "ai_analysis")] = ai_pre
                    ai_pre_score = ai_pre.get("conviction_score", 0)
                    ai_pre_rec   = ai_pre.get("recommendation", "AVOID_WAIT")
                    ai_pre_summary = ai_pre.get("reasoning_summary", "")
                    
                    if ai_auto_on:
                        # Block only if conviction is LOW or AI says avoid AND auto-trade is ON
                        if ai_pre_score < AI_MIN_CONVICTION or "BUY" not in ai_pre_rec:
                            ai_conviction_ok = False
                            st.warning(
                                f"🤖 AI blocked {idx} trade — conviction {ai_pre_score}/100 "
                                f"(need ≥{AI_MIN_CONVICTION}) | AI says: `{ai_pre_rec.replace('_',' ')}`"
                            )
                        else:
                            st.success(f"🤖 AI approved {idx} {final_signal} — conviction **{ai_pre_score}/100** ✅")
                    else:
                        # Auto-trade is OFF, just log the AI confidence but don't block
                        st.info(f"🤖 AI Analysis Complete — conviction **{ai_pre_score}/100**. (Auto-trade is OFF, proceeding via rules)")

            if not ai_conviction_ok:
                # AI blocked — don't enter, but mark signal as seen so it doesn't loop
                st.session_state[sk(idx, "last_signal")] = final_signal
            else:
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
                    "Confidence Score": ai_pre_score if ai_auto_on else conf_score,
                }
                st.session_state[tlog_key].insert(0, trade_entry)
                trade_mgr.save_log(idx, st.session_state[tlog_key])
                st.session_state[sk(idx, "last_signal")] = final_signal

                # Record in journal
                journal_id = journal.record_trade(trade_entry, {
                    "pcr": md["pcr"], "vwap": md["vwap_proxy"],
                    "oi_delta_ce": md["total_ce_delta"],
                    "oi_delta_pe": md["total_pe_delta"],
                    "confidence_score": ai_pre_score if ai_auto_on else conf_score,
                    "pcr_momentum": md["pcr_momentum"],
                    "trap": trap, "buffer_state": updated_buf[-3:],
                    "ai_validated": ai_auto_on,
                    "ai_reasoning": ai_pre_summary if ai_auto_on else "",
                })
                trade_entry["_journal_id"] = journal_id

                # Telegram alert
                signal_label = f"🤖 [AI✅] {final_signal}" if ai_auto_on else final_signal
                trade_mgr.notifier.send_signal_alert(
                    idx=idx, signal=signal_label,
                    strike=md["atm_actual"], spot=round(spot, 2),
                    entry=ep, sl=sl_p, tgt=tgt_p,
                    qty=qty, ml=ml, tp=tp,
                    conf=final_conf, score=ai_pre_score if ai_auto_on else conf_score,
                    time_str=now_str,
                )
                logger.info(
                    f"[{idx}] TRADE ENTERED: {final_signal} | Strike: {md['atm_actual']} | "
                    f"Entry: {ep} | SL: {sl_p} | Tgt: {tgt_p} | Conf: {final_conf} | "
                    f"AI-validated: {ai_auto_on} | AI-score: {ai_pre_score}"
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
            from analytics.db import TradeDB
            _idx_db = TradeDB()
            display_trades = _idx_db.get_all_trades(instrument=idx)
            if not display_trades:
                display_trades = list(st.session_state.get(tlog_key, []))
            if not display_trades and journal:
                display_trades = [t for t in journal.get_all_trades() if t.get("Index") == idx]
            if display_trades:
                cols = [
                    "Entry Time", "Exit Time", "Signal", "Strike",
                    "Entry Price", "Exit Price", "Qty",
                    "Actual P&L ₹", "Status", "Result",
                ]
                hdf = pd.DataFrame(display_trades)
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
            in_window = (now.weekday() < 5) and (MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME)
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
    Timeframe, Instrument, Outcome, and Search query, plus Backup/Restore controls.
    Backed by SQLite database (trades.db) for permanent persistence.
    """
    st.markdown('<div class="label" style="font-size:12px !important;color:#ffffff !important;font-weight:700;margin-bottom:12px;">TRADE HISTORY (SQLITE & JOURNAL)</div>', unsafe_allow_html=True)

    from analytics.db import TradeDB
    db = TradeDB()

    # 1. Action Bar: Sync & Status
    col_sync, col_status = st.columns([2, 5])
    with col_sync:
        if st.button("🔄 SYNC ALL TRADES TO SQLITE", key="btn_sync_db", use_container_width=True):
            imported = db.sync_from_json_and_csv()
            st.success(f"Synced {imported} trades into SQLite database!")
            st.rerun()
    with col_status:
        st.caption("All trades are permanently stored in SQLite database (`trades.db`) and mirrored to JSON/CSV.")

    # 2. Gather trades: Query SQLite directly
    all_trades = db.get_all_trades()
    if not all_trades and journal:
        all_trades = journal.get_all_trades()

    # Merge active session trades if not yet committed
    for idx in INDEX_CONFIG:
        for t in st.session_state.get(sk(idx, "trade_log"), []):
            t_id = t.get("trade_id") or t.get("_journal_id")
            if t_id and any(at.get("trade_id") == t_id for at in all_trades):
                continue
            t_strike = str(int(float(t.get("Strike", 0)))) if t.get("Strike") else "0"
            t_etime = str(t.get("Entry Time") or "")
            t_idx = str(t.get("Index") or "").upper()
            exists = any(
                (str(at.get("Index") or "").upper() == t_idx
                 and str(at.get("Entry Time") or "") == t_etime
                 and (str(int(float(at.get("Strike", 0)))) if at.get("Strike") else "0") == t_strike)
                for at in all_trades
            )
            if not exists:
                all_trades.append(t)
                db.upsert_trade(t)

    # ── Manual Record Trade Expander ──
    with st.expander("➕ Manually Record Past Trade (e.g. from Zerodha / AngelOne / Groww)", expanded=False):
        with st.form("form_manual_trade"):
            f_col1, f_col2, f_col3, f_col4 = st.columns(4)
            with f_col1:
                m_date = st.date_input("Trade Date", value=datetime.date.today(), key="m_trade_date")
                m_idx = st.selectbox("Instrument", list(INDEX_CONFIG.keys()), key="m_trade_idx")
            with f_col2:
                m_sig = st.selectbox("Signal", ["BUY CE", "BUY PE"], key="m_trade_sig")
                m_strike = st.number_input("Strike", value=24500, step=50, key="m_trade_strike")
            with f_col3:
                m_ep = st.number_input("Entry Price (₹)", value=100.0, step=1.0, key="m_trade_ep")
                m_xp = st.number_input("Exit Price (₹)", value=120.0, step=1.0, key="m_trade_xp")
            with f_col4:
                m_qty = st.number_input("Quantity", value=INDEX_CONFIG.get("NIFTY", {}).get("lot", 65), step=1, key="m_trade_qty")
                m_submit = st.form_submit_button("💾 Save Trade to History", use_container_width=True)

            if m_submit:
                m_pnl = round((m_xp - m_ep) * m_qty, 2)
                m_res = "🟢 WIN" if m_pnl > 0 else ("🔴 LOSS" if m_pnl < 0 else "🟡 BREAKEVEN")
                now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
                manual_entry = {
                    "trade_id": f"{m_idx}_{m_date.strftime('%Y%m%d')}_{datetime.datetime.now(IST).strftime('%H%M%S')}",
                    "date": m_date.strftime("%Y-%m-%d"),
                    "Entry Time": now_str,
                    "Exit Time": now_str,
                    "Index": m_idx,
                    "Signal": m_sig,
                    "Strike": m_strike,
                    "Entry Price": m_ep,
                    "Exit Price": m_xp,
                    "Live Price": m_xp,
                    "Qty": m_qty,
                    "Actual P&L ₹": m_pnl,
                    "Status": "CLOSED",
                    "Result": m_res,
                    "Confidence Score": 100,
                    "_ai_reasoning": "Manual User Entry",
                }
                db.upsert_trade(manual_entry)
                if journal:
                    journal.record_trade(manual_entry)
                st.success(f"Recorded {m_idx} {m_sig} {m_strike} (P&L: ₹{m_pnl:+,.0f}) to SQLite database!")
                st.rerun()

    # ── Persistence & Backup Toolbar ──
    with st.expander("💾 Backup & Restore Trade History", expanded=False):
        b_c1, b_c2, b_c3 = st.columns([1.5, 1.5, 3])
        with b_c1:
            if journal:
                st.download_button(
                    "📥 Export JSON",
                    data=journal.export_to_json(),
                    file_name="trade_history_backup.json",
                    mime="application/json",
                    use_container_width=True,
                    key="hist_dl_json",
                    help="Download complete trade history as JSON"
                )
        with b_c2:
            if journal:
                st.download_button(
                    "📥 Export CSV",
                    data=journal.export_to_csv(),
                    file_name="trade_history_backup.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="hist_dl_csv",
                    help="Download complete trade history as CSV"
                )
        with b_c3:
            uploaded_file = st.file_uploader(
                "Restore Backup",
                type=["json"],
                key="hist_upload_journal",
                label_visibility="collapsed"
            )
            if uploaded_file is not None and journal:
                try:
                    content = uploaded_file.read().decode("utf-8")
                    imported_count = journal.import_from_json_string(content)
                    st.success(f"✅ Restored {imported_count} trades into journal!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to restore backup: {e}")

    if not all_trades:
        st.markdown("""
        <div class="empty-state">
          <div class="icon">📜</div>
          <div class="msg">NO TRADE HISTORY</div>
          <div class="sub">Closed positions and historical execution logs will automatically display here.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Normalize trades and extract dates
    normalized = []
    now_ist = datetime.datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")

    for t in all_trades:
        norm = normalize_trade(t)
        # Extract trade date
        rec_at = str(t.get("recorded_at") or "")
        t_date = rec_at[:10] if len(rec_at) >= 10 else ""
        if not t_date:
            tid = str(t.get("trade_id") or "")
            parts = tid.split("_")
            if len(parts) >= 2 and len(parts[1]) == 8 and parts[1].isdigit():
                t_date = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]}"
            else:
                t_date = today_str
        norm["date"] = t_date
        norm["recorded_at_str"] = rec_at
        normalized.append(norm)

    # Sort newest first
    normalized.sort(key=lambda x: str(x.get("recorded_at_str") or x.get("date") or ""), reverse=True)

    # Filters row
    c_time, c_inst, c_res, c_search = st.columns([2, 2, 2, 3])
    with c_time:
        selected_time = st.selectbox(
            "Timeframe",
            options=["ALL TIME", "TODAY", "LAST 7 DAYS", "LAST 30 DAYS"],
            key="hist_filter_time",
        )
    with c_inst:
        selected_inst = st.selectbox(
            "Instrument",
            options=["ALL"] + list(INDEX_CONFIG.keys()),
            key="hist_filter_inst",
        )
    with c_res:
        selected_res = st.selectbox(
            "Outcome",
            options=["ALL", "CLOSED ONLY", "WINS ONLY", "LOSSES ONLY", "OPEN ONLY"],
            key="hist_filter_res",
        )
    with c_search:
        search_query = st.text_input(
            "Search (Date / Strike / Signal)",
            placeholder="e.g. 2026-09-11, 23350, BUY CE...",
            key="hist_filter_search",
        )

    # Filter trades
    filtered = []
    seven_days_ago = (now_ist - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    thirty_days_ago = (now_ist - datetime.timedelta(days=30)).strftime("%Y-%m-%d")

    for t in normalized:
        t_date = t["date"]
        # Timeframe filter
        if selected_time == "TODAY" and t_date != today_str:
            continue
        elif selected_time == "LAST 7 DAYS" and t_date < seven_days_ago:
            continue
        elif selected_time == "LAST 30 DAYS" and t_date < thirty_days_ago:
            continue

        # Instrument filter
        if selected_inst != "ALL" and t["instrument"] != selected_inst:
            continue

        # Outcome filter
        status = t["status"]
        if selected_res == "CLOSED ONLY" and status != "CLOSED":
            continue
        elif selected_res == "OPEN ONLY" and status != "OPEN":
            continue
        elif selected_res == "WINS ONLY" and (status != "CLOSED" or t["pnl"] <= 0):
            continue
        elif selected_res == "LOSSES ONLY" and (status != "CLOSED" or t["pnl"] > 0):
            continue

        # Search filter
        if search_query:
            q = search_query.strip().lower()
            match_txt = f"{t_date} {t['instrument']} {t['signal']} {t['strike']} {t['raw'].get('Result', '')}".lower()
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
        if t["status"] == "OPEN":
            pnl_disp = f"⏳ ₹{pnl:,.0f}"
        else:
            pnl_disp = f"{pnl_arrow} {pnl_sign}₹{pnl:,.0f}"

        exit_p = t["raw"].get("Exit Price")
        exit_disp = f"₹{float(exit_p):.2f}" if exit_p else "—"
        exit_time = t["raw"].get("Exit Time") or "—"
        res = t["raw"].get("Result") or t["status"]

        score_val = t.get("conf_score")
        if score_val is not None and str(score_val).strip() != "":
            try:
                score_disp = f"{int(float(score_val))}/100"
            except (ValueError, TypeError):
                score_disp = str(score_val)
        else:
            score_disp = "—"

        rows.append({
            "Date": t["date"],
            "Time": t["entry_time"],
            "Exit Time": exit_time,
            "Instrument": t["instrument"],
            "Signal": t["signal"],
            "Score": score_disp,
            "Strike": t["strike"],
            "Entry": f"₹{t['entry_price']:.2f}",
            "Exit": exit_disp,
            "Qty": t["quantity"],
            "P&L": pnl_disp,
            "Result": res,
        })

    df_hist = pd.DataFrame(rows)

    # ── AUTO-SQUARE OFF + CLOSE ALL button ──
    open_rows = [t for t in filtered if t["status"] == "OPEN"]
    now_close_time = datetime.datetime.now(IST)
    past_square_off = now_close_time.time() >= AUTO_SQUARE_OFF_TIME

    if open_rows:
        ca_col, cb_col = st.columns([3, 2])
        with ca_col:
            if past_square_off:
                st.warning(
                    f"⏰ Market past {AUTO_SQUARE_OFF_TIME.strftime('%I:%M %p')} — "
                    f"{len(open_rows)} open position(s) should be squared off."
                )
            else:
                st.info(f"📂 {len(open_rows)} open position(s) in this view.")
        with cb_col:
            if st.button(
                "❌ CLOSE ALL OPEN TRADES",
                key="btn_close_all_open_hist",
                type="primary",
                use_container_width=True,
            ):
                exit_now = now_close_time.strftime("%I:%M:%S %p")
                closed_count = 0
                for t_row in open_rows:
                    raw_trade = t_row.get("raw", {})
                    idx_val = t_row["instrument"]
                    
                    # Compute exit metrics
                    lp = float(raw_trade.get("Live Price") or raw_trade.get("Entry Price") or 0)
                    ep = float(raw_trade.get("Entry Price") or 0)
                    qty = int(raw_trade.get("Qty") or 0)
                    pnl = round((lp - ep) * qty, 2)
                    result_val = "🟡 MANUAL" if not past_square_off else "🟠 AUTO-SQUARED"
                    
                    # Update raw dictionary
                    raw_trade["Status"] = "CLOSED"
                    raw_trade["Exit Time"] = exit_now
                    raw_trade["Exit Price"] = lp
                    raw_trade["Actual P&L ₹"] = pnl
                    raw_trade["Result"] = result_val
                    
                    # 1. Update Database & Journal
                    trade_id = raw_trade.get("trade_id") or raw_trade.get("_journal_id", "")
                    if journal:
                        journal.update_trade(
                            trade_id,
                            {
                                "Exit Time": exit_now,
                                "Exit Price": lp,
                                "Actual P&L ₹": pnl,
                                "Status": "CLOSED",
                                "Result": result_val,
                            },
                            raw_trade,
                        )
                    
                    # 2. Update Session State (if it exists there)
                    tlog_ss = st.session_state.get(sk(idx_val, "trade_log"), [])
                    changed_ss = False
                    for ss_t in tlog_ss:
                        if (ss_t.get("trade_id") and ss_t.get("trade_id") == trade_id) or \
                           (ss_t.get("Index") == idx_val and ss_t.get("Entry Time") == raw_trade.get("Entry Time")):
                            ss_t["Status"] = "CLOSED"
                            ss_t["Exit Time"] = exit_now
                            ss_t["Exit Price"] = lp
                            ss_t["Actual P&L ₹"] = pnl
                            ss_t["Result"] = result_val
                            changed_ss = True
                            break
                    
                    if changed_ss:
                        trade_mgr_ss = st.session_state.get("_trade_mgr")
                        if trade_mgr_ss:
                            trade_mgr_ss.save_log(idx_val, tlog_ss)
                        st.session_state[sk(idx_val, "last_signal")] = "WAIT"
                        st.session_state[sk(idx_val, "signal_buffer")] = []
                        
                    closed_count += 1
                    
                st.success(f"✅ Closed {closed_count} open position(s)!")
                st.rerun()

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
        CAPITAL, MAX_LOSS, MAX_DAILY_LOSS, DAILY_TGT,
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
        <div class="card-inset"><div class="label">MAX LOSS / INDEX</div><div class="kpi num c-pe">₹{MAX_LOSS:,}</div></div>
        <div class="card-inset"><div class="label">PORTFOLIO MAX LOSS</div><div class="kpi num c-pe">₹{MAX_DAILY_LOSS:,}</div></div>
        <div class="card-inset"><div class="label">SL COOLDOWN</div><div class="kpi num">{COOLDOWN_SECONDS}s</div></div>
        <div class="card-inset"><div class="label">MARKET HOURS</div><div class="kpi-sm num" style="color:#ffffff;">{MARKET_OPEN_TIME} – {MARKET_CLOSE_TIME}</div></div>
        <div class="card-inset"><div class="label">AUTO SQUARE-OFF</div><div class="kpi-sm num c-amber">{AUTO_SQUARE_OFF_TIME}</div></div>
        <div class="card-inset"><div class="label">NO NEW TRADES</div><div class="kpi-sm num">{NO_NEW_TRADE_TIME}</div></div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_ai_copilot_tab(copilot, fetcher, signal_engine, risk_mgr, trade_mgr, journal):
    """
    Renders the AI Copilot tab:
    - Market reasoning and signal confirmation using NVIDIA Nemotron 550B
    - Direct 1-Click AI Trade Execution
    - Auto-Trade Mode toggle
    - Live options telemetry & AI thinking inspector
    """
    import os
    import json
    from config import INDEX_CONFIG, AI_AUTO_TRADE_DEFAULT, NVIDIA_MODEL

    st.markdown('<div class="label" style="font-size:12px !important;color:#ffffff !important;font-weight:700;margin-bottom:12px;">⚡ NVIDIA NEMOTRON AI COPILOT & TRADE EXECUTION</div>', unsafe_allow_html=True)

    if not copilot or not copilot.is_configured():
        st.error("NVIDIA API Key not configured. Please add NVIDIA_API_KEY in config.py or environment variables.")
        return

    # Top Controls Bar: Index Selector & Auto-Trade Toggle
    col_idx, col_toggle, col_model = st.columns([2, 3, 3])
    with col_idx:
        selected_idx = st.selectbox("Select Index", list(INDEX_CONFIG.keys()), key="ai_copilot_idx")
    with col_toggle:
        if "ai_auto_trade" not in st.session_state:
            st.session_state["ai_auto_trade"] = AI_AUTO_TRADE_DEFAULT
        if "toggle_ai_autotrade" not in st.session_state:
            st.session_state["toggle_ai_autotrade"] = st.session_state["ai_auto_trade"]
        auto_trade = st.toggle("⚡ Auto-Trade on High Conviction (>=75%)", key="toggle_ai_autotrade")
        st.session_state["ai_auto_trade"] = auto_trade
    with col_model:
        st.markdown(f'<div style="padding-top:10px;"><span class="badge badge-ce">● NEMOTRON 550B ACTIVE</span> <span style="font-size:11px;color:#94a3b8;margin-left:8px;">{NVIDIA_MODEL}</span></div>', unsafe_allow_html=True)

    # Fetch fresh or cached data for selected index
    cache_file = os.path.join(BASE_DIR, f"last_data_{selected_idx}.json")
    d = None
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                d = json.load(f)
        except Exception:
            pass
    if d is None:
        with st.spinner(f"Fetching market data for {selected_idx}..."):
            d = fetcher.fetch_option_chain(selected_idx)

    if not d or "records" not in d or not d["records"].get("data"):
        st.warning(f"Could not load option chain data for {selected_idx}. Market may be closed or offline.")
        return

    records = d["records"]["data"]
    spot = d["records"].get("underlyingValue") or 0.0
    cfg = INDEX_CONFIG[selected_idx]
    step, rng = cfg["step"], cfg["rng"]
    atm = round(spot / step) * step if step else 0

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

    prev_df = st.session_state.get(sk(selected_idx, "prev_df"))
    oi_baseline = st.session_state.get(sk(selected_idx, "oi_baseline"))
    pcr_hist = st.session_state.get(sk(selected_idx, "pcr_history"), [])
    spot_hist = st.session_state.get(sk(selected_idx, "spot_history"), [])

    md = signal_engine.compute_market_data(
        df, spot, step, selected_idx, spot_hist, pcr_hist, prev_df, oi_baseline
    )

    now_ist = datetime.datetime.now(IST)
    in_window = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_ist.time() <= MARKET_CLOSE_TIME)
    signal, conf, filter_reason = signal_engine.generate_signal(md, in_window)
    final_signal, final_conf, updated_buf = signal_engine.confirm_signal(
        signal, conf, st.session_state.get(sk(selected_idx, "signal_buffer"), [])
    )
    trap = signal_engine.detect_trap(
        spot, md.get("support", 0), md.get("resistance", 0),
        md.get("total_ce_delta", 0), md.get("total_pe_delta", 0)
    )
    conf_score = signal_engine.compute_confidence_score(md, final_signal, trap)

    # 1. Telemetry Strip
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Spot", f"₹{spot:,.1f}")
    col2.metric("ATM Strike", str(md["atm_actual"]))
    col3.metric("PCR", f"{md['pcr']:.2f}", delta=md["pcr_momentum"])
    col4.metric("VWAP Proxy", f"₹{md['vwap_proxy']:,.1f}", delta=md["spot_vs_vwap"])
    col5.metric("CE Δ vs PE Δ", f"{md['total_ce_delta']:,} / {md['total_pe_delta']:,}")
    col6.metric("Rule Signal", final_signal, delta=f"{conf_score}/100")

    st.markdown("<hr style='margin:12px 0;border-color:rgba(255,255,255,0.08);'>", unsafe_allow_html=True)

    # 2. Trigger AI Analysis
    col_act, col_info = st.columns([2, 5])
    with col_act:
        run_ai = st.button("🧠 RUN AI SIGNAL ANALYSIS", key=f"btn_run_ai_{selected_idx}", use_container_width=True)
    with col_info:
        active_analysis = st.session_state.get(sk(selected_idx, "ai_analysis"))
        if active_analysis and "timestamp" in active_analysis:
            st.caption(f"Last AI analysis generated at: {active_analysis['timestamp']}")
        else:
            st.caption("Click to trigger Nemotron 550B reasoning on live option chain structure.")

    tlog_key = sk(selected_idx, "trade_log")
    if tlog_key not in st.session_state:
        st.session_state[tlog_key] = []
    tlog = st.session_state[tlog_key]
    open_trades_count = len([t for t in tlog if t.get("Status") == "OPEN"])

    if run_ai:
        with st.spinner(f"NVIDIA Nemotron 550B is analyzing {selected_idx} market mechanics..."):
            analysis = copilot.analyze_market_and_signals(
                selected_idx, md, final_signal, conf_score, active_trades_count=open_trades_count
            )
            st.session_state[sk(selected_idx, "ai_analysis")] = analysis

            # ── AUTO-TRADE: fire immediately if toggle is ON and conviction is high ──
            if auto_trade:
                auto_rec = analysis.get("recommendation", "AVOID_WAIT")
                auto_conv = analysis.get("conviction_score", 0)
                from config import AI_MIN_CONVICTION
                if auto_conv >= AI_MIN_CONVICTION and "BUY" in auto_rec:
                    exec_sig = "BUY CE" if "CE" in auto_rec else "BUY PE"
                    # Block if there is already an open trade on this index
                    already_open = any(
                        t.get("Status") == "OPEN"
                        for t in st.session_state.get(sk(selected_idx, "trade_log"), [])
                    )
                    if already_open:
                        st.session_state[sk(selected_idx, "ai_auto_trade_msg")] = (
                            "warn",
                            f"Auto-Trade skipped — {selected_idx} already has an open position.",
                        )
                    else:
                        ok, _, msg = copilot.take_trade(
                            selected_idx, exec_sig, md, trade_mgr, risk_mgr, journal,
                            st.session_state.get(sk(selected_idx, "trade_log"), []),
                            ai_conviction=auto_conv,
                            ai_reasoning=analysis.get("reasoning_summary", "Auto-Trade: High Conviction"),
                        )
                        st.session_state[sk(selected_idx, "ai_auto_trade_msg")] = (
                            "ok" if ok else "err", msg
                        )
                else:
                    st.session_state[sk(selected_idx, "ai_auto_trade_msg")] = (
                        "info",
                        f"Auto-Trade: conviction {auto_conv}/100 below threshold ({AI_MIN_CONVICTION}) or signal is AVOID — no trade fired.",
                    )

            st.rerun()

    analysis = st.session_state.get(sk(selected_idx, "ai_analysis"))
    if not analysis:
        st.info("No analysis generated yet for this session. Click 'RUN AI SIGNAL ANALYSIS' above to begin.")
        return

    # Show auto-trade result banner (if any)
    at_msg = st.session_state.pop(sk(selected_idx, "ai_auto_trade_msg"), None)
    if at_msg:
        status, text = at_msg
        if status == "ok":
            st.success(f"🤖 **AUTO-TRADE FIRED:** {text}")
        elif status == "err":
            st.error(f"🤖 Auto-Trade failed: {text}")
        elif status == "warn":
            st.warning(f"⚡ {text}")
        else:
            st.info(f"⚡ {text}")

    # 3. Render AI Verdict Card
    bias = analysis.get("market_bias", "UNKNOWN")
    rec = analysis.get("recommendation", "AVOID_WAIT")
    conviction = analysis.get("conviction_score", 0)
    summary = analysis.get("reasoning_summary", "")
    key_factors = analysis.get("key_factors", [])
    risk_warn = analysis.get("risk_warning", "")
    thinking = analysis.get("reasoning_content", "")

    bias_color = "#10b981" if "BULL" in bias else ("#ef4444" if "BEAR" in bias else "#f59e0b")
    rec_color = "#10b981" if "BUY_CE" in rec else ("#ef4444" if "BUY_PE" in rec else "#64748b")

    st.markdown(f"""
    <div class="card" style="padding:18px;margin-top:10px;border-left:4px solid {rec_color};">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
        <div>
          <span style="font-size:11px;color:#94a3b8;letter-spacing:0.05em;text-transform:uppercase;">AI Conviction Verdict</span>
          <div style="font-size:20px;font-weight:800;color:{rec_color};margin-top:2px;">{rec.replace('_', ' ')}</div>
        </div>
        <div style="text-align:right;">
          <span style="font-size:11px;color:#94a3b8;">MARKET BIAS</span>
          <div style="font-size:16px;font-weight:700;color:{bias_color};">{bias}</div>
        </div>
        <div style="text-align:right;">
          <span style="font-size:11px;color:#94a3b8;">CONVICTION SCORE</span>
          <div style="font-size:20px;font-weight:800;color:#38bdf8;">{conviction}/100</div>
        </div>
      </div>
      <div style="margin-top:14px;font-size:14px;line-height:1.5;color:#e2e8f0;background:rgba(255,255,255,0.03);padding:12px 14px;border-radius:6px;">
        <b>Executive Summary:</b> {summary}
      </div>
    </div>
    """, unsafe_allow_html=True)

    col_factors, col_action = st.columns([3, 2])
    with col_factors:
        st.markdown("<div class='card' style='padding:16px;margin-top:12px;'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>KEY DRIVING FACTORS</div>", unsafe_allow_html=True)
        if key_factors:
            for kf in key_factors:
                st.markdown(f"<div style='font-size:13px;color:#cbd5e1;margin-bottom:6px;'>• {kf}</div>", unsafe_allow_html=True)
        if risk_warn:
            st.markdown(f"<div style='font-size:12px;color:#f87171;margin-top:10px;'>⚠️ <b>Risk:</b> {risk_warn}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if thinking:
            with st.expander("🔍 Inspect Deep Reasoning (Nemotron Thinking Trace)"):
                st.markdown(f"<div style='font-size:12px;font-family:monospace;white-space:pre-wrap;color:#94a3b8;'>{thinking}</div>", unsafe_allow_html=True)

    with col_action:
        # 4. Interactive Trade Execution
        st.markdown("<div class='card' style='padding:16px;margin-top:12px;'>", unsafe_allow_html=True)
        st.markdown("<div class='label'>AI TRADE EXECUTION</div>", unsafe_allow_html=True)

        atm_row = md.get("atm_row", {})
        ce_price = float(atm_row.get("CE LTP", 0)) if hasattr(atm_row, "get") else 0.0
        pe_price = float(atm_row.get("PE LTP", 0)) if hasattr(atm_row, "get") else 0.0
        lot = cfg["lot"]

        if "BUY_CE" in rec:
            exec_signal = "BUY CE"
            ep = ce_price
        elif "BUY_PE" in rec:
            exec_signal = "BUY PE"
            ep = pe_price
        else:
            exec_signal = "BUY CE" if final_signal == "BUY CE" else ("BUY PE" if final_signal == "BUY PE" else None)
            ep = ce_price if exec_signal == "BUY CE" else pe_price

        if exec_signal and ep > 0:
            qty, sl_p, tgt_p, ml, tp = risk_mgr.calc_trade_with_atr(ep, lot, md["spot_history"])
            st.markdown(f"""
            <div style="font-size:13px;color:#cbd5e1;line-height:1.7;">
              <b>Signal:</b> <span class="{'c-ce' if 'CE' in exec_signal else 'c-pe'}">{exec_signal}</span><br>
              <b>Strike:</b> {md['atm_actual']} | <b>Premium:</b> ₹{ep:.2f}<br>
              <b>SL:</b> ₹{sl_p:.2f} | <b>Target:</b> ₹{tgt_p:.2f}<br>
              <b>Qty:</b> {qty} | <b>Max Loss:</b> ₹{ml:,} | <b>Target P&L:</b> ₹{tp:,}
            </div>
            """, unsafe_allow_html=True)

            btn_label = f"⚡ TAKE AI TRADE ({exec_signal})"
            if st.button(btn_label, key=f"btn_take_trade_{selected_idx}", use_container_width=True):
                ok, trade_entry, msg = copilot.take_trade(
                    selected_idx, exec_signal, md, trade_mgr, risk_mgr, journal, tlog,
                    ai_conviction=conviction, ai_reasoning=summary, force=True
                )
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.info("AI recommends holding or waiting. No trade suggested right now.")
            # Manual trade override buttons
            c_ce, c_pe = st.columns(2)
            with c_ce:
                if st.button("BUY ATM CE", key=f"btn_force_ce_{selected_idx}", use_container_width=True):
                    ok, trade_entry, msg = copilot.take_trade(
                        selected_idx, "BUY CE", md, trade_mgr, risk_mgr, journal, tlog,
                        ai_conviction=conviction, ai_reasoning="Manual 1-Click Execution", force=True
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            with c_pe:
                if st.button("BUY ATM PE", key=f"btn_force_pe_{selected_idx}", use_container_width=True):
                    ok, trade_entry, msg = copilot.take_trade(
                        selected_idx, "BUY PE", md, trade_mgr, risk_mgr, journal, tlog,
                        ai_conviction=conviction, ai_reasoning="Manual 1-Click Execution", force=True
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        st.markdown("</div>", unsafe_allow_html=True)

