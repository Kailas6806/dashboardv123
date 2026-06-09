"""
V12 PRO MAX — TRADER DASHBOARD
================================
Slim orchestrator. All logic lives in modular packages:
  - config.py         → all tunable parameters
  - core/             → signal engine, risk manager, data fetcher, trade manager
  - analytics/        → trade journal, analytics dashboard
  - notifications/    → async Telegram alerts
  - ui/               → styles, components, renderer
  - utils/            → cache, logger
"""
import streamlit as st
import pandas as pd
import datetime
import os

# ── CONFIGURATION ──
from config import (
    INDEX_CONFIG, IST, CAPITAL, DAILY_TGT,
    FRAGMENT_REFRESH_SECONDS, DAILY_REPORT_CHECK_SECS,
    DAILY_REPORT_TIME, LOG_DIR,
)

# ── MODULES ──
from ui.styles import get_styles
from ui.renderer import (
    render_index, render_open_trades_tab,
    init_state, load_log, sk,
)
from core.signal_engine import SignalEngine
from core.risk_manager import RiskManager
from core.data_fetcher import get_fetcher
from core.trade_manager import TradeManager
from analytics.trade_journal import TradeJournal
from analytics.dashboard import render_analytics_tab
from notifications.telegram import TelegramNotifier
from utils.logger import setup_logger

# ── STREAMLIT CONFIG ──
st.set_page_config(page_title="V12 PRO MAX", page_icon="⚡", layout="wide")
st.markdown(get_styles(), unsafe_allow_html=True)
st.markdown("""
<div style="padding: 10px 0 20px 0;">
    <h1 style="font-size: 38px; font-weight: 800; background: linear-gradient(135deg, #818cf8, #c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; letter-spacing: -0.02em;">V12 PRO MAX</h1>
    <p style="color: #a1a1aa; font-size: 13px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; margin-top: 4px;">Algorithmic Trading Engine</p>
</div>
""", unsafe_allow_html=True)

# ── INITIALIZE LOGGER ──
logger = setup_logger()
logger.info("Dashboard loaded")

# ── INITIALIZE SINGLETONS (via session state) ──
if "_signal_engine" not in st.session_state:
    st.session_state["_signal_engine"] = SignalEngine()
if "_risk_mgr" not in st.session_state:
    st.session_state["_risk_mgr"] = RiskManager()
if "_notifier" not in st.session_state:
    st.session_state["_notifier"] = TelegramNotifier()
if "_trade_mgr" not in st.session_state:
    st.session_state["_trade_mgr"] = TradeManager(
        notifier=st.session_state["_notifier"],
        risk_mgr=st.session_state["_risk_mgr"],
    )
if "_journal" not in st.session_state:
    st.session_state["_journal"] = TradeJournal()

signal_engine = st.session_state["_signal_engine"]
risk_mgr      = st.session_state["_risk_mgr"]
notifier      = st.session_state["_notifier"]
trade_mgr     = st.session_state["_trade_mgr"]
journal       = st.session_state["_journal"]
fetcher       = get_fetcher()

# ── INITIALIZE PER-INDEX STATE ──
for idx in INDEX_CONFIG:
    init_state(idx)
    if not st.session_state[sk(idx, "trade_log")]:
        st.session_state[sk(idx, "trade_log")] = load_log(idx)

# ── TABS ──
tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "🟢 Open Trades", "📈 NIFTY", "🏦 BANKNIFTY", "💹 FINNIFTY", "📊 Analytics"
])


# ── FRAGMENTS (silent background refresh every 3s) ──
@st.fragment(run_every=FRAGMENT_REFRESH_SECONDS)
def show_open_trades():
    render_open_trades_tab(trade_mgr, fetcher)


@st.fragment(run_every=FRAGMENT_REFRESH_SECONDS)
def show_nifty():
    render_index("NIFTY", fetcher, signal_engine, risk_mgr, trade_mgr, journal)


@st.fragment(run_every=FRAGMENT_REFRESH_SECONDS)
def show_banknifty():
    render_index("BANKNIFTY", fetcher, signal_engine, risk_mgr, trade_mgr, journal)


@st.fragment(run_every=FRAGMENT_REFRESH_SECONDS)
def show_finnifty():
    render_index("FINNIFTY", fetcher, signal_engine, risk_mgr, trade_mgr, journal)


def show_analytics():
    render_analytics_tab(journal)


with tab0:
    show_open_trades()
with tab1:
    show_nifty()
with tab2:
    show_banknifty()
with tab3:
    show_finnifty()
with tab4:
    show_analytics()


# ── DAILY P&L REPORT ──
def send_daily_pnl_report():
    """Send daily P&L summary via Telegram at DAILY_REPORT_TIME."""
    now = datetime.datetime.now(IST)
    current_date = now.strftime("%Y-%m-%d")

    # Fast path: check daily lock file first to avoid redundant checks & double sending
    lock_file = os.path.join(LOG_DIR, f"daily_report_{current_date}.lock")
    if os.path.exists(lock_file):
        st.session_state["daily_report_date"] = current_date
        return

    if now.time() >= DAILY_REPORT_TIME:
        if st.session_state.get("daily_report_date") != current_date:
            total_pnl = 0
            total_trades = 0
            wins = 0
            losses = 0
            report_lines = [f"📊 *DAILY P&L REPORT — {current_date}*\n"]

            # --- Primary: read from session state trade logs ---
            session_trades_found = False
            for idx in INDEX_CONFIG:
                tlog = st.session_state.get(sk(idx, "trade_log"), [])
                if not tlog:
                    continue

                df = pd.DataFrame(tlog)
                closed = df[df["Status"] == "CLOSED"] if not df.empty else pd.DataFrame()
                if closed.empty:
                    continue

                session_trades_found = True
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
                report_lines.append(
                    f"{emoji} *{idx}*: ₹{idx_pnl:,.0f} ({idx_wins}W/{idx_losses}L)"
                )

            # --- Fallback: read from trade journal if session state had no trades ---
            if not session_trades_found:
                day_trades = journal.get_trades_for_date(current_date)
                closed_j = [t for t in day_trades if t.get("Status") == "CLOSED"]
                if closed_j:
                    by_idx_j = {}
                    for t in closed_j:
                        t_idx = t.get("Index", "UNKNOWN")
                        pnl = float(t.get("Actual P&L ₹") or 0)
                        if t_idx not in by_idx_j:
                            by_idx_j[t_idx] = {"pnl": 0, "wins": 0, "losses": 0}
                        by_idx_j[t_idx]["pnl"] += pnl
                        if pnl > 0:
                            by_idx_j[t_idx]["wins"] += 1
                        else:
                            by_idx_j[t_idx]["losses"] += 1
                    for t_idx, v in by_idx_j.items():
                        emoji = "🟢" if v["pnl"] >= 0 else "🔴"
                        report_lines.append(
                            f"{emoji} *{t_idx}*: ₹{v['pnl']:,.0f} ({v['wins']}W/{v['losses']}L)"
                        )
                        total_pnl += v["pnl"]
                        total_trades += v["wins"] + v["losses"]
                        wins += v["wins"]
                        losses += v["losses"]

            report_lines.append(f"\n📈 *TOTAL TRADES*: {total_trades} ({wins}W / {losses}L)")
            final_emoji = "🟢" if total_pnl >= 0 else "🔴"
            report_lines.append(f"{final_emoji} *NET P&L*: ₹{total_pnl:,.0f}")

            # Always send — even if 0 trades (show empty day summary)
            notifier.send_daily_report(report_lines)
            os.makedirs(LOG_DIR, exist_ok=True)
            try:
                with open(lock_file, "w") as f:
                    f.write(f"sent_at: {now.isoformat()}\n")
                logger.info(f"Daily report sent and lock file created: {lock_file}")
            except Exception as e:
                logger.error(f"Failed to write daily report lock file: {e}")
            st.session_state["daily_report_date"] = current_date
            logger.info(f"Daily report sent: {total_trades} trades, P&L: ₹{total_pnl:,.0f}")



@st.fragment(run_every=DAILY_REPORT_CHECK_SECS)
def check_daily_report():
    send_daily_pnl_report()
    _send_weekly_report_if_friday()


def _send_weekly_report_if_friday():
    """Send a 7-day weekly P&L summary on Friday after market close."""
    now = datetime.datetime.now(IST)
    # Friday = weekday 4
    if now.weekday() != 4:
        return
    if now.time() < DAILY_REPORT_TIME:
        return

    week_str = now.strftime("%Y-W%W")
    lock_file = os.path.join(LOG_DIR, f"weekly_report_{week_str}.lock")
    if os.path.exists(lock_file):
        return

    # Build 7-day summary from journal
    analytics = journal.get_analytics(days=7)
    total_trades = analytics.get("total_trades", 0)
    wins        = analytics.get("wins", 0)
    losses      = analytics.get("losses", 0)
    win_rate    = analytics.get("win_rate", 0.0)
    total_pnl   = analytics.get("total_pnl", 0.0)
    max_dd      = analytics.get("max_drawdown", 0.0)
    rr          = analytics.get("risk_reward_ratio", 0.0)

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    lines = [
        f"📅 *WEEKLY REPORT — {now.strftime('%d %b %Y')}*\n",
        f"📊 Trades: {total_trades} ({wins}W / {losses}L)",
        f"🎯 Win Rate: {win_rate:.1f}%",
        f"{pnl_emoji} Net P&L: ₹{total_pnl:,.0f}",
        f"📉 Max Drawdown: ₹{max_dd:,.0f}",
        f"⚖️ Risk:Reward: {rr:.2f}",
    ]

    # Per-index breakdown
    by_index = analytics.get("by_index", {})
    if by_index:
        lines.append("\n*By Index:*")
        for t_idx, v in by_index.items():
            ie = "🟢" if v["pnl"] >= 0 else "🔴"
            lines.append(f"  {ie} {t_idx}: ₹{v['pnl']:,.0f} ({v['wins']}W/{v['losses']}L)")

    notifier.send_daily_report(lines)
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        with open(lock_file, "w") as f:
            f.write(f"sent_at: {now.isoformat()}\n")
        logger.info(f"Weekly report sent for {week_str}")
    except Exception as e:
        logger.error(f"Failed to write weekly report lock file: {e}")


check_daily_report()

# ── FORCED RELOAD TRIGGER ──
