import io
import os
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ml.model_manager import (
    get_model,
    get_model_metadata,
    load_trade_csv_samples,
    train_model,
    MODEL_PATH,
)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_CSV_PATH = os.path.join(ROOT_DIR, "trades_rows.csv")
LOCAL_DASHBOARD_HTML = os.path.join(ROOT_DIR, "dashboard.html")


def render_ml_dashboard():
    st.markdown(
        "<h3 style='color:#34D399;'>🤖 XGBOOST LIVE OBSERVER & ANALYTICS</h3>",
        unsafe_allow_html=True,
    )
    st.info(
        "Evaluation only: live probabilities are displayed for confirmed signals. "
        "XGBoost filters false breakouts and calculates quantitative win probability."
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
            st.metric("Chronological Holdout Accuracy", f"{metadata.get('accuracy', 0) * 100:.1f}%")
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
            with st.expander("Feature importances"):
                importance_df = pd.DataFrame(
                    list(importance.items()),
                    columns=["Feature", "Importance"],
                ).sort_values("Importance", ascending=False)
                st.dataframe(importance_df, width="stretch", hide_index=True)

    # ── EMBEDDED INTERACTIVE QUANT DASHBOARD ──
    if os.path.exists(LOCAL_DASHBOARD_HTML):
        with st.expander("📊 INTERACTIVE VISUAL ANALYTICS & THRESHOLD SIMULATOR", expanded=True):
            st.caption("Drag the threshold slider below to simulate equity curve, win rate, and profit factor in real-time.")
            try:
                with open(LOCAL_DASHBOARD_HTML, "r", encoding="utf-8") as f:
                    html_code = f.read()
                components.html(html_code, height=880, scrolling=True)
            except Exception as e:
                st.warning(f"Could not load embedded dashboard: {e}")

    # ── TRAINING & SYNC SECTION ──
    st.markdown("#### Retrain or Update Model")
    
    col_retrain, col_status = st.columns([1, 2])
    with col_retrain:
        if os.path.exists(LOCAL_CSV_PATH):
            if st.button("⚡ Quick Retrain from local trades_rows.csv", type="secondary"):
                with st.spinner("Retraining XGBoost observer from local trades_rows.csv..."):
                    samples = load_trade_csv_samples(LOCAL_CSV_PATH)
                    trained, result = train_model(custom_data=samples, training_source="trade_csv")
                    if trained:
                        st.success(f"Retrained on {result['samples']} trades!")
                        st.rerun()
                    else:
                        st.error(f"Failed: {result.get('error')}")

    with st.expander("Upload Custom Trade CSV"):
        st.caption(
            "Upload trades_rows.csv. Closed trades with positive actual P&L are labeled wins; "
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
                    if st.button("Train from uploaded file", type="primary"):
                        with st.spinner("Training model..."):
                            trained, result = train_model(custom_data=samples, training_source="trade_csv")
                            if trained:
                                st.success("Observer model trained successfully!")
                                st.rerun()
                            else:
                                st.error(f"Training failed: {result.get('error')}")
            except Exception as exc:
                st.error(f"Error reading CSV: {exc}")
