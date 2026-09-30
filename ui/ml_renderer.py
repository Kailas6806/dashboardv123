import streamlit as st
import datetime
import config
ML_ENABLED = getattr(config, "ML_ENABLED", False)
ML_MIN_PROBABILITY = getattr(config, "ML_MIN_PROBABILITY", 0.70)
ML_FAIL_SAFE_BLOCK = getattr(config, "ML_FAIL_SAFE_BLOCK", True)
from analytics.ml_db import get_training_data
import os
import joblib

def render_ml_dashboard():
    st.markdown("<h3 style='color:#34D399;'>🤖 AI / ML FILTER (XGBOOST)</h3>", unsafe_allow_html=True)
    st.write("XGBoost is acting as a secondary probabilistic filter to your V12 Strategy engine. It calculates the historical probability that the current trade setup will hit 1:2 Risk/Reward before hitting Stop Loss.")

    # Status Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("ML Filter Status", "🟢 ACTIVE" if ML_ENABLED else "🔴 DISABLED")
    with col2:
        st.metric("Model Version", "v1.0")
    with col3:
        st.metric("Minimum Probability", f"{ML_MIN_PROBABILITY*100:.0f}%")
    with col4:
        st.metric("Fail-Safe Mode", "BLOCK" if ML_FAIL_SAFE_BLOCK else "PASS")
        
    st.divider()

    data = get_training_data()
    samples = len(data)
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown("#### 🧠 Training Data")
        if samples < 50:
            st.warning(f"WAITING FOR TRAINING DATA. Currently have {samples}/50 samples required.")
        else:
            wins = sum(1 for d in data if d.get('target') == 1)
            st.success(f"Model trained on {samples} historical samples ({wins} Wins / {samples-wins} Losses)")
            
    with col_t2:
        st.markdown("#### ⚙️ Manual Actions")
        if st.button("🔄 Retrain XGBoost Model (Walk-Forward)"):
            with st.spinner("Training model on Supabase Data..."):
                from ml.model_manager import train_model
                success, metrics = train_model()
                if success:
                    st.success(f"Training Complete! Win Rate Baseline: {metrics.get('win_rate', 0)*100:.1f}% | F1: {metrics.get('f1', 0):.2f}")
                else:
                    st.error(metrics.get("error", "Unknown Error"))
                    
    # Log Table
    st.markdown("#### 📡 Recent Live Predictions")
    if samples == 0:
        st.info("No predictions logged yet.")
    else:
        import pandas as pd
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.sort_values(by="timestamp", ascending=False).head(20)
            disp_df = df[['timestamp', 'idx', 'signal', 'strategy_score', 'xgb_probability', 'decision', 'target']]
            disp_df['xgb_probability'] = (disp_df['xgb_probability'] * 100).round(1).astype(str) + "%"
            st.dataframe(disp_df, use_container_width=True)
