"""
V12 PRO MAX — Centralized Configuration
All tunable parameters live here. Core signal thresholds are included
for reference but MUST NOT be modified (they are the trading philosophy).
"""
import datetime

# ── TIMEZONE ──
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# ── CAPITAL & RISK ──
CAPITAL   = 20_000
MAX_LOSS  = 1000
DAILY_TGT = 2000

# ── INDEX CONFIG ──
INDEX_CONFIG = {
    "NIFTY":     {"step": 50,  "lot": 65,  "rng": 300},
    "BANKNIFTY": {"step": 100, "lot": 30,  "rng": 600},
    "FINNIFTY":  {"step": 50,  "lot": 60,  "rng": 300},
}

# ── TRADE LOG COLUMNS ──
LOG_COLS = [
    "Entry Time", "Exit Time", "Index", "Signal", "Spot", "Strike",
    "Entry Price", "Live Price", "Exit Price",
    "Stop Loss", "Target", "Qty", "Max Loss ₹", "Target P&L ₹",
    "Actual P&L ₹", "Status", "Result",
]

# ── SIGNAL QUALITY & FILTERING ──
SIGNAL_BUFFER_SIZE     = 3       # number of refreshes to buffer
SIGNAL_CONFIRM_COUNT   = 2       # confirmations needed (2-of-3)
SIDEWAYS_PCR_LOW       = 0.85    # PCR below this + above high = sideways
SIDEWAYS_PCR_HIGH      = 1.15
SIDEWAYS_SPOT_STDEV_PCT = 0.001  # 0.1% stdev threshold for strong sideways

# ── VWAP ──
VWAP_HISTORY_SIZE = 50           # spot readings for volume-weighted VWAP proxy

# ── OI ANALYSIS ──
OI_UNUSUAL_THRESHOLD = 0.30     # single strike > 30% of total delta = unusual

# ── COOLDOWN & MARKET OPEN ──
COOLDOWN_SECONDS        = 300    # 5 min cooldown after SL hit
MARKET_OPEN_BUFFER_MIN  = 3      # suppress entries 9:15–9:18
MARKET_OPEN_TIME        = datetime.time(9, 15)
MARKET_CLOSE_TIME       = datetime.time(15, 30)
AUTO_SQUARE_OFF_TIME    = datetime.time(15, 25)

# ── RISK MANAGEMENT ──
ATR_PERIOD               = 14    # periods for ATR calculation
ATR_SL_MULTIPLIER        = 1.5   # SL = entry ∓ (multiplier × ATR)
TRAILING_STOP_ACTIVATION = 0.50  # activate trail at 50% of target profit
TRAILING_STOP_LOCK_PCT   = 0.80  # lock in 80% of highest seen profit
MAX_DAILY_LOSSES         = 3     # stop trading after N consecutive losses

# ── CACHING ──
CACHE_TTL_SECONDS = 2            # option chain cache TTL

# ── NSE FETCH ──
MAX_RETRIES            = 3       # retry attempts for NSE fetch
RETRY_BACKOFF_BASE     = 0.5     # exponential backoff base (0.5s, 1s, 2s)
AUTO_RECOVERY_THRESHOLD = 5      # full session rebuild after N consecutive failures
MIN_REQUEST_INTERVAL   = 1.0     # minimum seconds between NSE requests per index

# ── TELEGRAM ──
TELEGRAM_MAX_RATE      = 20      # max messages per minute
TELEGRAM_BATCH_WINDOW  = 2.0     # seconds to batch rapid messages
TELEGRAM_MAX_RETRIES   = 3       # retry failed sends

# ── LOGGING ──
LOG_DIR           = "logs"
LOG_MAX_BYTES     = 5 * 1024 * 1024   # 5 MB per log file
LOG_BACKUP_COUNT  = 5                  # keep 5 rotated files

# ── TRADE JOURNAL ──
JOURNAL_FILE = "trade_journal.json"

# ── CONFIDENCE SCORING WEIGHTS (display only, does NOT gate signals) ──
CONF_WEIGHT_PCR       = 25   # max points from PCR strength
CONF_WEIGHT_VWAP      = 20   # max points from VWAP distance
CONF_WEIGHT_OI_DELTA  = 20   # max points from OI delta magnitude
CONF_WEIGHT_PCR_MOM   = 15   # max points from PCR momentum streak
CONF_WEIGHT_SR_PROX   = 10   # max points from S/R proximity
CONF_PENALTY_TRAP     = 10   # penalty points for trap detection

# ── STREAMLIT REFRESH ──
FRAGMENT_REFRESH_SECONDS = 3   # @st.fragment(run_every=N)
DAILY_REPORT_CHECK_SECS  = 60  # check for daily report every N seconds
DAILY_REPORT_TIME        = datetime.time(14, 55)
