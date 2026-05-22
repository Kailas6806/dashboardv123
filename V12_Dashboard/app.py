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

# ── CONFIGURATION ──
from config import (
    INDEX_CONFIG, IST, CAPITAL, DAILY_TGT,
    FRAGMENT_REFRESH_SECONDS, DAILY_REPORT_CHECK_SECS,
    DAILY_REPORT_TIME,
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
st.set_page_config(page_title="V12 PRO MAX", page_icon="🧠", layout="wide")
st.markdown(get_styles(), unsafe_allow_html=True)
st.title("🧠 V12 PRO MAX — TRADER DASHBOARD")

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

    if now.time() >= DAILY_REPORT_TIME:
        if st.session_state.get("daily_report_date") != current_date:
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
                report_lines.append(
                    f"{emoji} *{idx}*: ₹{idx_pnl:,.0f} ({idx_wins}W/{idx_losses}L)"
                )

            report_lines.append(f"\n📈 *TOTAL TRADES*: {total_trades} ({wins}W / {losses}L)")
            final_emoji = "🟢" if total_pnl >= 0 else "🔴"
            report_lines.append(f"{final_emoji} *NET P&L*: ₹{total_pnl:,.0f}")

            if total_trades > 0:
                notifier.send_daily_report(report_lines)
            st.session_state["daily_report_date"] = current_date
            logger.info(f"Daily report sent: {total_trades} trades, P&L: ₹{total_pnl:,.0f}")


@st.fragment(run_every=DAILY_REPORT_CHECK_SECS)
def check_daily_report():
    send_daily_pnl_report()


check_daily_report()
