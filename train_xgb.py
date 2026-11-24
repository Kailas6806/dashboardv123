"""XGBClassifier: predict Win (actual_pnl > 0) vs Loss from ENTRY-TIME features only.

Usage:
  Supabase : export SUPABASE_URL=... SUPABASE_KEY=...   (service-role or read key)
             python train_xgb.py                         # reads table "trades"
             SUPABASE_TABLE=my_table python train_xgb.py
  CSV      : python train_xgb.py trades_export.csv
Requires: pip install xgboost scikit-learn pandas
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import roc_auc_score, brier_score_loss

warnings.filterwarnings("ignore")

# 10 features kept (all known at entry time)
FEATURES = [
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

# Columns that must NOT go into training (kept here as documentation / safety check)
DROP_COLUMNS = [
    # outcome / leakage
    "exit_time", "exit_price", "live_price", "actual_pnl", "result", "status",
    "updated_at", "live_price_updated_at",
    # derived from other columns
    "target_pnl", "max_loss", "target", "stop_loss", "sl_pct", "entry_price", "quantity",  # stop/target are trailed after entry -> leak
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

PARAMS = dict(          # heavily regularised: ~230 rows is tiny
    n_estimators=150, max_depth=2, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8,
    min_child_weight=8, reg_lambda=5.0, gamma=1.0,
    eval_metric="logloss", random_state=0, n_jobs=-1,
)


def load_trades(path: str | None = None) -> pd.DataFrame:
    """Load closed trades from a CSV path, or from Supabase when no path is given."""
    if path:
        return pd.read_csv(path)

    # 1. Check if SUPABASE_URL and SUPABASE_KEY are provided
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        try:
            from supabase import create_client
            sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
            table, rows, start, page = os.environ.get("SUPABASE_TABLE", "trades"), [], 0, 1000
            while True:  # page through results (Supabase caps rows per request)
                res = (
                    sb.table(table)
                    .select("*")
                    .not_.is_("actual_pnl", "null")
                    .order("created_at")
                    .range(start, start + page - 1)
                    .execute()
                )
                rows += res.data
                if len(res.data) < page:
                    break
                start += page
            return pd.DataFrame(rows)
        except Exception as e:
            print(f"[!] supabase-py client load failed ({e}), trying PostgreSQL TradeDB connection...")

    # 2. Direct Supabase PostgreSQL connection using SUPABASE_URI (from secrets.toml / env)
    try:
        from ml.model_manager import _load_supabase_dataframe
        df = _load_supabase_dataframe()
        if not df.empty:
            return df
    except Exception as e:
        print(f"[!] Supabase PostgreSQL load failed ({e})")

    # 3. Fallback: local CSV if available
    local_csv = os.path.join(os.path.dirname(__file__), "trades_rows.csv")
    if os.path.exists(local_csv):
        print(f"[*] Falling back to local CSV: {local_csv}")
        return pd.read_csv(local_csv)

    raise RuntimeError("Could not load trades from Supabase or CSV. Please provide a CSV path or check credentials.")


def _meta(v):
    if isinstance(v, dict):
        return v
    if not v or (isinstance(v, float) and np.isnan(v)):
        return {}
    try:
        return json.loads(v)  # jsonb arrives as dict, text as str
    except (TypeError, ValueError):
        return {}


def build(df: pd.DataFrame) -> pd.DataFrame:
    m = pd.json_normalize(df.metadata_json.apply(_meta))
    sg = np.where(df.signal == "BUY CE", 1, -1)
    et = pd.to_datetime(
        df.trade_date.astype(str) + " " + df.entry_time.astype(str),
        format="%Y-%m-%d %I:%M:%S %p",
        errors="coerce",
    )
    tot = (m.oi_delta_pe.abs() + m.oi_delta_ce.abs()).replace(0, np.nan)
    X = pd.DataFrame(index=df.index)
    X["strike_off"] = (df.strike.astype(float) - df.spot.astype(float)).abs() / df.spot.astype(float) * 100
    X["hour"] = et.dt.hour + et.dt.minute / 60
    vwap = m.get("vwap", pd.Series(np.nan, index=df.index)).astype(float)
    pcr = m.get("pcr", pd.Series(1.0, index=df.index)).astype(float)
    oi_pe = m.get("oi_delta_pe", pd.Series(0.0, index=df.index)).astype(float)
    oi_ce = m.get("oi_delta_ce", pd.Series(0.0, index=df.index)).astype(float)
    pcr_mom = m.get("pcr_momentum", pd.Series("", index=df.index)).astype(str)
    buf_state = m.get("buffer_state", pd.Series("", index=df.index)).astype(str)

    X["vwap_dist_dir"] = sg * (df.spot.astype(float) - vwap) / vwap * 100
    X["vwap_dist_abs"] = X.vwap_dist_dir.abs()
    X["pcr_dir"] = sg * (pcr - 1)
    X["oi_imb_dir"] = sg * (oi_pe - oi_ce) / tot
    X["oi_pe"], X["oi_ce"] = oi_pe, oi_ce
    up = (pcr_mom == "RISING") == (sg == 1)
    X["mom_dir"] = np.where(pcr_mom == "FLAT", 0, np.where(up, 1, -1))
    X["sideways"] = buf_state.str.contains("SIDEWAYS").astype(int)
    X = X[FEATURES]
    assert not set(X.columns) & set(DROP_COLUMNS), "dropped column leaked into features"
    return X


def main(path: str | None = None):
    df = load_trades(path)
    if "actual_pnl" in df.columns:
        df["actual_pnl"] = pd.to_numeric(df["actual_pnl"], errors="coerce")
    df = df[df.actual_pnl.notna()].reset_index(drop=True)
    X, y, days = build(df), (df.actual_pnl > 0).astype(int).values, df.trade_date.values

    # Clean any NaN/Inf
    X = X.apply(pd.to_numeric, errors="coerce")
    X = X.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)

    # Leave-one-day-out CV: each prediction comes from a model that never saw that day
    oof = np.full(len(y), 0.5)
    for tr, te in LeaveOneGroupOut().split(X, y, days):
        if len(np.unique(y[tr])) < 2:
            continue
        clf = XGBClassifier(**PARAMS).fit(X.iloc[tr], y[tr])
        oof[te] = clf.predict_proba(X.iloc[te])[:, 1]
    print(f"Trades: {len(y)} | win rate: {y.mean():.1%}")
    print(f"OOF AUC: {roc_auc_score(y, oof):.3f} (0.5 = no skill) | Brier: {brier_score_loss(y, oof):.3f}")

    # Expected-value filter: trade only if p > break-even win rate
    w = df.actual_pnl[df.actual_pnl > 0].mean() if (df.actual_pnl > 0).any() else 0.0
    l = -df.actual_pnl[df.actual_pnl <= 0].mean() if (df.actual_pnl <= 0).any() else 0.0
    be = l / (w + l) if (w + l) > 0 else 0.5
    print(f"Avg win {w:.0f} / avg loss {l:.0f} -> break-even win prob {be:.1%}")
    for thr in (be, 0.45, 0.50):
        k = oof >= thr
        if k.sum():
            print(f"  p>={thr:.2f}: n={k.sum():3d} pnl={df.actual_pnl[k].sum():9.0f} "
                  f"win={y[k].mean():.1%} exp/trade={df.actual_pnl[k].mean():6.0f}")
    print(f"  all trades: n={len(y)} pnl={df.actual_pnl.sum():.0f}")

    final = XGBClassifier(**PARAMS).fit(X, y)
    imp = pd.Series(final.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print("\nFeature importance:\n", imp.round(3).to_string())

    # 1. Save standalone model file
    final.save_model("xgb_win_model.json")
    print("\n[+] Model saved to xgb_win_model.json")

    # 2. Update production models/ directory for the dashboard live observer
    models_dir = os.path.join(os.path.dirname(__file__), "models")
    os.makedirs(models_dir, exist_ok=True)
    import joblib
    joblib.dump(final, os.path.join(models_dir, "xgb_prod.joblib"), compress=3)
    final.save_model(os.path.join(models_dir, "xgb_win_model.json"))

    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    y_pred_oof = (oof >= 0.5).astype(int)
    threshold_analysis = {}
    for thr in (be, 0.45, 0.50):
        mask = oof >= thr
        if mask.sum() > 0:
            threshold_analysis[f"p>={thr:.2f}"] = {
                "trades": int(mask.sum()),
                "pnl": float(df.actual_pnl[mask].sum()),
                "win_rate": float(y[mask].mean()),
                "avg_pnl": float(df.actual_pnl[mask].mean()),
            }

    meta = {
        "oof_auc": float(roc_auc_score(y, oof)),
        "oof_brier": float(brier_score_loss(y, oof)),
        "accuracy": float(accuracy_score(y, y_pred_oof)),
        "precision": float(precision_score(y, y_pred_oof, zero_division=0)),
        "recall": float(recall_score(y, y_pred_oof, zero_division=0)),
        "f1": float(f1_score(y, y_pred_oof, zero_division=0)),
        "samples": int(len(df)),
        "win_rate": float(y.mean()),
        "positive_samples": int(y.sum()),
        "negative_samples": int(len(y) - y.sum()),
        "avg_win": float(w),
        "avg_loss": float(l),
        "break_even_threshold": round(float(be), 3),
        "threshold_analysis": threshold_analysis,
        "training_source": "supabase_db" if path is None else "trade_csv",
        "trained_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "features": list(FEATURES),
        "feature_importances": {k: round(float(v), 4) for k, v in imp.items()},
        "cv_method": "leave_one_day_out",
    }
    with open(os.path.join(models_dir, "xgb_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print("[+] Updated models/xgb_prod.joblib and models/xgb_meta.json for dashboard live observer.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
