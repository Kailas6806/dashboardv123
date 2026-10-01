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

META_PATH = os.path.join(MODELS_DIR, "xgb_meta.json")

def get_model_metadata():
    """Returns metadata about the currently trained model."""
    if os.path.exists(META_PATH):
        try:
            import json
            with open(META_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load model metadata: {e}")
    return None

def train_model(custom_data=None):
    """
    Trains XGBoost using Walk-Forward chronological validation.
    Accepts custom_data (list of dicts or DataFrame with 'features' and 'target')
    or fetches from Supabase.
    """
    global _cached_model
    import datetime
    import json
    
    if custom_data is not None:
        if isinstance(custom_data, pd.DataFrame):
            df = custom_data.copy()
        else:
            df = pd.DataFrame(custom_data)
    else:
        data = get_training_data()
        if len(data) < 50:
            logger.warning(f"Not enough data to train. Need at least 50 samples, got {len(data)}")
            return False, {"error": f"Insufficient data ({len(data)} samples, minimum 50 required)"}
        df = pd.DataFrame(data)

    if 'features' in df.columns:
        features_df = pd.json_normalize(df['features'])
    else:
        # Features might be direct columns except 'target'
        features_df = df.drop(columns=[c for c in ['target', 'idx', 'signal', 'timestamp', 'id', 'dt'] if c in df.columns])

    X = features_df
    y = df['target'].astype(int)

    if len(X) < 20:
        return False, {"error": f"Insufficient samples ({len(X)} samples, minimum 20 required)"}

    # Train test split (chronological Walk-Forward)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # Optimized conservative XGBoost
    model = XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=1,
        tree_method='hist'
    )

    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1] if len(X_test) > 0 else []

    # Calculate feature importances
    feat_names = list(X.columns)
    importances = model.feature_importances_.tolist()
    feat_imp = sorted(zip(feat_names, importances), key=lambda x: x[1], reverse=True)
    feat_imp_dict = {k: round(v, 4) for k, v in feat_imp}

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "samples": int(len(df)),
        "train_samples": int(len(X_train)),
        "test_samples": int(len(X_test)),
        "win_rate": float(y.mean()),
        "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "features": feat_names,
        "feature_importances": feat_imp_dict
    }

    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)

    joblib.dump(model, MODEL_PATH, compress=3)
    _cached_model = model

    with open(META_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

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
