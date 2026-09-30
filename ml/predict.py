import datetime
from config import IST, ML_ENABLED, ML_MIN_PROBABILITY, ML_FAIL_SAFE_BLOCK
from ml.feature_engineering import extract_features
from ml.model_manager import predict_probability
from analytics.ml_db import log_prediction

def evaluate_ml_signal(idx: str, signal: str, md: dict, strategy_score: float) -> tuple:
    """
    Evaluates the signal through XGBoost.
    Returns: (probability, is_allowed, message)
    """
    if not ML_ENABLED:
        return 0.0, True, "ML Disabled"
        
    now = datetime.datetime.now(IST)
    
    # Extract features
    features = extract_features(
        idx=idx,
        spot_history=md.get("spot_history", []),
        chain_records=md.get("chain_records", []),
        now=now,
        strategy_score=strategy_score
    )
    
    if not features:
        if ML_FAIL_SAFE_BLOCK:
            return 0.0, False, "XGBoost features unavailable (Fail-safe Block)"
        else:
            return 0.0, True, "XGBoost features unavailable (Allowed by Fail-safe)"
            
    # Predict
    prob = predict_probability(features)
    
    if prob < 0:
        if ML_FAIL_SAFE_BLOCK:
            return 0.0, False, "XGBoost model unavailable (Fail-safe Block)"
        else:
            return 0.0, True, "XGBoost model unavailable (Allowed by Fail-safe)"
            
    # Log prediction
    is_allowed = (prob >= ML_MIN_PROBABILITY)
    decision = "TRADE ALLOWED" if is_allowed else "FILTERED"
    
    log_prediction(
        idx=idx,
        signal=signal,
        strategy_score=strategy_score,
        features=features,
        probability=prob,
        version="v1.0",
        decision=decision
    )
    
    if is_allowed:
        return prob, True, f"ML Approved ({prob*100:.1f}% Win Probability)"
    else:
        return prob, False, f"ML Filtered ({prob*100:.1f}% < {ML_MIN_PROBABILITY*100:.1f}% minimum)"
