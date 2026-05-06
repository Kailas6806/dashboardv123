import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import time
import json
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="GOC Technology - Algo Trading",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---- Dark GOC-style CSS ----
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');
    
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    
    .main { background-color: #0d0e17; color: #e0e0e0; }
    .stApp { background-color: #0d0e17; }
    
    /* Top Nav Bar */
    .goc-navbar {
        background: linear-gradient(135deg, #12131f 0%, #1a1b2e 100%);
        padding: 10px 20px;
        border-radius: 10px;
        border: 1px solid #2a2b3d;
        margin-bottom: 15px;
        display: flex; align-items: center; justify-content: space-between;
    }
    .goc-logo { color: #4dc4ff; font-size: 22px; font-weight: 800; letter-spacing: 1px; }
    
    /* Metric Cards */
    .metric-card {
        background: linear-gradient(135deg, #1a1b2e 0%, #12131f 100%);
        border: 1px solid #2a2b3d;
        border-radius: 10px;
        padding: 12px 16px;
        text-align: center;
    }
    .metric-value { font-size: 22px; font-weight: 800; color: #ffffff; }
    .metric-label { font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 1px; }
    
    /* Signal Badges */
    .signal-ce { background: rgba(0,230,118,0.15); border: 1.5px solid #00e676; border-radius: 8px; padding: 12px; text-align: center; }
    .signal-pe { background: rgba(255,23,68,0.15); border: 1.5px solid #ff1744; border-radius: 8px; padding: 12px; text-align: center; }
    .signal-wait { background: rgba(255,193,7,0.1); border: 1.5px solid #ffc107; border-radius: 8px; padding: 12px; text-align: center; }
    
    /* Meter Bar */
    .meter-container { background: #1a1b2e; border-radius: 20px; padding: 3px; overflow: hidden; height: 14px; }
    .meter-bull { background: linear-gradient(90deg, #00e676, #00c853); border-radius: 20px; height: 100%; float: left; }
    .meter-bear { background: linear-gradient(90deg, #ff5252, #ff1744); border-radius: 20px; height: 100%; float: right; }
    
    /* Option Chain Tables */
    .oc-header { background: #1a1b2e; padding: 8px 12px; border-radius: 8px 8px 0 0; font-size: 12px; font-weight: 700; color: #4dc4ff; }
    .oc-row-ce { background: rgba(0,230,118,0.05); padding: 6px 10px; border-bottom: 1px solid #1a1b2e; display: flex; justify-content: space-between; font-size: 12px; }
    .oc-row-pe { background: rgba(255,23,68,0.05); padding: 6px 10px; border-bottom: 1px solid #1a1b2e; display: flex; justify-content: space-between; font-size: 12px; }
    .oc-atm { background: rgba(77,196,255,0.1); }
    
    /* Scanner Row */
    .scanner-row { background: #1a1b2e; border: 1px solid #2a2b3d; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; }
    
    /* Override Streamlit defaults */
    .stTabs [data-baseweb="tab-list"] { background: #12131f; border-radius: 10px; gap: 4px; padding: 4px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px; color: #6b7280; font-weight: 600; padding: 6px 20px; }
    .stTabs [aria-selected="true"] { background: #4dc4ff !important; color: #0d0e17 !important; }
    
    div[data-testid="metric-container"] { background: #1a1b2e; border: 1px solid #2a2b3d; border-radius: 10px; padding: 12px; }
    div[data-testid="metric-container"] label { color: #6b7280 !important; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 20px; font-weight: 800; color: #ffffff; }
    
    .stSidebar { background: #12131f; border-right: 1px solid #2a2b3d; }
    
    hr { border-color: #2a2b3d; }
    
    /* Hide ALL Streamlit spinner/status text completely */
    div[data-testid="stStatusWidget"] { display: none !important; }
    .stSpinner { display: none !important; }
    div[data-testid="stToolbar"] { display: none !important; }
    [class*="StatusWidget"] { display: none !important; }
    .running-animation { display: none !important; }
    
    /* scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #12131f; }
    ::-webkit-scrollbar-thumb { background: #2a2b3d; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ---- Session State Initialization ----
if "capital" not in st.session_state:
    st.session_state.capital = 30000.0
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "selected_index" not in st.session_state:
    st.session_state.selected_index = "NIFTY"
if "last_signal_sent" not in st.session_state:
    st.session_state.last_signal_sent = {}

TICKERS = {
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK",
    "Finnifty": "NIFTY_FIN_SERVICE.NS"
}

NSE_INDICES = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS"
}

LOT_SIZES = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25}
STRIKE_GAPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50}

# Top F&O stocks
FNO_STOCKS = {
    "RELIANCE": "RELIANCE.NS",
    "HDFC BANK": "HDFCBANK.NS",
    "ICICI BANK": "ICICIBANK.NS",
    "INFOSYS": "INFY.NS",
    "TCS": "TCS.NS",
}

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# ==========================================
# 2. NSE API & DATA FUNCTIONS
# ==========================================

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/",
}

@st.cache_data(ttl=10, show_spinner=False)
def get_nse_session_cookies():
    """Establish a valid NSE session to bypass anti-scraping."""
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=5)
        session.get("https://www.nseindia.com/option-chain", headers=NSE_HEADERS, timeout=5)
        return dict(session.cookies)
    except Exception:
        return {}

@st.cache_data(ttl=10, show_spinner=False)
def fetch_nse_option_chain(symbol="NIFTY"):
    """Fetch live NSE Option Chain data with session spoofing."""
    cookies = get_nse_session_cookies()
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    try:
        resp = requests.get(url, headers=NSE_HEADERS, cookies=cookies, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("records", {})
        else:
            return None
    except Exception:
        return None

def parse_option_chain(oc_data, spot_price, symbol="NIFTY"):
    """Parse NSE option chain JSON into a structured DataFrame."""
    if not oc_data or "data" not in oc_data:
        return None, None

    gap = STRIKE_GAPS.get(symbol, 50)
    atm = round(spot_price / gap) * gap

    rows = []
    for record in oc_data["data"]:
        strike = record.get("strikePrice", 0)
        ce = record.get("CE", {})
        pe = record.get("PE", {})

        if abs(strike - atm) <= gap * 6:
            rows.append({
                "strike": strike,
                "is_atm": strike == atm,
                "ce_ltp": ce.get("lastPrice", 0),
                "ce_oi": ce.get("openInterest", 0),
                "ce_chg_oi": ce.get("changeinOpenInterest", 0),
                "ce_vol": ce.get("totalTradedVolume", 0),
                "ce_iv": ce.get("impliedVolatility", 0),
                "pe_ltp": pe.get("lastPrice", 0),
                "pe_oi": pe.get("openInterest", 0),
                "pe_chg_oi": pe.get("changeinOpenInterest", 0),
                "pe_vol": pe.get("totalTradedVolume", 0),
                "pe_iv": pe.get("impliedVolatility", 0),
            })

    if not rows:
        return None, atm

    df = pd.DataFrame(rows).sort_values("strike")
    return df, atm

def generate_synthetic_option_chain(spot_price, symbol="NIFTY"):
    """Synthetic fallback when NSE API is unavailable."""
    gap = STRIKE_GAPS.get(symbol, 50)
    atm = round(spot_price / gap) * gap
    strikes = [atm + gap * i for i in range(-6, 7)]
    rows = []
    for strike in strikes:
        diff = (spot_price - strike)
        # Rough Black-Scholes approximation for options values
        ce_intrinsic = max(0, diff * -1)
        pe_intrinsic = max(0, diff)
        ce_ltp = max(5, ce_intrinsic + np.random.uniform(20, 80))
        pe_ltp = max(5, pe_intrinsic + np.random.uniform(20, 80))
        rows.append({
            "strike": strike,
            "is_atm": strike == atm,
            "ce_ltp": round(ce_ltp, 1),
            "ce_oi": int(np.random.uniform(50000, 500000)),
            "ce_chg_oi": int(np.random.uniform(-50000, 100000)),
            "ce_vol": int(np.random.uniform(1000, 50000)),
            "ce_iv": round(np.random.uniform(12, 25), 1),
            "pe_ltp": round(pe_ltp, 1),
            "pe_oi": int(np.random.uniform(50000, 500000)),
            "pe_chg_oi": int(np.random.uniform(-50000, 100000)),
            "pe_vol": int(np.random.uniform(1000, 50000)),
            "pe_iv": round(np.random.uniform(12, 25), 1),
        })
    return pd.DataFrame(rows), atm

@st.cache_data(ttl=10, show_spinner=False)
def fetch_mtf_data(ticker_symbol):
    """Fetch 1m, 5m, 15m data for Multi-Timeframe analysis."""
    data = {}
    try:
        for interval, period in [("1m", "2d"), ("5m", "5d"), ("15m", "5d")]:
            df = yf.download(tickers=ticker_symbol, period=period, interval=interval, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
            data[interval] = df
        return data
    except Exception:
        return {"1m": pd.DataFrame(), "5m": pd.DataFrame(), "15m": pd.DataFrame()}

@st.cache_data(ttl=10, show_spinner=False)
def fetch_stock_data(ticker):
    """Fetch single stock 1m data for F&O Scanner."""
    try:
        df = yf.download(tickers=ticker, period="2d", interval="1m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        return df
    except Exception:
        return pd.DataFrame()

# ==========================================
# 3. TECHNICAL INDICATORS
# ==========================================

def calculate_rsi(data, period=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = (gain / loss).replace([np.inf, -np.inf], 100)
    return 100 - (100 / (1 + rs))

def calculate_vwap(df):
    q = df.get('Volume', pd.Series(1, index=df.index))
    if q.sum() == 0:
        q = pd.Series(1, index=df.index)
    p = (df['High'] + df['Low'] + df['Close']) / 3
    try:
        df_copy = df.copy()
        df_copy['Date'] = df_copy.index.date
        vwap = df_copy.groupby('Date', group_keys=False).apply(
            lambda x: (p.loc[x.index] * q.loc[x.index]).cumsum() / q.loc[x.index].cumsum()
        )
        if len(vwap) == len(df):
            return vwap
    except Exception:
        pass
    return (p * q).cumsum() / q.cumsum()

def apply_indicators(df_1m):
    if df_1m.empty or len(df_1m) < 50:
        return df_1m
    df = df_1m.copy()
    df['VWAP'] = calculate_vwap(df)
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['RSI_14'] = calculate_rsi(df, period=14)
    today = df.index[-1].date()
    today_mask = df.index.date == today
    df.loc[today_mask, 'Intraday_High'] = df.loc[today_mask, 'High'].cummax()
    df.loc[today_mask, 'Intraday_Low'] = df.loc[today_mask, 'Low'].cummin()
    df['Intraday_High'] = df['Intraday_High'].ffill()
    df['Intraday_Low'] = df['Intraday_Low'].ffill()
    daily = df.resample('D').agg({'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
    if len(daily) >= 2:
        prev = daily.iloc[-2]
        P = (prev['High'] + prev['Low'] + prev['Close']) / 3
        df['Pivot'] = P
        df['R1'] = (2 * P) - prev['Low']
        df['S1'] = (2 * P) - prev['High']
        df['R2'] = P + (prev['High'] - prev['Low'])
        df['S2'] = P - (prev['High'] - prev['Low'])
    else:
        for col in ['Pivot', 'R1', 'S1', 'R2', 'S2']:
            df[col] = np.nan
    return df

def get_macro_trend(df):
    if df is None or df.empty or len(df) < 50:
        return "Sideways", 50
    ema20 = df['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
    rsi_val = calculate_rsi(df).iloc[-1]
    rsi_val = float(rsi_val) if not pd.isna(rsi_val) else 50.0
    if ema20 > ema50 and rsi_val > 52:
        bull_pct = min(90, 50 + (rsi_val - 50) * 1.5)
        return "Bullish", round(bull_pct)
    elif ema20 < ema50 and rsi_val < 48:
        bear_pct = min(90, 50 + (50 - rsi_val) * 1.5)
        return "Bearish", round(bear_pct)
    return "Sideways", 50

def generate_signal(row, trend_5m, trend_15m):
    price, vwap, ema20, ema50, rsi = (
        float(row['Close']), float(row['VWAP']), float(row['EMA_20']),
        float(row['EMA_50']), float(row['RSI_14'])
    )
    if any(pd.isna(v) for v in [vwap, ema50, rsi]):
        return "WAIT", "Insufficient Data", None, None, None

    micro_bull = price > vwap and ema20 > ema50 and rsi > 55
    micro_bear = price < vwap and ema20 < ema50 and rsi < 45
    macro_bull = (trend_5m == "Bullish" and trend_15m == "Bullish")
    macro_bear = (trend_5m == "Bearish" and trend_15m == "Bearish")

    intra_high = row.get('Intraday_High', np.nan)
    intra_low = row.get('Intraday_Low', np.nan)
    r1 = row.get('R1', np.nan)
    s1 = row.get('S1', np.nan)

    if not pd.isna(intra_high) and not pd.isna(r1):
        breakout_up = price >= min(intra_high, r1)
    elif not pd.isna(intra_high):
        breakout_up = price >= intra_high
    else:
        breakout_up = False

    if not pd.isna(intra_low) and not pd.isna(s1):
        breakout_down = price <= max(intra_low, s1)
    elif not pd.isna(intra_low):
        breakout_down = price <= intra_low
    else:
        breakout_down = False

    if micro_bull and macro_bull and breakout_up:
        sl = price * 0.99
        risk = price - sl
        return "BUY CE", "Bull Breakout ✅", sl, price + risk * 2, price + risk * 4
    elif micro_bear and macro_bear and breakout_down:
        sl = price * 1.01
        risk = sl - price
        return "BUY PE", "Bear Breakdown ✅", sl, price - risk * 2, price - risk * 4
    elif micro_bull:
        return "WAIT", "Mild Bullish (Await Breakout)", None, None, None
    elif micro_bear:
        return "WAIT", "Mild Bearish (Await Breakdown)", None, None, None
    else:
        return "WAIT", "Sideways / Chop Zone", None, None, None

# ==========================================
# 4. PAPER TRADING ENGINE
# ==========================================

def manage_paper_trading(index_name, latest_price, signal, sl, target1, target2):
    LOT_SIZE = 15 if "Bank" in index_name else 25
    DELTA = 0.5
    positions = st.session_state.positions
    timestamp = datetime.now().strftime("%H:%M:%S")

    if index_name in positions and positions[index_name]:
        pos = positions[index_name]
        ttrade, entry_price, pos_sl = pos['type'], pos['entry'], pos['sl']
        exit_triggered, exit_price, reason = False, 0, ""
        if ttrade == "BUY CE":
            if latest_price <= pos_sl:
                exit_triggered, exit_price, reason = True, pos_sl, "🛑 Stop Loss"
            elif latest_price >= pos['target1']:
                exit_triggered, exit_price, reason = True, latest_price, "🎯 Target Hit"
        elif ttrade == "BUY PE":
            if latest_price >= pos_sl:
                exit_triggered, exit_price, reason = True, pos_sl, "🛑 Stop Loss"
            elif latest_price <= pos['target1']:
                exit_triggered, exit_price, reason = True, latest_price, "🎯 Target Hit"
        if exit_triggered:
            points = (exit_price - entry_price) if ttrade == "BUY CE" else (entry_price - exit_price)
            pnl = round(points * DELTA * LOT_SIZE, 2)
            st.session_state.capital += pnl
            st.session_state.trade_history.append({
                "⏰ Time": timestamp, "Index": index_name, "Type": ttrade,
                "Entry": round(entry_price, 2), "Exit": round(exit_price, 2),
                "P&L (₹)": pnl, "Status": reason
            })
            positions[index_name] = None
            send_telegram_alert(f"🔴 *TRADE CLOSED* | {index_name}\n{reason}\nP&L: ₹{pnl}")

    if (index_name not in positions or not positions[index_name]) and signal in ["BUY CE", "BUY PE"]:
        positions[index_name] = {
            "type": signal, "entry": latest_price, "sl": sl,
            "target1": target1, "target2": target2, "time": timestamp
        }
        send_telegram_alert(f"🟢 *SIGNAL* | {index_name}\n{signal} @ ₹{latest_price:.2f}\nSL: ₹{sl:.2f} T1: ₹{target1:.2f}")

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=2)
    except Exception:
        pass

# ==========================================
# 5. UI COMPONENTS
# ==========================================

def render_navbar():
    now = datetime.now().strftime("%d %b %Y  %H:%M:%S")
    mkt_open = 9 <= datetime.now().hour < 15 or (datetime.now().hour == 15 and datetime.now().minute <= 30)
    status_color = "#00e676" if mkt_open else "#ff1744"
    status_text = "MARKET OPEN" if mkt_open else "MARKET CLOSED"
    st.markdown(f"""
    <div class="goc-navbar">
        <div class="goc-logo">⚡ GOC Technology <span style="font-size:13px; color:#6b7280; font-weight:400;">| Algo Suite</span></div>
        <div style="display:flex; gap:20px; align-items:center;">
            <span style="font-size:12px; color:#4dc4ff;">Pullers/Draggers</span>
            <span style="font-size:12px; color:#4dc4ff;">GOC Meter</span>
            <span style="font-size:12px; color:#4dc4ff;">GOC Scanner</span>
            <span style="font-size:12px; color:#4dc4ff;">Option Chain</span>
            <div style="background:{status_color}; color:#000; font-size:11px; font-weight:700; padding:4px 10px; border-radius:20px;">{status_text}</div>
            <span style="font-size:12px; color:#6b7280;">{now}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_paper_trading_console():
    total = len(st.session_state.trade_history)
    wins = sum(1 for t in st.session_state.trade_history if t['P&L (₹)'] > 0)
    net_pnl = st.session_state.capital - 30000.0
    pnl_color = "#00e676" if net_pnl >= 0 else "#ff1744"
    win_rate = f"{int((wins/total)*100)}%" if total > 0 else "N/A"
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 Capital", f"₹{st.session_state.capital:,.0f}")
    c2.metric("📊 Trades", total)
    c3.metric("🏆 Win Rate", win_rate)
    c4.metric("📈 Net P&L", f"₹{net_pnl:,.2f}", delta=round(net_pnl, 2))
    active_count = sum(1 for v in st.session_state.positions.values() if v)
    c5.metric("🔄 Active Positions", active_count)

def render_goc_meter(bull_pct_5m, bear_pct_5m, bull_pct_15m, bear_pct_15m, index_key):
    """Render a GOC-style sentiment meter bar."""
    bull_avg = round((bull_pct_5m + bull_pct_15m) / 2)
    bear_avg = 100 - bull_avg
    color = "#00e676" if bull_avg > 50 else "#ff1744" if bear_avg > 50 else "#ffc107"
    label = "🟢 Bullish" if bull_avg > 55 else "🔴 Bearish" if bear_avg > 55 else "🟡 Neutral"
    
    st.markdown(f"""
    <div style="background:#1a1b2e; border-radius:8px; padding:10px; margin-bottom:8px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:12px;">
            <span style="color:#00e676; font-weight:700;">BULL {bull_avg}%</span>
            <span style="font-weight:700; color:{color};">{label}</span>
            <span style="color:#ff1744; font-weight:700;">BEAR {bear_avg}%</span>
        </div>
        <div style="background:#0d0e17; border-radius:20px; height:12px; overflow:hidden;">
            <div style="width:{bull_avg}%; background:linear-gradient(90deg,#00e676,#00c853); height:100%; border-radius:20px; float:left;"></div>
        </div>
        <div style="display:flex; justify-content:space-between; margin-top:6px; font-size:10px; color:#6b7280;">
            <span>5m: {'🟢' if bull_pct_5m > 50 else '🔴'}</span>
            <span>15m: {'🟢' if bull_pct_15m > 50 else '🔴'}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_option_chain_table(oc_df, atm, symbol):
    """Render a clean GOC-style option chain table using st.dataframe."""
    if oc_df is None or oc_df.empty:
        st.warning("Option chain data unavailable.")
        return

    total_ce_oi = oc_df['ce_oi'].sum()
    total_pe_oi = oc_df['pe_oi'].sum()
    pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
    pcr_sentiment = "🐂 Bullish" if pcr > 1.2 else "🐻 Bearish" if pcr < 0.8 else "⚖️ Neutral"

    col_pcr, col_pcr2 = st.columns(2)
    col_pcr.metric("PCR", pcr)
    col_pcr2.metric("Sentiment", pcr_sentiment)

    # Build a clean, flat dataframe for display
    display_rows = []
    for _, row in oc_df.iterrows():
        atm_marker = " ◀ ATM" if row['strike'] == atm else ""
        display_rows.append({
            "CE LTP": f"{row['ce_ltp']:.1f}",
            "CE ΔOI": f"{int(row['ce_chg_oi']/1000):+}K",
            "STRIKE": f"{int(row['strike'])}{atm_marker}",
            "PE ΔOI": f"{int(row['pe_chg_oi']/1000):+}K",
            "PE LTP": f"{row['pe_ltp']:.1f}",
        })
    df_display = pd.DataFrame(display_rows)
    st.dataframe(df_display, use_container_width=True, hide_index=True, height=320)

def render_fno_scanner():
    """F&O Top Stocks Sector Scanner Panel."""
    st.markdown("#### 🔍 F&O Stock Scanner")
    rows = []
    for name, ticker in FNO_STOCKS.items():
        df = fetch_stock_data(ticker)
        if df.empty or len(df) < 20:
            continue
        latest_close = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2]) if len(df) > 1 else latest_close
        chg_pct = round(((latest_close - prev_close) / prev_close) * 100, 2)
        rsi = float(calculate_rsi(df).iloc[-1])
        ema20 = float(df['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
        trend = "🟢 Bull" if (latest_close > ema20 and rsi > 52) else "🔴 Bear" if (latest_close < ema20 and rsi < 48) else "🟡 Neutral"
        rows.append({"Stock": name, "LTP": f"₹{latest_close:,.1f}", "Chg%": chg_pct, "RSI": round(rsi, 1), "Trend": trend})

    if rows:
        df_scan = pd.DataFrame(rows)
        for _, r in df_scan.iterrows():
            chg_color = "#00e676" if r['Chg%'] >= 0 else "#ff5252"
            st.markdown(f"""
            <div style="background:#1a1b2e; border:1px solid #2a2b3d; border-radius:8px; padding:8px 14px; margin-bottom:5px; display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; font-size:13px;">{r['Stock']}</span>
                <span style="color:#ffffff; font-size:13px;">{r['LTP']}</span>
                <span style="color:{chg_color}; font-size:13px; font-weight:700;">{'+' if r['Chg%'] >= 0 else ''}{r['Chg%']}%</span>
                <span style="font-size:12px; color:#6b7280;">RSI: {r['RSI']}</span>
                <span style="font-size:12px;">{r['Trend']}</span>
            </div>
            """, unsafe_allow_html=True)

def render_index_signal_panel(index_name, nse_symbol, ticker_symbol):
    """Full GOC-style index analysis panel."""
    data = fetch_mtf_data(ticker_symbol)
    df_1m, df_5m, df_15m = data.get("1m"), data.get("5m"), data.get("15m")

    if df_1m is None or df_1m.empty or len(df_1m) < 50:
        st.error(f"Insufficient data for {index_name}.")
        return

    df = apply_indicators(df_1m)
    latest = df.iloc[-1]
    spot = float(latest['Close'])
    
    trend_5m, bull_5m = get_macro_trend(df_5m)
    trend_15m, bull_15m = get_macro_trend(df_15m)
    bear_5m = 100 - bull_5m
    bear_15m = 100 - bull_15m

    signal, bias, sl, target1, target2 = generate_signal(latest, trend_5m, trend_15m)
    manage_paper_trading(index_name, spot, signal, sl, target1, target2)

    # Send toast alert only if signal changes
    last_sig = st.session_state.last_signal_sent.get(index_name)
    if signal in ["BUY CE", "BUY PE"] and last_sig != signal:
        st.toast(f"🚨 {index_name}: {signal} triggered!", icon="💥")
        st.session_state.last_signal_sent[index_name] = signal
    elif signal == "WAIT":
        st.session_state.last_signal_sent[index_name] = None

    # ---- Price & Signal Header ----
    signal_info = {
        "BUY CE": ("#00e676", "rgba(0,230,118,0.15)", "🚨 BUY CE 🚨"),
        "BUY PE": ("#ff1744", "rgba(255,23,68,0.15)", "🚨 BUY PE 🚨"),
        "WAIT": ("#ffc107", "rgba(255,193,7,0.08)", "⏳ WAIT")
    }
    sig_color, sig_bg, sig_text = signal_info.get(signal, ("#888", "rgba(128,128,128,0.1)", signal))

    col_metrics, col_signal = st.columns([2, 1])
    with col_metrics:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Spot Price", f"₹{spot:,.2f}")
        m2.metric("VWAP", f"₹{float(latest['VWAP']):,.0f}")
        m3.metric("RSI (14)", f"{float(latest['RSI_14']):.1f}")
        m4.metric("EMA 20/50", f"{float(latest['EMA_20']):.0f}/{float(latest['EMA_50']):.0f}")

    with col_signal:
        sl_str = f"₹{sl:.0f}" if sl else "—"
        t1_str = f"₹{target1:.0f}" if target1 else "—"
        st.markdown(f"""
        <div style="background:{sig_bg}; border:2px solid {sig_color}; border-radius:10px; padding:14px; text-align:center;">
            <div style="font-size:18px; font-weight:900; color:{sig_color};">{sig_text}</div>
            <div style="font-size:11px; color:#aaa; margin-top:5px;">{bias}</div>
            <div style="font-size:12px; margin-top:8px;">
                <span style="color:#ff5252;">SL: {sl_str}</span>&nbsp;&nbsp;
                <span style="color:#00e676;">T1: {t1_str}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ---- GOC Meter ----
    render_goc_meter(bull_5m, bear_5m, bull_15m, bear_15m, nse_symbol)

    # ---- Layout: Chart Left, Option Chain Right ----
    col_chart, col_oc = st.columns([3, 2])

    with col_chart:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'
        ))
        if 'VWAP' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='yellow', width=1.2, dash='dot'), name='VWAP'))
        if 'EMA_20' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='orange', width=1.2), name='EMA 20'))
        if 'EMA_50' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#b388ff', width=1.2), name='EMA 50'))
        
        # Draw horizontal levels
        last_x = [df.index[max(0, len(df)-60)], df.index[-1]]
        level_data = {"R1": ("red", df['R1'].iloc[-1]), "S1": ("lime", df['S1'].iloc[-1]),
                      "Pivot": ("#4dc4ff", df['Pivot'].iloc[-1])}
        for lname, (lcol, lval) in level_data.items():
            if not pd.isna(lval):
                fig.add_trace(go.Scatter(x=last_x, y=[lval, lval], line=dict(color=lcol, width=1, dash='dash'), name=lname, showlegend=True))

        fig.update_layout(
            template="plotly_dark", height=320,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_rangeslider_visible=False, paper_bgcolor="#0d0e17", plot_bgcolor="#0d0e17",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10))
        )
        st.plotly_chart(fig, use_container_width=True)

        # Smart Levels table
        col_sl1, col_sl2 = st.columns(2)
        with col_sl1:
            st.markdown(f"""
            <div style="background:#1a1b2e; border-radius:8px; padding:10px; font-size:12px;">
                <div style="color:#4dc4ff; font-weight:700; margin-bottom:5px;">📍 Pivot Levels</div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">R2</span><span style="color:#ff5252;">{float(df['R2'].iloc[-1]):,.0f}</span></div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">R1</span><span style="color:#ff7043;">{float(df['R1'].iloc[-1]):,.0f}</span></div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">Pivot</span><span style="color:#4dc4ff;">{float(df['Pivot'].iloc[-1]):,.0f}</span></div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">S1</span><span style="color:#66bb6a;">{float(df['S1'].iloc[-1]):,.0f}</span></div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">S2</span><span style="color:#00e676;">{float(df['S2'].iloc[-1]):,.0f}</span></div>
            </div>
            """, unsafe_allow_html=True)
        with col_sl2:
            st.markdown(f"""
            <div style="background:#1a1b2e; border-radius:8px; padding:10px; font-size:12px;">
                <div style="color:#4dc4ff; font-weight:700; margin-bottom:5px;">📊 Intraday Levels</div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">Intraday High</span><span style="color:#ff5252;">{float(latest['Intraday_High']):,.0f}</span></div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">Intraday Low</span><span style="color:#00e676;">{float(latest['Intraday_Low']):,.0f}</span></div>
                <div style="display:flex; justify-content:space-between;"><span style="color:#6b7280;">Current</span><span style="color:#ffffff;">{spot:,.1f}</span></div>
            </div>
            """, unsafe_allow_html=True)

    with col_oc:
        st.markdown("**📋 Option Chain**")
        
        # Attempt NSE API; else synthetic
        oc_raw = fetch_nse_option_chain(nse_symbol)
        if oc_raw:
            oc_df, atm = parse_option_chain(oc_raw, spot, nse_symbol)
        else:
            oc_df, atm = None, None

        if oc_df is None:
            atm_val = round(spot / STRIKE_GAPS.get(nse_symbol, 50)) * STRIKE_GAPS.get(nse_symbol, 50)
            oc_df, atm = generate_synthetic_option_chain(spot, nse_symbol)
            st.caption("⚠️ Live NSE data unavailable — showing simulated strikes")

        render_option_chain_table(oc_df, atm, nse_symbol)
        
        # ATM suggestion
        lot = LOT_SIZES.get(nse_symbol, 25)
        st.markdown(f"""
        <div style="background:#1a1b2e; border-radius:8px; padding:10px; margin-top:8px; font-size:12px;">
            <div style="color:#4dc4ff; font-weight:700; margin-bottom:4px;">🎯 ATM Strike Info</div>
            <div>ATM Strike: <b>{atm}</b></div>
            <div>Lot Size: <b>{lot}</b> | Delta: ~<b>0.5</b></div>
            <div style="margin-top:4px; color:#ffc107;">Trade: <b>ATM {signal.replace('BUY ', '') if signal != 'WAIT' else '—'}</b> option for this setup</div>
        </div>
        """, unsafe_allow_html=True)

# ==========================================
# 6. MAIN APP
# ==========================================

def is_market_open():
    """Returns True if current IST time is within NSE market hours (Mon-Fri, 9:15-15:30)."""
    from datetime import timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    if now_ist.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now_ist <= market_end

def main():
    render_navbar()

    mkt_open = is_market_open()

    # Only auto-refresh silently when market is live
    if mkt_open:
        st_autorefresh(interval=10000, limit=None, key="goc_autorefresh")

    with st.sidebar:
        st.markdown("### ⚙️ Control Panel")
        if mkt_open:
            st.success("🟢 MARKET LIVE — Auto-syncing every 10s")
        else:
            st.error("🔴 MARKET CLOSED")
            if st.button("🔄 Manual Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        st.markdown("---")
        
        # Paper Trading Console
        st.markdown("### 🏦 Paper Trading Console")
        render_paper_trading_console()
        
        st.markdown("---")
        st.markdown("### 📱 Telegram Alerts")
        tel_token = st.text_input("Bot Token", type="password", key="tel_tok")
        tel_chat = st.text_input("Chat ID", key="tel_chat")
        if tel_token and tel_chat:
            global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            TELEGRAM_BOT_TOKEN = tel_token
            TELEGRAM_CHAT_ID = tel_chat
            st.success("Telegram Connected ✅")
        st.markdown("---")
        if st.button("🔄 Reset Portfolio"):
            st.session_state.capital = 30000.0
            st.session_state.positions = {}
            st.session_state.trade_history = []
            st.rerun()

    # Main content
    # Top scanner row
    render_fno_scanner()
    st.markdown("---")
    
    # Index scanner tabs
    st.markdown("### 📊 Index Option Scanner")
    tab1, tab2, tab3 = st.tabs(["Nifty 50", "Bank Nifty", "Finnifty"])
    
    with tab1:
        render_index_signal_panel("Nifty 50", "NIFTY", "^NSEI")
    with tab2:
        render_index_signal_panel("Bank Nifty", "BANKNIFTY", "^NSEBANK")
    with tab3:
        render_index_signal_panel("Finnifty", "FINNIFTY", "NIFTY_FIN_SERVICE.NS")
    
    # Trade history
    if st.session_state.trade_history:
        st.markdown("---")
        st.markdown("### 📝 Execution Ledger")
        df_hist = pd.DataFrame(st.session_state.trade_history)
        st.dataframe(df_hist, use_container_width=True)

    # Refresh is handled by st_autorefresh above — no blocking sleep needed

if __name__ == "__main__":
    main()
