import os
import sys
import datetime
import time
import importlib
import importlib.util
import pandas as pd
import streamlit as st

# ── ENSURE DIRECTORY ON PATH & CONFIG AVAILABLE ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_cfg_path = os.path.join(BASE_DIR, "config.py")
_cfg_example = os.path.join(BASE_DIR, "config.example.py")

# Ensure config.py exists from config.example.py if missing or incomplete
if os.path.exists(_cfg_example):
    need_copy = not os.path.exists(_cfg_path)
    if not need_copy:
        try:
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                if "INDEX_CONFIG" not in _f.read():
                    need_copy = True
        except Exception:
            need_copy = True
    if need_copy:
        try:
            import shutil
            shutil.copy(_cfg_example, _cfg_path)
        except Exception:
            pass

# ── CONFIGURATION MODULE LOADER ──
try:
    import config
    if not hasattr(config, "INDEX_CONFIG"):
        _target = _cfg_path if os.path.exists(_cfg_path) else _cfg_example
        _spec = importlib.util.spec_from_file_location("config", _target)
        if _spec and _spec.loader:
            config = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(config)
            sys.modules["config"] = config
except Exception:
    _spec = importlib.util.spec_from_file_location("config", _cfg_example)
    config = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(config)
    sys.modules["config"] = config

for _k, _default in [
    ("MAX_LOSS", 1500),
    ("MAX_INDEX_DAILY_LOSS", 4500),
    ("MAX_DAILY_LOSS", 9000),
    ("DAILY_TGT", 3000),
    ("PROFIT_LOCK_START", 1500),
    ("ENABLE_WEBSOCKET", True),
    ("ML_ENABLED", False),
    ("GEMINI_API_KEY", ""),
    ("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    ("NVIDIA_API_KEY", ""),
    ("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    ("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct"),
]:
    _val = getattr(config, _k, _default)
    # Upgrade any legacy defaults for index/portfolio to new 4500 / 9000 rules
    if _k == "MAX_LOSS" and _val == 2000:
        _val = 1500
    elif _k == "MAX_INDEX_DAILY_LOSS" and (_val == 1500 or _val == 2000):
        _val = 4500
    elif _k == "MAX_DAILY_LOSS" and (_val == 4500 or _val == 6000):
        _val = 9000
    elif _k == "DAILY_TGT" and _val == 4000:
        _val = 3000

    if hasattr(st, "secrets") and _k in st.secrets:
        _val = str(st.secrets[_k]).strip()
        if _k in ("MAX_LOSS", "MAX_INDEX_DAILY_LOSS", "MAX_DAILY_LOSS", "DAILY_TGT", "PROFIT_LOCK_START"):
            try:
                _val = int(_val)
            except Exception:
                pass
        elif _k == "ENABLE_WEBSOCKET":
            _val = _val.lower() in ("true", "1", "yes")
    setattr(config, _k, _val)

# Core constants exported for main.py
INDEX_CONFIG = getattr(config, "INDEX_CONFIG")
IST = getattr(config, "IST")
FRAGMENT_REFRESH_SECONDS = getattr(config, "FRAGMENT_REFRESH_SECONDS", 3)
LIVE_UI_REFRESH_SECONDS = getattr(config, "LIVE_UI_REFRESH_SECONDS", 1)
DAILY_REPORT_CHECK_SECS = getattr(config, "DAILY_REPORT_CHECK_SECS", 60)
DAILY_REPORT_TIME = getattr(config, "DAILY_REPORT_TIME", datetime.time(15, 35))
LOG_DIR = getattr(config, "LOG_DIR", os.path.join(BASE_DIR, "logs"))
MARKET_OPEN_TIME = getattr(config, "MARKET_OPEN_TIME", datetime.time(9, 15))
MARKET_CLOSE_TIME = getattr(config, "MARKET_CLOSE_TIME", datetime.time(15, 30))

# ── MODULES ──
from ui.styles import get_styles
from ui.renderer import (
    render_index, render_open_trades_tab,
    render_trade_history_tab, render_settings_tab,
    render_ai_copilot_tab,
    init_state, load_log, sk,
)
from ui.components import (
    render_app_header,
)
from core.signal_engine import SignalEngine
from core.risk_manager import RiskManager
from core.angelone_fetcher import get_fetcher
from core.trade_manager import TradeManager
from core.ai_copilot import AICopilot
from analytics.trade_journal import TradeJournal
from analytics.dashboard import render_analytics_tab
from notifications.telegram import TelegramNotifier
from utils.logger import setup_logger

# ── STREAMLIT CONFIG ──
st.set_page_config(page_title="V12 PRO MAX", page_icon="⚡", layout="wide")
st.markdown(get_styles(), unsafe_allow_html=True)

# ── INITIALIZE LOGGER ──
logger = setup_logger()
logger.info("Dashboard loaded")

# ── INITIALIZE SINGLETONS (via session state) ──
if "_signal_engine" not in st.session_state or not hasattr(st.session_state.get("_signal_engine"), "_has_15m_trend"):
    st.session_state["_signal_engine"] = SignalEngine()
if "_risk_mgr" not in st.session_state or not hasattr(st.session_state["_risk_mgr"], "calculate_portfolio_equity"):
    st.session_state["_risk_mgr"] = RiskManager()
if "_notifier" not in st.session_state:
    st.session_state["_notifier"] = TelegramNotifier()
if "_trade_mgr" not in st.session_state or not hasattr(st.session_state.get("_trade_mgr"), "_supports_fetcher"):
    st.session_state["_trade_mgr"] = TradeManager(
        notifier=st.session_state["_notifier"],
        risk_mgr=st.session_state["_risk_mgr"],
    )
else:
    st.session_state["_trade_mgr"]._risk_mgr = st.session_state["_risk_mgr"]
if "_journal" not in st.session_state or not hasattr(st.session_state.get("_journal"), "clear_all_trades"):
    st.session_state["_journal"] = TradeJournal()
if "_copilot" not in st.session_state:
    st.session_state["_copilot"] = AICopilot()
try:
    from analytics.db import TradeDB
    cached_trade_db = st.session_state.get("_trade_db")
    if (
        not isinstance(cached_trade_db, TradeDB)
        or not hasattr(cached_trade_db, "get_all_trades")
        or not hasattr(cached_trade_db, "get_or_init_capital")
    ):
        st.session_state["_trade_db"] = TradeDB()
except Exception as e:
    logger.warning(f"TradeDB initialization failed: {e}")
    st.session_state["_trade_db"] = None

signal_engine = st.session_state["_signal_engine"]
risk_mgr      = st.session_state["_risk_mgr"]
notifier      = st.session_state["_notifier"]
trade_mgr     = st.session_state["_trade_mgr"]
journal       = st.session_state["_journal"]
copilot       = st.session_state["_copilot"]
fetcher       = get_fetcher()

# ── 100% FOREGROUND MULTI-INDEX SCANNER & AUDITOR ──
from core.foreground_scanner import (
    start_foreground_scanner, get_scanner_status,
    get_latest_index_state, get_index_trade_log, set_index_trade_log,
)
from core.signal_audit import get_signal_auditor
auditor = get_signal_auditor()

# ── INITIALIZE PER-INDEX STATE (Loaded once into session state for instant sub-50ms tab switching) ──
for idx in INDEX_CONFIG:
    init_state(idx)
    if not st.session_state.get(f"_trades_loaded_{idx}"):
        initial_trades = []
        if hasattr(journal, "db") and journal.db:
            try:
                now_date = datetime.datetime.now(IST).strftime("%Y-%m-%d")
                try:
                    initial_trades = journal.db.get_all_trades(
                        instrument=idx,
                        trade_date=now_date,
                        include_open=True,
                    )
                except TypeError:
                    db_t = journal.db.get_all_trades(instrument=idx)
                    initial_trades = [
                        trade for trade in db_t
                        if str(trade.get("date") or "")[:10] == now_date
                        or str(trade.get("Status") or "").upper() == "OPEN"
                    ]
            except Exception:
                initial_trades = []
        if not initial_trades and not (hasattr(journal, "db") and journal.db):
            initial_trades = load_log(idx)
        st.session_state[sk(idx, "trade_log")] = initial_trades
        set_index_trade_log(idx, initial_trades)
        st.session_state[f"_trades_loaded_{idx}"] = True

start_foreground_scanner(fetcher, signal_engine, risk_mgr, trade_mgr, journal, copilot)

# Render the most recent scanner state immediately; scanning is scheduled below.
latest_scan_results = {
    idx: get_latest_index_state(idx)
    for idx in INDEX_CONFIG
}

# ── COMPUTE TICKER & MARKET STATUS ──
now_ist = datetime.datetime.now(IST)
market_open = (now_ist.weekday() < 5) and (MARKET_OPEN_TIME <= now_ist.time() <= MARKET_CLOSE_TIME)
datetime_str = now_ist.strftime("%d %b %Y · %I:%M %p").replace("AM", "am").replace("PM", "pm")

# Check and ensure WebSocket streaming during trading hours (if ENABLE_WEBSOCKET is True)
ws_connected = fetcher.is_websocket_connected() if (fetcher and hasattr(fetcher, "is_websocket_connected")) else False

ticker_items = []
import json
for idx in INDEX_CONFIG:
    spot = None
    # 1. Check latest foreground evaluated spot
    latest_st = latest_scan_results.get(idx) or st.session_state.get(sk(idx, "latest_state"))
    if latest_st and latest_st.get("spot"):
        spot = latest_st["spot"]
    # 2. Check live sub-50ms WebSocket spot tick (if active)
    if spot is None and fetcher and hasattr(fetcher, "ws_mgr") and fetcher.ws_mgr:
        tok = fetcher.index_tokens.get(idx, {}).get("token")
        if tok:
            ws_spot = fetcher.ws_mgr.get_live_ltp(str(tok))
            if ws_spot and ws_spot > 0:
                spot = ws_spot
    if spot is None:
        hist = st.session_state.get(sk(idx, "spot_history"), [])
        if hist:
            spot = hist[-1]
    if spot is None:
        cache_file = os.path.join(BASE_DIR, f"last_data_{idx}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cache_d = json.load(f)
                spot = cache_d.get("records", {}).get("underlyingValue")
            except Exception:
                pass
    ticker_items.append({"symbol": idx, "spot": spot})

is_connected = any(it.get("spot") is not None for it in ticker_items)

# ── RENDER HEADER & TICKER ──
scanner_enabled = bool(getattr(config, "ENABLE_BACKGROUND_SCANNER", True))
scanner_status = get_scanner_status()
st.markdown(
    render_app_header(
        market_open,
        is_connected,
        datetime_str,
        ws_connected=ws_connected,
        scanner_active=scanner_enabled,
        ticker_items=ticker_items,
        scanner_status=scanner_status,
    ),
    unsafe_allow_html=True,
)

# ── DYNAMIC NAVIGATION (FAST LAZY-LOADED TABS) ──
open_count = sum(
    len([t for t in get_index_trade_log(idx) if t.get("Status") == "OPEN"])
    for idx in INDEX_CONFIG
)
open_tab_label = "OPEN TRADES"

tab_options = [
    open_tab_label,
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "🧠 XGBOOST ML",
    "🤖 AI COPILOT",
    "🦾 AUTONOMOUS AI",
    "🎯 SIGNAL AUDIT",
    "TRADE HISTORY",
    "ANALYTICS",
    "⚡ ACTIVITY",
    "SETTINGS",
]

nav_icons = {
    "OPEN TRADES": "▣",
    "NIFTY": "⌁",
    "BANKNIFTY": "▤",
    "FINNIFTY": "▥",
    "🧠 XGBOOST ML": "◈",
    "🤖 AI COPILOT": "✧",
    "🦾 AUTONOMOUS AI": "⟡",
    "🎯 SIGNAL AUDIT": "◎",
    "TRADE HISTORY": "◴",
    "ANALYTICS": "▥",
    "⚡ ACTIVITY": "≋",
    "SETTINGS": "⚙",
}
sidebar_icons = {
    "OPEN TRADES": ":material/work:",
    "NIFTY": ":material/show_chart:",
    "BANKNIFTY": ":material/account_balance:",
    "FINNIFTY": ":material/candlestick_chart:",
    "🧠 XGBOOST ML": ":material/psychology:",
    "🤖 AI COPILOT": ":material/auto_awesome:",
    "🦾 AUTONOMOUS AI": ":material/smart_toy:",
    "🎯 SIGNAL AUDIT": ":material/track_changes:",
    "TRADE HISTORY": ":material/history:",
    "ANALYTICS": ":material/analytics:",
    "⚡ ACTIVITY": ":material/bolt:",
    "SETTINGS": ":material/settings:",
}
mobile_nav_tabs = [open_tab_label, "NIFTY", "🤖 AI COPILOT", "TRADE HISTORY"]


def _select_nav_tab(tab):
    st.session_state["active_nav_tab"] = tab
    st.session_state["main_nav_pills"] = tab


# Normalize values saved by versions that included the live count in the option itself.
saved_nav_value = st.session_state.get("main_nav_pills")
if isinstance(saved_nav_value, str) and "OPEN TRADES" in saved_nav_value:
    st.session_state["main_nav_pills"] = open_tab_label

# Track active tab across reruns and open_count badge updates
if "active_nav_tab" not in st.session_state:
    st.session_state["active_nav_tab"] = open_tab_label if open_count > 0 else "NIFTY"

curr_default = st.session_state["active_nav_tab"]
if curr_default not in tab_options:
    if "OPEN TRADES" in curr_default:
        curr_default = open_tab_label
    else:
        curr_default = "NIFTY"
    st.session_state["active_nav_tab"] = curr_default

previous_nav_tab = st.session_state.get("_last_rendered_nav_tab", curr_default)

with st.sidebar:
    st.markdown(
        '<div class="nav-brand" title="V12 PRO MAX"><strong>V<span>12</span></strong></div>'
        '<div class="nav-section-label">WORKSPACE</div>',
        unsafe_allow_html=True,
    )
    for nav_tab in tab_options:
        nav_label = nav_tab
        if nav_tab == open_tab_label and open_count > 0:
            nav_label = f"{nav_tab} · {open_count}"
        if st.button(
            nav_tab,
            icon=sidebar_icons[nav_tab],
            key=f"sidebar_nav_{tab_options.index(nav_tab)}",
            help=nav_label,
            type="primary" if curr_default == nav_tab else "secondary",
            width="stretch",
        ):
            _select_nav_tab(nav_tab)

with st.container(key="mobile_bottom_nav"):
    mobile_columns = st.columns(5, gap="small")
    for column, nav_tab in zip(mobile_columns[:4], mobile_nav_tabs):
        with column:
            mobile_label = {
                open_tab_label: "▣\nTrades",
                "NIFTY": "⌁\nNifty",
                "🤖 AI COPILOT": "✧\nAI",
                "TRADE HISTORY": "◴\nHistory",
            }[nav_tab]
            if st.button(
                mobile_label,
                key=f"mobile_nav_{tab_options.index(nav_tab)}",
                help=nav_tab,
                type="primary" if curr_default == nav_tab else "secondary",
                width="stretch",
            ):
                _select_nav_tab(nav_tab)
    with mobile_columns[4]:
        with st.popover("☰\nMore", width="stretch"):
            st.markdown("**More pages**")
            for nav_tab in tab_options:
                if nav_tab in mobile_nav_tabs:
                    continue
                if st.button(
                    f"{nav_icons[nav_tab]}  {nav_tab}",
                    key=f"mobile_more_nav_{tab_options.index(nav_tab)}",
                    type="primary" if curr_default == nav_tab else "secondary",
                    width="stretch",
                ):
                    _select_nav_tab(nav_tab)

selected_tab = st.session_state.get("active_nav_tab", curr_default)

st.session_state["_last_rendered_nav_tab"] = selected_tab

def _nav_identity(tab):
    return "OPEN TRADES" if tab and "OPEN TRADES" in tab else tab

navigation_changed = (
    previous_nav_tab is not None
    and _nav_identity(previous_nav_tab) != _nav_identity(selected_tab)
)
if navigation_changed:
    logger.debug("Navigation changed to %s; rendering latest shared snapshot", selected_tab)

# ── BACKGROUND MULTI-INDEX SCANNER & TAB FRAGMENTS ──
# Live panels refresh independently; one process-wide worker scans NIFTY, BANKNIFTY, and FINNIFTY,
# evaluates signals,
# checks SL/TP exits, executes autonomous entries (max 1 open trade per index), and persists state.

@st.fragment(run_every=LIVE_UI_REFRESH_SECONDS)
def show_open_trades():
    render_open_trades_tab(trade_mgr, fetcher)

@st.fragment(run_every=LIVE_UI_REFRESH_SECONDS)
def show_nifty():
    render_index("NIFTY", fetcher, signal_engine, risk_mgr, trade_mgr, journal, copilot)

@st.fragment(run_every=LIVE_UI_REFRESH_SECONDS)
def show_banknifty():
    render_index("BANKNIFTY", fetcher, signal_engine, risk_mgr, trade_mgr, journal, copilot)

@st.fragment(run_every=LIVE_UI_REFRESH_SECONDS)
def show_finnifty():
    render_index("FINNIFTY", fetcher, signal_engine, risk_mgr, trade_mgr, journal, copilot)

def show_analytics():
    render_analytics_tab(journal)

@st.fragment
def show_ai():
    render_ai_copilot_tab(copilot, fetcher, signal_engine, risk_mgr, trade_mgr, journal)

@st.fragment
def show_autonomous():
    from ui.renderer import render_autonomous_tab
    render_autonomous_tab(fetcher, signal_engine, risk_mgr, trade_mgr, journal, copilot)

# ── PURE LAZY TAB RENDERING ──
if "OPEN TRADES" in selected_tab:
    show_open_trades()
elif selected_tab == "NIFTY":
    show_nifty()
elif selected_tab == "BANKNIFTY":
    show_banknifty()
elif selected_tab == "FINNIFTY":
    show_finnifty()
elif "XGBOOST ML" in selected_tab:
    from ui.ml_renderer import render_ml_dashboard
    render_ml_dashboard()
elif "AI COPILOT" in selected_tab:
    show_ai()
elif "AUTONOMOUS AI" in selected_tab:
    show_autonomous()
elif "SIGNAL AUDIT" in selected_tab:
    from ui.audit_renderer import render_audit_tab
    render_audit_tab(auditor, fetcher, copilot)
elif selected_tab == "TRADE HISTORY":
    render_trade_history_tab(journal)
elif selected_tab == "ANALYTICS":
    show_analytics()
elif "ACTIVITY" in selected_tab:
    from ui.health_renderer import render_health_dashboard
    render_health_dashboard(fetcher, trade_mgr, copilot)
elif selected_tab == "SETTINGS":
    render_settings_tab(trade_mgr, journal)


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

# ── MOBILE SCREEN WAKE LOCK (Keeps screen alive during market hours) ──
_wake_lock_html = """
<script>
let wakeLock = null;
async function requestWakeLock() {
  try {
    if ('wakeLock' in navigator) {
      wakeLock = await navigator.wakeLock.request('screen');
    }
  } catch (err) {}
}
requestWakeLock();
document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState === 'visible') {
    await requestWakeLock();
  }
});
</script>
"""
if hasattr(st, "iframe"):
    st.iframe(_wake_lock_html, height=1, width=1)
else:
    import streamlit.components.v1 as components
    components.html(_wake_lock_html, height=0, width=0)
