import numpy as np
import pandas as pd
import datetime

def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

def extract_features(idx: str, spot_history: list, chain_records: list, now: datetime.datetime, strategy_score: float) -> dict:
    """
    Extracts features for XGBoost prediction based on current market state.
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
    
    return features
