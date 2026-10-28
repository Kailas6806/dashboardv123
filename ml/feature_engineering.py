import numpy as np
import pandas as pd
import datetime
import json

from config import IST


OBSERVER_FEATURE_COLUMNS = (
    "idx_nifty",
    "idx_banknifty",
    "idx_finnifty",
    "signal_is_ce",
    "hour",
    "minute",
    "day_of_week",
    "spot_price",
    "strike_distance_pct",
    "entry_price",
    "confidence_score",
    "pcr",
    "vwap_distance_pct",
    "oi_delta_ce",
    "oi_delta_pe",
    "ai_generated",
    "ai_conviction",
    "ai_bias",
    "ai_agrees",
    "pcr_momentum",
    "trap_detected",
)


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if np.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _parse_metadata(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _boolean(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None or pd.isna(value):
        return False
    return bool(value)


def _trade_datetime(trade):
    created_at = trade.get("created_at") or trade.get("recorded_at")
    if created_at:
        try:
            parsed = datetime.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            return parsed.astimezone(IST) if parsed.tzinfo else parsed.replace(tzinfo=IST)
        except (TypeError, ValueError, OverflowError):
            pass

    date_text = str(trade.get("trade_date") or trade.get("date") or "")
    time_text = str(trade.get("entry_time") or trade.get("Entry Time") or "")
    for time_format in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.datetime.strptime(time_text.strip(), time_format).time()
            parsed_date = datetime.date.fromisoformat(date_text[:10])
            return datetime.datetime.combine(parsed_date, parsed_time, tzinfo=IST)
        except (TypeError, ValueError):
            continue
    return datetime.datetime.now(IST)


def _build_observer_features(
    idx,
    signal,
    spot,
    strike,
    entry_price,
    now,
    confidence_score,
    pcr,
    vwap,
    oi_delta_ce,
    oi_delta_pe,
    ai_generated,
    ai_conviction,
    ai_bias,
    ai_recommendation,
    pcr_momentum,
    trap,
):
    spot_value = _number(spot)
    vwap_value = _number(vwap)
    strike_value = _number(strike)
    recommendation = str(ai_recommendation or "").upper().replace(" ", "_")
    bias = str(ai_bias or "").upper()
    momentum = str(pcr_momentum or "").upper()
    signal_text = str(signal or "").upper()
    if "BUY_CE" in recommendation:
        ai_agrees = 1.0 if "CE" in signal_text else -1.0 if "PE" in signal_text else 0.0
    elif "BUY_PE" in recommendation:
        ai_agrees = 1.0 if "PE" in signal_text else -1.0 if "CE" in signal_text else 0.0
    else:
        ai_agrees = 0.0

    return {
        "idx_nifty": float(str(idx).upper() == "NIFTY"),
        "idx_banknifty": float(str(idx).upper() == "BANKNIFTY"),
        "idx_finnifty": float(str(idx).upper() == "FINNIFTY"),
        "signal_is_ce": float("CE" in signal_text),
        "hour": float(now.hour),
        "minute": float(now.minute),
        "day_of_week": float(now.weekday()),
        "spot_price": spot_value,
        "strike_distance_pct": ((strike_value - spot_value) / spot_value * 100.0) if spot_value else 0.0,
        "entry_price": _number(entry_price),
        "confidence_score": _number(confidence_score),
        "pcr": _number(pcr, 1.0),
        "vwap_distance_pct": ((spot_value - vwap_value) / spot_value * 100.0) if spot_value else 0.0,
        "oi_delta_ce": _number(oi_delta_ce),
        "oi_delta_pe": _number(oi_delta_pe),
        "ai_generated": float(_boolean(ai_generated)),
        "ai_conviction": _number(ai_conviction, 50.0),
        "ai_bias": 1.0 if "BULL" in bias else (-1.0 if "BEAR" in bias else 0.0),
        "ai_agrees": ai_agrees,
        "pcr_momentum": 1.0 if momentum == "RISING" else (-1.0 if momentum == "FALLING" else 0.0),
        "trap_detected": float(bool(trap) and str(trap).upper() != "NONE"),
    }


def observer_features_from_trade(trade):
    """Build entry-time observer features from a row in the trade-history CSV."""
    metadata = _parse_metadata(trade.get("metadata_json") or trade.get("signal_metadata"))
    spot = trade.get("spot", trade.get("Spot"))
    entry_price = trade.get("entry_price", trade.get("Entry Price"))
    if spot is None or entry_price is None:
        return None

    return _build_observer_features(
        idx=trade.get("instrument") or trade.get("Index", ""),
        signal=trade.get("signal") or trade.get("Signal", ""),
        spot=spot,
        strike=trade.get("strike", trade.get("Strike")),
        entry_price=entry_price,
        now=_trade_datetime(trade),
        confidence_score=trade.get("confidence_score", trade.get("Confidence Score")),
        pcr=metadata.get("pcr"),
        vwap=metadata.get("vwap"),
        oi_delta_ce=metadata.get("oi_delta_ce"),
        oi_delta_pe=metadata.get("oi_delta_pe"),
        ai_generated=trade.get("ai_generated", trade.get("_ai_generated", False)),
        ai_conviction=trade.get("ai_conviction", trade.get("_ai_conviction", metadata.get("ai_conviction", 50.0))),
        ai_bias=metadata.get("ai_market_bias") or metadata.get("market_bias"),
        ai_recommendation=metadata.get("ai_recommendation") or metadata.get("recommendation"),
        pcr_momentum=metadata.get("pcr_momentum"),
        trap=metadata.get("trap"),
    )


def observer_features_from_market(
    idx,
    signal,
    market_data,
    now,
    confidence_score,
    ai_analysis=None,
):
    """Build the same entry-time features for a live, non-blocking observation."""
    if signal not in ("BUY CE", "BUY PE"):
        return None
    ai_analysis = ai_analysis if isinstance(ai_analysis, dict) else {}
    atm_row = market_data.get("atm_row")
    option_column = "CE LTP" if signal == "BUY CE" else "PE LTP"
    if hasattr(atm_row, "get"):
        entry_price = atm_row.get(option_column, 0)
    else:
        entry_price = 0

    return _build_observer_features(
        idx=idx,
        signal=signal,
        spot=market_data.get("spot"),
        strike=market_data.get("atm_actual"),
        entry_price=entry_price,
        now=now,
        confidence_score=confidence_score,
        pcr=market_data.get("pcr"),
        vwap=market_data.get("vwap_proxy"),
        oi_delta_ce=market_data.get("total_ce_delta"),
        oi_delta_pe=market_data.get("total_pe_delta"),
        ai_generated=ai_analysis.get("provider") is not None,
        ai_conviction=ai_analysis.get("conviction_score", 50.0),
        ai_bias=ai_analysis.get("market_bias"),
        ai_recommendation=ai_analysis.get("recommendation"),
        pcr_momentum=market_data.get("pcr_momentum"),
        trap=market_data.get("trap"),
    )

def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

def extract_features(idx: str, spot_history: list, chain_records: list, now: datetime.datetime, strategy_score: float, ai_analysis: dict = None) -> dict:
    """
    Extracts features for XGBoost prediction based on current market state and AI Copilot verdict.
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
