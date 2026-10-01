import streamlit as st
import datetime
import os
import json
import pandas as pd
import config

ML_ENABLED = getattr(config, "ML_ENABLED", False)
ML_MIN_PROBABILITY = getattr(config, "ML_MIN_PROBABILITY", 0.70)
ML_FAIL_SAFE_BLOCK = getattr(config, "ML_FAIL_SAFE_BLOCK", False)

from analytics.ml_db import get_training_data
from ml.model_manager import get_model, get_model_metadata, train_model, MODEL_PATH
from ml.historical_trainer import run_historical_training

def render_ml_dashboard():
    st.markdown("<h3 style='color:#34D399;'>🤖 AI / ML FILTER (XGBOOST)</h3>", unsafe_allow_html=True)
    st.write("XGBoost acts as a quantitative probabilistic filter to your V12 Strategy engine. It calculates the statistical probability that a trade setup will hit 1:2 Risk/Reward (₹3,000 Target) before hitting Stop Loss (₹1,500 Max Loss), taking into account both technical factors and AI Copilot quant verdicts.")

    # Status Cards
    model_loaded = get_model() is not None
    meta = get_model_metadata() or {}
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("ML Filter Status", "🟢 ACTIVE" if ML_ENABLED else "🔴 DISABLED")
    with col2:
        st.metric("Model In Memory", "✅ LOADED" if model_loaded else "⚠️ MISSING")
    with col3:
        st.metric("Minimum Probability", f"{ML_MIN_PROBABILITY*100:.0f}%")
    with col4:
        st.metric("Fail-Safe Mode", "BLOCK" if ML_FAIL_SAFE_BLOCK else "PASS")
        
    st.divider()

    # Model Performance & Metadata Card
    if meta:
        st.markdown("#### 📊 Production Model Metrics (Walk-Forward Validated)")
        m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
        with m_col1:
            st.metric("Validation Accuracy", f"{meta.get('accuracy', 0)*100:.1f}%")
        with m_col2:
            st.metric("Precision", f"{meta.get('precision', 0)*100:.1f}%")
        with m_col3:
            st.metric("F1 Score", f"{meta.get('f1', 0):.2f}")
        with m_col4:
            st.metric("Training Samples", f"{meta.get('samples', 0)}")
        with m_col5:
            st.metric("Last Trained", str(meta.get('trained_at', 'N/A')).split(" ")[0])

        # Feature Importances Expander
        feat_imp = meta.get("feature_importances", {})
        if feat_imp:
            with st.expander("🔍 Top Predictive Features (XGBoost Feature Weights)", expanded=False):
                imp_df = pd.DataFrame(list(feat_imp.items()), columns=["Feature", "Importance Weight"])
                imp_df = imp_df.sort_values(by="Importance Weight", ascending=False).reset_index(drop=True)
                st.dataframe(imp_df.head(10), use_container_width=True)

    st.markdown("#### ⚡ Retrain Model with Historical Candles & AI Copilot")
    st.caption("Connects to Angel One, downloads 5m candles for NIFTY & BANKNIFTY, replays your Rule Engine, evaluates setups with AI Copilot, labels 1:2 R:R outcomes, and updates `models/xgb_prod.joblib`.")
    
    col_opt1, col_opt2, col_opt3 = st.columns([1.5, 1.5, 2])
    with col_opt1:
        hist_days = st.selectbox("Replay Candle Window", [30, 60], index=1, format_func=lambda x: f"{x} Days (5m Candles)")
    with col_opt2:
        use_ai = st.checkbox("Include AI Copilot Intelligence", value=True, help="Queries NVIDIA / Gemini Copilot to incorporate quantitative conviction, market regime, and agreement scores into XGBoost features.")
    with col_opt3:
        st.write("") # Spacer
        if st.button("🚀 Run Full Replay & Retrain XGBoost", use_container_width=True, type="primary"):
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            
            def on_progress(msg, pct):
                progress_bar.progress(min(1.0, max(0.0, pct)))
                status_text.info(f"⏳ {msg}")

            with st.spinner("Executing historical replay pipeline..."):
                ok, res = run_historical_training(
                    days=hist_days,
                    include_ai=use_ai,
                    max_ai_evals=20 if use_ai else 0,
                    progress_callback=on_progress
                )
                if ok:
                    progress_bar.progress(1.0)
                    status_text.empty()
                    st.success(f"🎉 **XGBoost Successfully Retrained!** Saved to `models/xgb_prod.joblib`. Walk-forward Accuracy: **{res.get('accuracy', 0)*100:.1f}%** across {res.get('samples', 0)} setups.")
                    st.rerun()
                else:
                    status_text.empty()
                    st.error(f"❌ Training failed: {res.get('error')}")

    st.divider()

    # Real-Time Live Logs Section
    col_t1, col_t2 = st.columns(2)
    data = get_training_data()
    samples = len(data)

    with col_t1:
        st.markdown("#### 🧠 Live Streamlit Trades (Supabase)")
        if samples < 50:
            st.info(f"Currently have {samples}/50 live logged trades in Supabase. (Historical training above is fully active).")
        else:
            wins = sum(1 for d in data if d.get('target') == 1)
            st.success(f"Supabase contains {samples} live samples ({wins} Wins / {samples-wins} Losses)")
            
    with col_t2:
        st.markdown("#### ⚙️ Incremental Retrain")
        if st.button("🔄 Retrain on Supabase Live Data Only"):
            with st.spinner("Training model on Supabase Data..."):
                success, metrics = train_model()
                if success:
                    st.success(f"Training Complete! Win Rate Baseline: {metrics.get('win_rate', 0)*100:.1f}% | F1: {metrics.get('f1', 0):.2f}")
                    st.rerun()
                else:
                    st.error(metrics.get("error", "Unknown Error"))
                    
    # Log Table
    st.markdown("#### 📡 Recent Live Predictions Log")
    if samples == 0:
        st.caption("No real-time predictions recorded in database yet.")
    else:
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.sort_values(by="timestamp", ascending=False).head(20)
            disp_df = df[['timestamp', 'idx', 'signal', 'strategy_score', 'xgb_probability', 'decision', 'target']]
            disp_df['xgb_probability'] = (disp_df['xgb_probability'] * 100).round(1).astype(str) + "%"
            st.dataframe(disp_df, use_container_width=True)
