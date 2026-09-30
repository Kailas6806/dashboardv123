import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from utils.logger import get_logger

logger = get_logger("ml_db")

def get_connection():
    import streamlit as st
    try:
        if "supabase" in st.secrets:
            uri = st.secrets["supabase"].get("SUPABASE_URI", "")
            if uri:
                return psycopg2.connect(uri)
    except Exception as e:
        logger.warning(f"Failed to load DB URI from secrets: {e}")
    return None

def init_ml_tables():
    """Create ML logging tables if they don't exist."""
    conn = get_connection()
    if not conn:
        return
        
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ml_predictions (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    idx VARCHAR(50),
                    signal VARCHAR(10),
                    strategy_score FLOAT,
                    features JSONB,
                    xgb_probability FLOAT,
                    model_version VARCHAR(50),
                    decision VARCHAR(20),
                    target INT DEFAULT NULL
                );
            """)
        conn.commit()
        logger.info("ML tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing ML tables: {e}")
    finally:
        conn.close()

def log_prediction(idx: str, signal: str, strategy_score: float, features: dict, probability: float, version: str, decision: str) -> int:
    """Log a real-time ML prediction to Supabase and return the row ID."""
    conn = get_connection()
    if not conn:
        return -1
        
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ml_predictions 
                (idx, signal, strategy_score, features, xgb_probability, model_version, decision)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (idx, signal, strategy_score, json.dumps(features), probability, version, decision))
            row_id = cur.fetchone()[0]
        conn.commit()
        return row_id
    except Exception as e:
        logger.error(f"Error logging ML prediction: {e}")
        return -1
    finally:
        conn.close()

def get_training_data():
    """Fetch completed trades to train the XGBoost model."""
    conn = get_connection()
    if not conn:
        return []
        
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM ml_predictions 
                WHERE target IS NOT NULL
                ORDER BY timestamp ASC;
            """)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Error fetching ML training data: {e}")
        return []
    finally:
        conn.close()
