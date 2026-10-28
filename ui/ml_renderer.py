import io
import os
import pandas as pd
import streamlit as st

from ml.model_manager import (
    get_model,
    get_model_metadata,
    load_trade_csv_samples,
    train_model,
    MODEL_PATH,
)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_CSV_PATH = os.path.join(ROOT_DIR, "trades_rows.csv")


def render_ml_dashboard():
    st.markdown(
        "<h3 style='color:#34D399;'>🤖 XGBOOST LIVE OBSERVER</h3>",
        unsafe_allow_html=True,
    )
    st.info(
        "Evaluation only: live probabilities are displayed for confirmed signals on trade cards. "
        "XGBoost filters false breakouts and evaluates quantitative setup win probability."
    )

    metadata = get_model_metadata() or {}
    model = get_model()
    observer_ready = bool(
        model is not None
        and metadata.get("training_source") == "trade_csv"
    )

    status_col, samples_col, trained_col = st.columns(3)
    with status_col:
        st.metric("Observer Model", "READY" if observer_ready else "NEEDS CSV TRAINING")
    with samples_col:
        st.metric("Closed Trade Samples", metadata.get("samples", "—"))
    with trained_col:
        st.metric("Last Trained", metadata.get("trained_at", "—"))

    if metadata.get("training_source") == "trade_csv":
        metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
        with metrics_col1:
            st.metric("Holdout Accuracy", f"{metadata.get('accuracy', 0) * 100:.1f}%")
        with metrics_col2:
            st.metric("Precision", f"{metadata.get('precision', 0) * 100:.1f}%")
        with metrics_col3:
            st.metric("Validation Samples", metadata.get("test_samples", 0))
        with metrics_col4:
            st.metric(
                "Historical Win Rate",
                f"{metadata.get('win_rate', 0) * 100:.1f}%",
            )
        st.caption(
            "Historical metrics calculated using 80/20 chronological holdout validation."
        )

        importance = metadata.get("feature_importances", {})
        if importance:
            with st.expander("Top Feature Importances", expanded=True):
                importance_df = pd.DataFrame(
                    list(importance.items()),
                    columns=["Feature Signal", "Relative Importance (Gain)"],
                ).sort_values("Relative Importance (Gain)", ascending=False)
                st.dataframe(importance_df, width="stretch", hide_index=True)

    # ── TRAINING & DATA RETRAINING SECTION ──
    st.markdown("#### Model Training from Trade History")
    
    col_retrain, col_info = st.columns([1.5, 2.5])
    with col_retrain:
        if os.path.exists(LOCAL_CSV_PATH):
            if st.button("⚡ Quick Retrain from local trades_rows.csv", type="primary"):
                with st.spinner("Retraining XGBoost model from local trade history..."):
                    samples = load_trade_csv_samples(LOCAL_CSV_PATH)
                    trained, result = train_model(custom_data=samples, training_source="trade_csv")
                    if trained:
                        st.success(f"Retrained on {result['samples']} trades ({result['positive_samples']} wins, {result['negative_samples']} losses)!")
                        st.rerun()
                    else:
                        st.error(f"Training failed: {result.get('error')}")

    with col_info:
        if os.path.exists(LOCAL_CSV_PATH):
            st.caption(f"Using local dataset: `{LOCAL_CSV_PATH}` ({metadata.get('samples', 203)} records)")

    with st.expander("Upload Custom Trade CSV"):
        st.caption(
            "Upload any trades_rows.csv. Closed trades with positive actual P&L are labeled wins; "
            "zero or negative P&L are labeled non-wins."
        )
        uploaded_file = st.file_uploader(
            "Trade history CSV",
            type=["csv"],
            key="xgboost_observer_trade_csv",
        )

        if uploaded_file is not None:
            try:
                samples = load_trade_csv_samples(io.BytesIO(uploaded_file.getvalue()))
                wins = sum(sample["target"] for sample in samples)
                losses = len(samples) - wins
                st.write(f"Usable closed trades: **{len(samples)}** · Wins: **{wins}** · Losses: **{losses}**")

                if len(samples) >= 20 and wins and losses:
                    if st.button("Train from uploaded file"):
                        with st.spinner("Training model..."):
                            trained, result = train_model(custom_data=samples, training_source="trade_csv")
                            if trained:
                                st.success("Observer model trained successfully!")
                                st.rerun()
                            else:
                                st.error(f"Training failed: {result.get('error')}")
            except Exception as exc:
                st.error(f"Error reading CSV: {exc}")
