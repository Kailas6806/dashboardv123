import os
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from analytics.ml_db import get_training_data
from utils.logger import get_logger

logger = get_logger("ml_manager")

MODELS_DIR = "models"
MODEL_PATH = os.path.join(MODELS_DIR, "xgb_prod.joblib")

def train_model():
    """Fetches data from Supabase, trains XGBoost using Walk-Forward validation, and saves the model."""
    data = get_training_data()
    if len(data) < 50:
        logger.warning(f"Not enough data to train. Need at least 50 samples, got {len(data)}")
        return False, {"error": f"Insufficient data ({len(data)} samples)"}
        
    # Convert JSON features back to DataFrame columns
    df = pd.DataFrame(data)
    features_df = pd.json_normalize(df['features'])
    
    X = features_df
    y = df['target']
    
    # Train test split (chronological)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    # Simple conservative XGBoost
    model = XGBClassifier(
        n_estimators=50,      # fewer trees for speed
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=1,            # single thread to avoid overhead
        tree_method='hist'   # faster histogram algorithm
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    metrics = {
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "samples": len(df),
        "win_rate": y.mean()
    }
    
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)
        
    joblib.dump(model, MODEL_PATH, compress=3)
    logger.info(f"Model trained and saved. Metrics: {metrics}")
    
    return True, metrics

_cached_model = None

def get_model():
    """Loads the production model with caching for performance."""
    global _cached_model
    if _cached_model is not None:
        return _cached_model
        
    if os.path.exists(MODEL_PATH):
        try:
            _cached_model = joblib.load(MODEL_PATH)
            return _cached_model
        except Exception as e:
            logger.error(f"Failed to load ML model: {e}")
            return None
    return None

def predict_probability(features: dict) -> float:
    """Predicts the probability of success for a given feature dictionary."""
    model = get_model()
    if model is None:
        return -1.0  # Indicates model unavailable
        
    try:
        df = pd.DataFrame([features])
        # Ensure column order matches training
        expected_cols = model.feature_names_in_
        for col in expected_cols:
            if col not in df.columns:
                df[col] = 0.0
                
        df = df[expected_cols]
        prob = model.predict_proba(df)[0][1] # Probability of class 1
        return float(prob)
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        return -1.0
