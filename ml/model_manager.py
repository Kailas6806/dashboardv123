import os
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from analytics.ml_db import get_training_data
from ml.feature_engineering import (
    OBSERVER_FEATURE_COLUMNS,
    observer_features_from_market,
    observer_features_from_trade,
)
from utils.logger import get_logger

logger = get_logger("ml_manager")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODELS_DIR = os.path.join(ROOT_DIR, "models")
MODEL_PATH = os.path.join(MODELS_DIR, "xgb_prod.joblib")
META_PATH = os.path.join(MODELS_DIR, "xgb_meta.json")


def load_trade_csv_samples(source):
    """Load closed trade rows as labeled observer-only model samples."""
    df = pd.read_csv(source)
    required = {"status", "actual_pnl"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Trade CSV is missing required columns: {', '.join(sorted(missing))}")

    df = df.copy()
    df["_actual_pnl"] = pd.to_numeric(df["actual_pnl"], errors="coerce")
    df = df[
        df["status"].astype(str).str.strip().str.upper().eq("CLOSED")
        & df["_actual_pnl"].notna()
    ]
    if "created_at" in df.columns:
        df["_sort_time"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df = df.sort_values("_sort_time", kind="stable", na_position="last")

    samples = []
    for row in df.to_dict("records"):
        features = observer_features_from_trade(row)
        if features is None:
            continue
        samples.append({
            "idx": row.get("instrument"),
            "dt": row.get("created_at") or row.get("trade_date") or "",
            "features": features,
            "target": int(row["_actual_pnl"] > 0),
        })
    return samples


def load_supabase_trade_samples():
    """Load closed trade records directly from Supabase PostgreSQL database."""
    try:
        from analytics.db import TradeDB
        db = TradeDB()
        trades = db.get_all_trades(status="CLOSED")
        if not trades:
            logger.warning("No closed trades returned from Supabase.")
            return []

        sorted_trades = sorted(
            trades,
            key=lambda t: str(t.get("created_at") or t.get("Entry Time") or t.get("trade_date") or ""),
        )

        samples = []
        for t in sorted_trades:
            pnl = t.get("Actual P&L ₹", t.get("actual_pnl"))
            if pnl is None:
                continue
            try:
                pnl_val = float(pnl)
            except (ValueError, TypeError):
                continue
            feats = observer_features_from_trade(t)
            if feats:
                samples.append({
                    "idx": t.get("instrument") or t.get("Index"),
                    "dt": str(t.get("created_at") or t.get("Entry Time") or t.get("trade_date") or ""),
                    "features": feats,
                    "target": int(pnl_val > 0),
                })
        logger.info("Loaded %d closed trade samples from Supabase database.", len(samples))
        return samples
    except Exception as exc:
        logger.error(f"Failed to fetch trade samples from Supabase: {exc}")
        return []


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

def train_model(custom_data=None, training_source="supabase"):
    """
    Trains XGBoost using a chronological 80/20 holdout validation.
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
        # Default: Directly fetch closed trades from Supabase Database
        samples = load_supabase_trade_samples()
        if len(samples) >= 20:
            df = pd.DataFrame(samples)
            training_source = "supabase_db"
        else:
            # Fallback to ml_predictions if trade table is empty
            data = get_training_data()
            if len(data) >= 20:
                df = pd.DataFrame(data)
                training_source = "supabase_predictions"
            else:
                logger.warning(f"Not enough training data in Supabase. Got {len(samples)} closed trades.")
                return False, {"error": f"Insufficient data in Supabase ({len(samples)} closed trades, minimum 20 required)"}

    if 'features' in df.columns:
        features_df = pd.json_normalize(df['features'])
    else:
        # Features might be direct columns except 'target'
        features_df = df.drop(columns=[c for c in ['target', 'idx', 'signal', 'timestamp', 'id', 'dt'] if c in df.columns])

    X = features_df
    y = df['target'].astype(int)

    if len(X) < 20:
        return False, {"error": f"Insufficient samples ({len(X)} samples, minimum 20 required)"}

    if training_source in ("trade_csv", "supabase_db"):
        X = X.reindex(columns=OBSERVER_FEATURE_COLUMNS, fill_value=0.0)
    X = X.apply(pd.to_numeric, errors="coerce")
    X = X.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
    y = y.astype(int)
    if y.nunique() != 2:
        return False, {"error": "Training requires both winning and losing trade samples."}

    # Train test split (chronological Walk-Forward)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    if y_train.nunique() != 2:
        return False, {"error": "Chronological training split must contain both outcome classes."}

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
        "training_source": training_source,
        "positive_samples": int(y.sum()),
        "negative_samples": int(len(y) - y.sum()),
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
        expected_cols = getattr(model, "feature_names_in_", OBSERVER_FEATURE_COLUMNS)
        missing_cols = [col for col in expected_cols if col not in features]
        if missing_cols:
            logger.warning(
                "Loaded XGBoost model is incompatible with live observer features; missing %s",
                ", ".join(missing_cols),
            )
            return -1.0
        for col in expected_cols:
            if col not in df.columns:
                df[col] = 0.0
                
        df = df[expected_cols]
        classes = list(model.classes_)
        if 1 not in classes:
            return -1.0
        positive_class_index = classes.index(1)
        prob = model.predict_proba(df)[0][positive_class_index]
        return float(prob)
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        return -1.0


def predict_live_observer_probability(
    idx,
    signal,
    market_data,
    now,
    confidence_score,
    ai_analysis=None,
):
    """Return a live probability only for a compatible CSV-trained observer model."""
    metadata = get_model_metadata() or {}
    if metadata.get("training_source") not in ("trade_csv", "supabase_db", "supabase"):
        return None
    if metadata.get("features") != list(OBSERVER_FEATURE_COLUMNS):
        logger.warning("Live observer model feature schema does not match the current schema.")
        return None

    features = observer_features_from_market(
        idx,
        signal,
        market_data,
        now,
        confidence_score,
        ai_analysis=ai_analysis,
    )
    if features is None:
        logger.warning("Live observer features are unavailable for signal %s.", signal)
        return None

    probability = predict_probability(features)
    return probability if probability >= 0.0 else None
