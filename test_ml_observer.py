"""Tests for the XGBoost 11-feature evaluation-only trade observer."""
import json
import os
import unittest
import datetime
import numpy as np
import pandas as pd

from ml.feature_engineering import (
    FEATURES,
    DROP_COLUMNS,
    build,
    build_live_features,
)
from ml.model_manager import (
    train_model,
    predict_probability,
    predict_live_observer_probability,
    get_model_metadata,
)
from ml.predict import observe_ml_signal


class TestMlObserver(unittest.TestCase):
    def setUp(self):
        self.sample_rows = [
            {
                "trade_id": "T1",
                "trade_date": "2026-10-15",
                "entry_time": "10:00:00 AM",
                "instrument": "NIFTY",
                "signal": "BUY CE",
                "spot": 22000.0,
                "strike": 22050.0,
                "entry_price": 100.0,
                "stop_loss": 85.0,
                "target": 130.0,
                "actual_pnl": 1500.0,
                "status": "CLOSED",
                "metadata_json": json.dumps({
                    "pcr": 1.2,
                    "vwap": 21980.0,
                    "oi_delta_ce": 10000.0,
                    "oi_delta_pe": 25000.0,
                    "pcr_momentum": "RISING",
                    "buffer_state": ["BUY CE", "BUY CE"],
                }),
            },
            {
                "trade_id": "T2",
                "trade_date": "2026-10-16",
                "entry_time": "11:30:00 AM",
                "instrument": "BANKNIFTY",
                "signal": "BUY PE",
                "spot": 48000.0,
                "strike": 47900.0,
                "entry_price": 250.0,
                "stop_loss": 220.0,
                "target": 310.0,
                "actual_pnl": -750.0,
                "status": "CLOSED",
                "metadata_json": json.dumps({
                    "pcr": 0.8,
                    "vwap": 48050.0,
                    "oi_delta_ce": 30000.0,
                    "oi_delta_pe": 10000.0,
                    "pcr_momentum": "FALLING",
                    "buffer_state": ["SIDEWAYS", "BUY PE"],
                }),
            },
        ]

    def test_build_extracts_11_features_and_no_leakage(self):
        df = pd.DataFrame(self.sample_rows)
        X = build(df)
        self.assertEqual(list(FEATURES), list(X.columns))
        self.assertEqual(11, len(X.columns))
        # Leakage check: no DROP_COLUMNS in X
        leaked = set(X.columns) & set(DROP_COLUMNS)
        self.assertEqual(set(), leaked)

    def test_live_features_match_batch_features(self):
        row = self.sample_rows[0]
        meta = json.loads(row["metadata_json"])
        dt = datetime.datetime(2026, 10, 15, 10, 0, 0)

        live_f = build_live_features(
            signal=row["signal"],
            entry_price=row["entry_price"],
            stop_loss=row["stop_loss"],
            spot=row["spot"],
            strike=row["strike"],
            now=dt,
            vwap=meta["vwap"],
            pcr=meta["pcr"],
            oi_delta_ce=meta["oi_delta_ce"],
            oi_delta_pe=meta["oi_delta_pe"],
            pcr_momentum=meta["pcr_momentum"],
            buffer_state=meta["buffer_state"],
        )

        df = pd.DataFrame([row])
        batch_f = build(df).iloc[0].to_dict()

        for k in FEATURES:
            self.assertAlmostEqual(live_f[k], batch_f[k], places=4, msg=f"Mismatch on {k}")

    def test_model_training_and_live_inference(self):
        # Generate 24 synthetic rows across 3 days to test LeaveOneGroupOut CV
        rows = []
        for i in range(24):
            day = 15 + (i % 3)
            is_win = (i % 2 == 0)
            rows.append({
                "trade_id": f"T{i}",
                "trade_date": f"2026-10-{day}",
                "entry_time": f"10:{i:02d}:00 AM",
                "instrument": "NIFTY",
                "signal": "BUY CE" if is_win else "BUY PE",
                "spot": 22000.0 + i * 10,
                "strike": 22000.0,
                "entry_price": 100.0,
                "stop_loss": 85.0,
                "target": 130.0,
                "actual_pnl": 500.0 if is_win else -300.0,
                "status": "CLOSED",
                "metadata_json": json.dumps({
                    "pcr": 1.2 if is_win else 0.8,
                    "vwap": 21950.0,
                    "oi_delta_ce": 5000.0,
                    "oi_delta_pe": 15000.0,
                    "pcr_momentum": "RISING" if is_win else "FALLING",
                    "buffer_state": ["BUY CE"] if is_win else ["SIDEWAYS"],
                }),
            })

        df = pd.DataFrame(rows)
        success, metrics = train_model(custom_data=df, training_source="trade_csv")
        self.assertTrue(success)
        self.assertIn("oof_auc", metrics)
        self.assertIn("break_even_threshold", metrics)
        self.assertEqual(list(FEATURES), metrics["features"])

        # Test live observer prediction
        market_data = {
            "spot": 22050.0,
            "atm_actual": 22000.0,
            "vwap_proxy": 21950.0,
            "pcr": 1.25,
            "total_ce_delta": 4000.0,
            "total_pe_delta": 18000.0,
            "pcr_momentum": "RISING",
        }
        prob = observe_ml_signal(
            idx="NIFTY",
            signal="BUY CE",
            md=market_data,
            strategy_score=75.0,
            entry_price=105.0,
            stop_loss=90.0,
            buffer_state=["BUY CE", "BUY CE"],
        )
        self.assertIsNotNone(prob)
        self.assertTrue(0.0 <= prob <= 1.0)


if __name__ == "__main__":
    unittest.main()
