import io
import os
import pandas as pd
import streamlit as st

from ml.model_manager import (
    get_model,
    get_model_metadata,
    train_model,
    MODEL_PATH,
)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_CSV_PATH = os.path.join(ROOT_DIR, "trades_rows.csv")


def render_ml_dashboard():
    st.markdown(
        "<h3 style='color:#34D399;'>🤖 XGBOOST WIN PROBABILITY OBSERVER</h3>",
        unsafe_allow_html=True,
    )
    st.info(
        "Evaluation & Filter Engine: trained on 11 entry-time direction-aware features with Leave-One-Day-Out CV. "
        "Evaluates setup quality and calculates positive expected-value thresholds."
    )

    metadata = get_model_metadata() or {}
    model = get_model()
    observer_ready = bool(
        model is not None
        and metadata.get("training_source") in ("trade_csv", "supabase_db", "supabase")
    )

    status_col, samples_col, trained_col = st.columns(3)
    with status_col:
        st.metric("Observer Model", "READY (11 Features)" if observer_ready else "NEEDS TRAINING")
    with samples_col:
        st.metric("Closed Trade Samples", metadata.get("samples", "—"))
    with trained_col:
        st.metric("Last Trained", metadata.get("trained_at", "—"))

    if observer_ready:
        metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
        with metrics_col1:
            auc = metadata.get("oof_auc")
            st.metric("OOF ROC AUC", f"{auc:.3f}" if auc is not None else "—")
        with metrics_col2:
            brier = metadata.get("oof_brier")
            st.metric("Brier Score", f"{brier:.3f}" if brier is not None else "—")
        with metrics_col3:
            wr = metadata.get("win_rate", 0)
            st.metric("Baseline Win Rate", f"{wr * 100:.1f}%")
        with metrics_col4:
            be = metadata.get("break_even_threshold")
            st.metric("Break-Even Prob", f"{be * 100:.1f}%" if be is not None else "—")

        st.caption(
            f"Cross-Validation: **{metadata.get('cv_method', 'Leave-One-Day-Out')}** · "
            f"Avg Win: ₹{metadata.get('avg_win', 0):.0f} · Avg Loss: ₹{metadata.get('avg_loss', 0):.0f}"
        )

        # Expected Value Threshold Analysis
        th_analysis = metadata.get("threshold_analysis", {})
        if th_analysis:
            with st.expander("📊 Expected-Value Filter Simulation", expanded=True):
                st.caption("Performance if only executing trades with probability ≥ threshold:")
                rows = []
                for label, stats in th_analysis.items():
                    rows.append({
                        "Threshold": label,
                        "Trades": stats.get("trades", 0),
                        "Win Rate": f"{stats.get('win_rate', 0) * 100:.1f}%",
                        "Net P&L (₹)": f"₹{stats.get('pnl', 0):,.0f}",
                        "Avg P&L / Trade": f"₹{stats.get('avg_pnl', 0):.0f}",
                    })
                if rows:
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        importance = metadata.get("feature_importances", {})
        if importance:
            with st.expander("Top Feature Importances", expanded=True):
                importance_df = pd.DataFrame(
                    list(importance.items()),
                    columns=["Feature Signal", "Relative Importance (Gain)"],
                ).sort_values("Relative Importance (Gain)", ascending=False)
                st.dataframe(importance_df, width="stretch", hide_index=True)

    # ── TRAINING & DATA RETRAINING SECTION ─────────────────────────────
    st.markdown("#### Model Training from Database / CSV")

    col_retrain, col_info = st.columns([1.8, 2.2])
    with col_retrain:
        if st.button("🔄 Train / Retrain from Supabase Database", type="primary"):
            with st.spinner("Connecting to Supabase PostgreSQL and fetching closed trades..."):
                trained, result = train_model(training_source="supabase")
                if trained:
                    st.success(
                        f"Observer model trained on {result['samples']} closed trades "
                        f"({result['positive_samples']} wins, {result['negative_samples']} losses)!"
                    )
                    st.rerun()
                else:
                    st.error(f"Training failed: {result.get('error')}")

    with col_info:
        src = metadata.get("training_source", "None")
        src_label = "Cloud Supabase PostgreSQL" if "supabase" in src else ("Local CSV File" if "csv" in src else "None")
        st.caption(f"Active Training Source: **{src_label}** ({metadata.get('samples', '—')} closed trades)")

    # Local trades_rows.csv quick train
    if os.path.exists(LOCAL_CSV_PATH):
        with st.expander("Train from Local trades_rows.csv"):
            st.caption(f"Found local file `{LOCAL_CSV_PATH}`")
            if st.button("Train from trades_rows.csv", key="btn_train_local_csv"):
                with st.spinner("Training 11-feature XGBoost on local trades_rows.csv..."):
                    trained, result = train_model(custom_data=LOCAL_CSV_PATH, training_source="trade_csv")
                    if trained:
                        st.success(
                            f"Model trained! OOF AUC: {result.get('oof_auc', 0):.3f}, "
                            f"Break-even: {result.get('break_even_threshold', 0) * 100:.1f}%"
                        )
                        st.rerun()
                    else:
                        st.error(f"Training failed: {result.get('error')}")

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
                df_up = pd.read_csv(io.BytesIO(uploaded_file.getvalue()))
                df_up["actual_pnl"] = pd.to_numeric(df_up.get("actual_pnl"), errors="coerce")
                df_up = df_up[df_up.actual_pnl.notna()].reset_index(drop=True)
                wins = int((df_up.actual_pnl > 0).sum())
                losses = len(df_up) - wins
                st.write(f"Usable closed trades: **{len(df_up)}** · Wins: **{wins}** · Losses: **{losses}**")

                if len(df_up) >= 20 and wins and losses:
                    if st.button("Train from uploaded file"):
                        with st.spinner("Training model..."):
                            trained, result = train_model(custom_data=df_up, training_source="trade_csv")
                            if trained:
                                st.success("Observer model trained successfully!")
                                st.rerun()
                            else:
                                st.error(f"Training failed: {result.get('error')}")
            except Exception as exc:
                st.error(f"Error reading CSV: {exc}")
