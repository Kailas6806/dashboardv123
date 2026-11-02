"""
V12 PRO MAX — Feature Engineering for XGBoost Win Probability Model.

Production pipeline (11 direction-aware, normalized features):
  build(df)                  – batch feature extraction from trade DataFrame
  build_live_features(...)   – single-row feature extraction for live prediction

Legacy pipeline (kept for historical_trainer.py):
  extract_features(...)      – 19-feature set from replayed candle data
"""
import json
import datetime
import numpy as np
import pandas as pd

from config import IST


# ── 11 PRODUCTION FEATURES (all known at entry time) ──────────────────────────
FEATURES = [
    "sl_pct",          # |entry - stop| / entry premium * 100
    "strike_off",      # |strike - spot| / spot * 100
    "hour",            # entry time as decimal hour
    "vwap_dist_abs",   # |spot - vwap| / vwap * 100
    "vwap_dist_dir",   # + when spot is on the trade's side of VWAP
    "pcr_dir",         # PCR distance from 1.0 in trade direction
    "oi_imb_dir",      # OI delta imbalance in trade direction
    "oi_pe", "oi_ce",  # raw OI deltas
    "mom_dir",         # PCR momentum aligned with trade (+1 / 0 / -1)
    "sideways",        # buffer_state contains SIDEWAYS
]

# Columns that must NOT go into training (documentation / safety check)
DROP_COLUMNS = [
    # outcome / leakage
    "exit_time", "exit_price", "live_price", "actual_pnl", "result", "status",
    "updated_at", "live_price_updated_at",
    # derived from other columns
    "target_pnl", "max_loss", "target", "stop_loss", "entry_price", "quantity",
    "spot", "strike", "entry_time",
    # duplicates
    "xgboostscore", "signalscore", "confidence_score",
    # AI outputs (no predictive value) + free text
    "ai_conviction", "ai_generated", "ai_reasoning", "ai_timestamp", "ai_inference_time",
    # ids / dates (trade_date used only for CV grouping)
    "trade_id", "created_at", "trade_date",
    # scores mostly empty (fill on every trade first)
    "xgboost_score", "signal_score",
    # metadata keys
    "metadata.confidence_score", "metadata.ai_conviction", "metadata.conf_score",
    "metadata.ml_probability", "metadata.ai_generated", "metadata.ai_validated",
    "metadata.ai_provider", "metadata.ai_execution_mode", "metadata.ai_reasoning",
    "metadata.ai_reasoning_summary", "metadata.ai_key_factors", "metadata.ai_risk_flags",
    "metadata.ai_recommendation", "metadata.ai_market_bias",
    # zero importance on current sample (re-test after 500+ trades)
    "trap", "is_ce", "inst_bn", "inst_fn",
]

# ── XGBoost hyperparameters (heavily regularised for ~230 rows) ───────────────
PARAMS = dict(
    n_estimators=150, max_depth=2, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8,
    min_child_weight=8, reg_lambda=5.0, gamma=1.0,
    eval_metric="logloss", random_state=0, n_jobs=-1,
)

# Backward compat alias used by model_manager column checks
OBSERVER_FEATURE_COLUMNS = tuple(FEATURES)


# ── helpers ───────────────────────────────────────────────────────────────────
def _safe_json(val):
    """Parse JSON string or return dict as-is."""
    if isinstance(val, dict):
        return val
    if not val or (isinstance(val, float) and np.isnan(val)):
        return {}
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


# ── BATCH FEATURE BUILDER (training from CSV / Supabase DataFrame) ────────────
def build(df: pd.DataFrame) -> pd.DataFrame:
    """Build 11 direction-aware features from a trade-history DataFrame.

    Expects columns: signal, entry_price, stop_loss, strike, spot,
    trade_date, entry_time, metadata_json (str or dict with pcr, vwap,
    oi_delta_ce, oi_delta_pe, pcr_momentum, buffer_state).
    """
    m = pd.json_normalize(df.metadata_json.apply(_safe_json))
    sg = np.where(df.signal == "BUY CE", 1, -1)
    et = pd.to_datetime(
        df.trade_date.astype(str) + " " + df.entry_time.astype(str),
        format="%Y-%m-%d %I:%M:%S %p",
    )
    tot = (m.oi_delta_pe.abs() + m.oi_delta_ce.abs()).replace(0, np.nan)

    X = pd.DataFrame(index=df.index)
    X["sl_pct"] = (df.entry_price - df.stop_loss).abs() / df.entry_price * 100
    X["strike_off"] = (df.strike - df.spot).abs() / df.spot * 100
    X["hour"] = et.dt.hour + et.dt.minute / 60
    X["vwap_dist_dir"] = sg * (df.spot - m.vwap) / m.vwap * 100
    X["vwap_dist_abs"] = X.vwap_dist_dir.abs()
    X["pcr_dir"] = sg * (m.pcr - 1)
    X["oi_imb_dir"] = sg * (m.oi_delta_pe - m.oi_delta_ce) / tot
    X["oi_pe"], X["oi_ce"] = m.oi_delta_pe, m.oi_delta_ce
    up = (m.pcr_momentum == "RISING") == (sg == 1)
    X["mom_dir"] = np.where(m.pcr_momentum == "FLAT", 0, np.where(up, 1, -1))
    X["sideways"] = m.buffer_state.astype(str).str.contains("SIDEWAYS").astype(int)

    X = X[FEATURES]
    assert not set(X.columns) & set(DROP_COLUMNS), "dropped column leaked into features"
    return X


# ── LIVE SINGLE-ROW FEATURE BUILDER (real-time prediction) ────────────────────
def build_live_features(
    signal: str,
    entry_price: float,
    stop_loss: float,
    spot: float,
    strike: float,
    now: datetime.datetime,
    vwap: float,
    pcr: float,
    oi_delta_ce: float,
    oi_delta_pe: float,
    pcr_momentum: str,
    buffer_state,
) -> dict:
    """Build the same 11 features from live market data for a single trade setup."""
    sg = 1 if "CE" in str(signal).upper() else -1
    entry_price = float(entry_price or 0)
    stop_loss = float(stop_loss or 0)
    spot = float(spot or 0)
    strike = float(strike or 0)
    vwap = float(vwap or 0)
    pcr = float(pcr or 1.0)
    oi_ce_val = float(oi_delta_ce or 0)
    oi_pe_val = float(oi_delta_pe or 0)
    momentum = str(pcr_momentum or "").upper()
    buf_str = str(buffer_state or "")

    sl_pct = abs(entry_price - stop_loss) / entry_price * 100 if entry_price else 0
    strike_off = abs(strike - spot) / spot * 100 if spot else 0
    hour = now.hour + now.minute / 60.0

    vwap_dist_dir = sg * (spot - vwap) / vwap * 100 if vwap else 0
    vwap_dist_abs = abs(vwap_dist_dir)
    pcr_dir = sg * (pcr - 1)

    tot = abs(oi_pe_val) + abs(oi_ce_val)
    oi_imb_dir = sg * (oi_pe_val - oi_ce_val) / tot if tot else 0

    up = (momentum == "RISING") == (sg == 1)
    mom_dir = 0 if momentum in ("FLAT", "STABLE", "") else (1 if up else -1)

    sideways = 1 if "SIDEWAYS" in buf_str else 0

    return {
        "sl_pct": sl_pct,
        "strike_off": strike_off,
        "hour": hour,
        "vwap_dist_abs": vwap_dist_abs,
        "vwap_dist_dir": vwap_dist_dir,
        "pcr_dir": pcr_dir,
        "oi_imb_dir": oi_imb_dir,
        "oi_pe": oi_pe_val,
        "oi_ce": oi_ce_val,
        "mom_dir": mom_dir,
        "sideways": sideways,
    }


# ── LEGACY FEATURE BUILDERS (kept for historical_trainer.py) ──────────────────

def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]


def extract_features(idx: str, spot_history: list, chain_records: list, now: datetime.datetime, strategy_score: float, ai_analysis: dict = None) -> dict:
    """
    Legacy 19-feature extraction for historical replay training.
    Used by ml/historical_trainer.py — do not remove.
    """
    features = {}

    # 1. TIME FEATURES
    features['hour'] = now.hour
    features['minute'] = now.minute

    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    features['minutes_from_open'] = max(0, (now - market_open).total_seconds() / 60.0)
    features['minutes_to_close'] = max(0, (market_close - now).total_seconds() / 60.0)
    features['day_of_week'] = now.weekday()

    # 2. PRICE & TREND FEATURES
    if not spot_history:
        return None

    prices = [float(p['spot']) for p in spot_history]
    current_price = prices[-1]

    features['spot_price'] = current_price
    features['price_change_1m'] = current_price - prices[-2] if len(prices) >= 2 else 0
    features['price_change_5m'] = current_price - prices[-5] if len(prices) >= 5 else features['price_change_1m']
    features['price_change_pct_5m'] = (features['price_change_5m'] / current_price) * 100 if current_price else 0

    ema20 = calculate_ema(prices, 20)
    ema50 = calculate_ema(prices, 50)

    features['ema20'] = ema20
    features['ema50'] = ema50
    features['ema20_vs_ema50'] = ema20 - ema50
    features['dist_ema20_pct'] = ((current_price - ema20) / ema20 * 100) if ema20 else 0

    # Intraday Volatility (High - Low of last N periods)
    if len(prices) >= 10:
        recent_prices = prices[-10:]
        features['volatility_10m'] = (max(recent_prices) - min(recent_prices)) / current_price * 100
    else:
        features['volatility_10m'] = 0

    # 3. OPTIONS / OI FEATURES
    ce_oi_total = 0
    pe_oi_total = 0

    for r in chain_records:
        ce = r.get("CE", {})
        pe = r.get("PE", {})
        ce_oi = ce.get("openInterest", 0)
        pe_oi = pe.get("openInterest", 0)
        ce_oi_total += ce_oi
        pe_oi_total += pe_oi

    features['total_ce_oi'] = ce_oi_total
    features['total_pe_oi'] = pe_oi_total
    features['oi_delta'] = pe_oi_total - ce_oi_total
    features['pcr'] = pe_oi_total / ce_oi_total if ce_oi_total > 0 else 1.0

    # 4. STRATEGY FEATURES
    features['strategy_score'] = strategy_score

    # 5. AI COPILOT QUANT FEATURES
    ai_conv = 50.0
    ai_bias_val = 0.0
    ai_regime_val = 0.0
    ai_agrees_val = 0.0

    if ai_analysis and isinstance(ai_analysis, dict):
        try:
            ai_conv = float(ai_analysis.get("conviction_score", 50.0) or 50.0)
        except Exception:
            ai_conv = 50.0

        bias_str = str(ai_analysis.get("market_bias", "")).upper()
        if "BULL" in bias_str:
            ai_bias_val = 1.0
        elif "BEAR" in bias_str:
            ai_bias_val = -1.0
        else:
            ai_bias_val = 0.0

        regime_str = str(ai_analysis.get("regime", "")).lower()
        if "up" in regime_str:
            ai_regime_val = 1.0
        elif "down" in regime_str:
            ai_regime_val = -1.0
        elif "vol" in regime_str:
            ai_regime_val = 2.0
        else:
            ai_regime_val = 0.0

        rec_str = str(ai_analysis.get("recommendation", "")).upper()
        if "BUY_CE" in rec_str:
            ai_agrees_val = 1.0
        elif "BUY_PE" in rec_str:
            ai_agrees_val = -1.0
        else:
            ai_agrees_val = 0.0

    features['ai_conviction'] = ai_conv
    features['ai_bias'] = ai_bias_val
    features['ai_regime'] = ai_regime_val
    features['ai_agrees'] = ai_agrees_val

    return features
