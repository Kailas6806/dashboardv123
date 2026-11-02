"""
V12 PRO MAX — XGBoost Model Manager.

Trains with Leave-One-Day-Out CV, evaluates AUC / Brier / break-even,
and serves live win-probability predictions using 11 direction-aware features.
"""
import os
import json
import datetime
import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import (
    roc_auc_score, brier_score_loss,
    accuracy_score, precision_score, recall_score, f1_score,
)
from ml.feature_engineering import FEATURES, PARAMS, build, build_live_features
from utils.logger import get_logger

logger = get_logger("ml_manager")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODELS_DIR = os.path.join(ROOT_DIR, "models")
MODEL_PATH = os.path.join(MODELS_DIR, "xgb_prod.joblib")
META_PATH = os.path.join(MODELS_DIR, "xgb_meta.json")

_cached_model = None


# ── Metadata ──────────────────────────────────────────────────────────────────
def get_model_metadata():
    """Returns metadata about the currently trained model."""
    if os.path.exists(META_PATH):
        try:
            with open(META_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load model metadata: %s", e)
    return None


# ── Data loading ──────────────────────────────────────────────────────────────
def _load_supabase_dataframe() -> pd.DataFrame:
    """Fetch all closed trades directly from Supabase PostgreSQL as a DataFrame."""
    try:
        from analytics.db import TradeDB
        from psycopg2.extras import RealDictCursor
        db = TradeDB()
        conn = db._get_connection()
        if not conn:
            logger.warning("No connection to Supabase database.")
            return pd.DataFrame()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT * FROM trades WHERE status = %s AND actual_pnl IS NOT NULL ORDER BY trade_date ASC, entry_time ASC",
                ("CLOSED",),
            )
            rows = cur.fetchall()
            if not rows:
                logger.warning("No closed trades returned from Supabase trades table.")
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            for col in ("entry_price", "stop_loss", "strike", "spot", "actual_pnl"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df[df.actual_pnl.notna()].reset_index(drop=True)
            logger.info("Loaded %d closed trades directly from Supabase PostgreSQL.", len(df))
            return df
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Failed to fetch trades from Supabase PostgreSQL: %s", exc)
        return pd.DataFrame()


def load_trade_csv_samples(source):
    """Backward-compat wrapper: load CSV and return list of {features, target} dicts."""
    df = pd.read_csv(source)
    df["actual_pnl"] = pd.to_numeric(df.get("actual_pnl"), errors="coerce")
    df = df[df.actual_pnl.notna()].reset_index(drop=True)
    if df.empty:
        return []
    try:
        X = build(df)
    except Exception:
        return []
    y = (df.actual_pnl > 0).astype(int)
    samples = []
    for i in range(len(df)):
        samples.append({"features": X.iloc[i].to_dict(), "target": int(y.iloc[i])})
    return samples


# ── Training ──────────────────────────────────────────────────────────────────
def train_model(custom_data=None, training_source="supabase"):
    """
    Train XGBoost using Leave-One-Day-Out CV with 11 direction-aware features.

    custom_data: DataFrame, CSV file path (str), or None (fetches from Supabase).
    Returns: (success: bool, metrics: dict)
    """
    global _cached_model

    # 1. Load data
    if custom_data is not None:
        if isinstance(custom_data, str):
            df = pd.read_csv(custom_data)
        elif isinstance(custom_data, pd.DataFrame):
            df = custom_data.copy()
        else:
            df = pd.DataFrame(custom_data)
    else:
        df = _load_supabase_dataframe()
        if len(df) >= 20:
            training_source = "supabase_db"
        else:
            # Fallback: try legacy ml_predictions table
            try:
                from analytics.ml_db import get_training_data
                data = get_training_data()
                if len(data) >= 20:
                    df = pd.DataFrame(data)
                    training_source = "supabase_predictions"
                else:
                    return False, {
                        "error": f"Insufficient data ({len(df)} closed trades, minimum 20 required)"
                    }
            except Exception:
                return False, {
                    "error": f"Insufficient data ({len(df)} closed trades, minimum 20 required)"
                }

    # Ensure numeric actual_pnl and filter
    if "actual_pnl" in df.columns:
        df["actual_pnl"] = pd.to_numeric(df["actual_pnl"], errors="coerce")
        df = df[df.actual_pnl.notna()].reset_index(drop=True)

    if len(df) < 20:
        return False, {"error": f"Insufficient samples ({len(df)}, minimum 20 required)"}

    # 2. Build features
    try:
        X = build(df)
    except Exception as e:
        logger.error("Feature build failed: %s", e, exc_info=True)
        return False, {"error": f"Feature engineering failed: {e}"}

    y = (df.actual_pnl > 0).astype(int).values

    if len(np.unique(y)) != 2:
        return False, {"error": "Training requires both winning and losing trade samples."}

    # Handle NaN/Inf in features
    X = X.apply(pd.to_numeric, errors="coerce")
    X = X.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)

    # 3. Leave-One-Day-Out CV
    days = df.trade_date.values if "trade_date" in df.columns else np.arange(len(df))
    unique_days = len(np.unique(days))

    oof = np.full(len(y), 0.5)  # default 0.5 for un-evaluated folds
    cv_method = "leave_one_day_out"

    if unique_days >= 3:
        for tr, te in LeaveOneGroupOut().split(X, y, days):
            # Skip fold if training set has only one class
            if len(np.unique(y[tr])) < 2:
                continue
            clf = XGBClassifier(**PARAMS).fit(X.iloc[tr], y[tr])
            oof[te] = clf.predict_proba(X.iloc[te])[:, 1]
        oof_auc = float(roc_auc_score(y, oof))
        oof_brier = float(brier_score_loss(y, oof))
    else:
        # Fallback: 80/20 chronological split if too few days
        cv_method = "chronological_80_20"
        split = int(len(X) * 0.8)
        X_tr, X_te = X.iloc[:split], X.iloc[split:]
        y_tr, y_te = y[:split], y[split:]
        if len(np.unique(y_tr)) >= 2 and len(X_te) > 0:
            clf = XGBClassifier(**PARAMS).fit(X_tr, y_tr)
            oof[split:] = clf.predict_proba(X_te)[:, 1]
            oof_auc = float(roc_auc_score(y_te, oof[split:])) if len(np.unique(y_te)) == 2 else 0.5
            oof_brier = float(brier_score_loss(y_te, oof[split:]))
        else:
            oof_auc = 0.5
            oof_brier = 0.25

    # 4. Break-even analysis
    wins_pnl = df.actual_pnl[df.actual_pnl > 0]
    losses_pnl = df.actual_pnl[df.actual_pnl <= 0]
    avg_win = float(wins_pnl.mean()) if len(wins_pnl) > 0 else 0
    avg_loss = float(-losses_pnl.mean()) if len(losses_pnl) > 0 else 0
    break_even = avg_loss / (avg_win + avg_loss) if (avg_win + avg_loss) > 0 else 0.5

    # Threshold analysis
    threshold_analysis = {}
    for thr in (break_even, 0.45, 0.50):
        mask = oof >= thr
        if mask.sum() > 0:
            threshold_analysis[f"p>={thr:.2f}"] = {
                "trades": int(mask.sum()),
                "pnl": float(df.actual_pnl[mask].sum()),
                "win_rate": float(y[mask].mean()),
                "avg_pnl": float(df.actual_pnl[mask].mean()),
            }

    # 5. Train final model on ALL data
    final_model = XGBClassifier(**PARAMS).fit(X, y)

    # Feature importances
    imp = pd.Series(final_model.feature_importances_, index=FEATURES).sort_values(ascending=False)
    feat_imp_dict = {k: round(float(v), 4) for k, v in imp.items()}

    # Hard classification metrics from OOF predictions
    y_pred_oof = (oof >= 0.5).astype(int)

    metrics = {
        "oof_auc": oof_auc,
        "oof_brier": oof_brier,
        "accuracy": float(accuracy_score(y, y_pred_oof)),
        "precision": float(precision_score(y, y_pred_oof, zero_division=0)),
        "recall": float(recall_score(y, y_pred_oof, zero_division=0)),
        "f1": float(f1_score(y, y_pred_oof, zero_division=0)),
        "samples": int(len(df)),
        "win_rate": float(y.mean()),
        "positive_samples": int(y.sum()),
        "negative_samples": int(len(y) - y.sum()),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "break_even_threshold": round(break_even, 3),
        "threshold_analysis": threshold_analysis,
        "training_source": training_source,
        "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "features": list(FEATURES),
        "feature_importances": feat_imp_dict,
        "cv_method": cv_method,
    }

    # 6. Save
    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(final_model, MODEL_PATH, compress=3)
    _cached_model = final_model

    with open(META_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    logger.info(
        "Model trained. AUC=%.3f Brier=%.3f Break-even=%.1f%%",
        oof_auc, oof_brier, break_even * 100,
    )
    return True, metrics


# ── Inference ─────────────────────────────────────────────────────────────────
def get_model():
    """Load the production model with caching."""
    global _cached_model
    if _cached_model is not None:
        return _cached_model
    if os.path.exists(MODEL_PATH):
        try:
            _cached_model = joblib.load(MODEL_PATH)
            return _cached_model
        except Exception as e:
            logger.error("Failed to load ML model: %s", e)
            return None
    return None


def predict_probability(features: dict) -> float:
    """Predict win probability from a feature dictionary (11 features)."""
    model = get_model()
    if model is None:
        return -1.0

    try:
        df = pd.DataFrame([features])
        # Ensure correct column order
        for col in FEATURES:
            if col not in df.columns:
                df[col] = 0.0
        df = df[FEATURES]
        df = df.apply(pd.to_numeric, errors="coerce")
        df = df.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)

        classes = list(model.classes_)
        if 1 not in classes:
            return -1.0
        pos_idx = classes.index(1)
        prob = model.predict_proba(df)[0][pos_idx]
        return float(prob)
    except Exception as e:
        logger.error("Prediction failed: %s", e)
        return -1.0


def predict_live_observer_probability(
    idx, signal, market_data, now, confidence_score,
    entry_price=None, stop_loss=None, buffer_state=None,
    ai_analysis=None,
):
    """Return live win probability using the 11-feature observer model."""
    metadata = get_model_metadata() or {}
    if metadata.get("features") != list(FEATURES):
        # Model was trained with a different feature schema
        if metadata.get("features"):
            logger.debug("Model feature schema mismatch: expected %s", FEATURES)
        return None

    if signal not in ("BUY CE", "BUY PE"):
        return None
    if entry_price is None or stop_loss is None:
        logger.debug("Cannot compute XGBoost features: missing entry_price or stop_loss")
        return None

    spot = market_data.get("spot", 0)
    features = build_live_features(
        signal=signal,
        entry_price=entry_price,
        stop_loss=stop_loss,
        spot=spot,
        strike=market_data.get("atm_actual", 0),
        now=now,
        vwap=market_data.get("vwap_proxy", 0),
        pcr=market_data.get("pcr", 1.0),
        oi_delta_ce=market_data.get("total_ce_delta", 0),
        oi_delta_pe=market_data.get("total_pe_delta", 0),
        pcr_momentum=market_data.get("pcr_momentum", ""),
        buffer_state=buffer_state,
    )

    probability = predict_probability(features)
    return probability if probability >= 0.0 else None
