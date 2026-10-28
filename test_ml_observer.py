"""Tests for the XGBoost evaluation-only trade observer."""
import io
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault(
    "SUPABASE_URI",
    "******db.pooler.supabase.com:5432/test",
)

import pandas as pd

from ml.feature_engineering import (
    OBSERVER_FEATURE_COLUMNS,
    observer_features_from_market,
    observer_features_from_trade,
)
from ml.model_manager import load_trade_csv_samples, predict_live_observer_probability
from ml.predict import observe_ml_signal


class TestMlObserver(unittest.TestCase):
    def test_csv_loader_excludes_open_and_unlabeled_rows(self):
        closed_trade = {
            "status": "CLOSED",
            "actual_pnl": "125.50",
            "instrument": "NIFTY",
            "signal": "BUY CE",
            "spot": 22000,
            "strike": 22000,
            "entry_price": 100,
            "created_at": "2026-10-15T10:00:00+05:30",
            "metadata_json": json.dumps({"pcr": 1.1}),
        }
        open_trade = {**closed_trade, "status": "OPEN", "actual_pnl": ""}
        missing_pnl_trade = {**closed_trade, "actual_pnl": ""}
        csv_content = pd.DataFrame(
            [closed_trade, open_trade, missing_pnl_trade]
        ).to_csv(index=False)

        samples = load_trade_csv_samples(io.StringIO(csv_content))

        self.assertEqual(1, len(samples))
        self.assertEqual(1, samples[0]["target"])
        self.assertEqual(list(OBSERVER_FEATURE_COLUMNS), list(samples[0]["features"]))

    def test_historical_and_live_features_share_one_schema(self):
        timestamp = "2026-10-15T10:00:00+05:30"
        metadata = {
            "pcr": 1.1,
            "vwap": 21990,
            "oi_delta_ce": 120,
            "oi_delta_pe": 240,
            "pcr_momentum": "RISING",
            "trap": "NONE",
            "recommendation": "EXECUTE_BUY_CE",
            "market_bias": "BULLISH",
        }
        trade = {
            "instrument": "NIFTY",
            "signal": "BUY CE",
            "spot": 22000,
            "strike": 22000,
            "entry_price": 100,
            "confidence_score": 70,
            "ai_generated": 1,
            "ai_conviction": 80,
            "created_at": timestamp,
            "metadata_json": json.dumps(metadata),
        }
        live_market = {
            "spot": 22000,
            "atm_actual": 22000,
            "atm_row": pd.Series({"CE LTP": 100, "PE LTP": 90}),
            "pcr": 1.1,
            "vwap_proxy": 21990,
            "total_ce_delta": 120,
            "total_pe_delta": 240,
            "pcr_momentum": "RISING",
            "trap": "NONE",
        }
        ai_analysis = {
            "provider": "Gemini",
            "conviction_score": 80,
            "recommendation": "EXECUTE_BUY_CE",
            "market_bias": "BULLISH",
        }
        now = pd.Timestamp(timestamp).to_pydatetime()

        historical_features = observer_features_from_trade(trade)
        live_features = observer_features_from_market(
            "NIFTY",
            "BUY CE",
            live_market,
            now,
            70,
            ai_analysis=ai_analysis,
        )

        self.assertEqual(list(OBSERVER_FEATURE_COLUMNS), list(historical_features))
        self.assertEqual(list(OBSERVER_FEATURE_COLUMNS), list(live_features))
        self.assertEqual(historical_features, live_features)

    def test_live_probability_is_returned_without_threshold_decision(self):
        metadata = {
            "training_source": "trade_csv",
            "features": list(OBSERVER_FEATURE_COLUMNS),
        }
        with (
            patch("ml.model_manager.get_model_metadata", return_value=metadata),
            patch(
                "ml.model_manager.observer_features_from_market",
                return_value={column: 0.0 for column in OBSERVER_FEATURE_COLUMNS},
            ),
            patch("ml.model_manager.predict_probability", return_value=0.12),
        ):
            probability = predict_live_observer_probability(
                "NIFTY", "BUY CE", {}, pd.Timestamp.now().to_pydatetime(), 50
            )

        self.assertEqual(0.12, probability)

    def test_observer_wrapper_never_returns_a_trade_decision(self):
        with patch("ml.predict.predict_live_observer_probability", return_value=0.12):
            probability = observe_ml_signal("NIFTY", "BUY CE", {}, 50)

        self.assertEqual(0.12, probability)

    def test_live_prediction_rejects_non_csv_models(self):
        with patch("ml.model_manager.get_model_metadata", return_value={"training_source": "supabase"}):
            probability = predict_live_observer_probability(
                "NIFTY", "BUY CE", {}, pd.Timestamp.now().to_pydatetime(), 50
            )

        self.assertIsNone(probability)


if __name__ == "__main__":
    unittest.main()
