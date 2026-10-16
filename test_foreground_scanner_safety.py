"""Regression tests for foreground scanner entry safeguards."""
import os
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault(
    "SUPABASE_URI",
    "postgresql://test:test@db.pooler.supabase.com:5432/test",
)

import config
from analytics.db import TradeDB
from core.ai_copilot import build_ai_trade_metadata
from core.angelone_fetcher import AngelOneDataFetcher
from core import foreground_scanner


class _ExistingOpenTradeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return (1,)


class _FakeConnection:
    def __init__(self):
        self.test_cursor = _ExistingOpenTradeCursor()
        self.rolled_back = False
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.test_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class TestForegroundScannerSafety(unittest.TestCase):
    def test_ai_trade_metadata_preserves_detailed_rationale(self):
        metadata = build_ai_trade_metadata({
            "reasoning_summary": "Institutional flow favors calls.",
            "detailed_reasoning": "PCR rose from 0.92 to 1.18 as put OI expanded.",
            "recommendation": "EXECUTE_BUY_CE",
            "market_bias": "BULLISH",
            "conviction_score": 82,
            "key_factors": ["PCR rising", "Put writing"],
            "risk_warning": "Resistance near the next strike.",
            "provider": "Gemini",
            "timestamp": "10:15 AM",
            "inference_time": "1.2s",
        }, execution_mode="AI_RECOMMENDATION")

        self.assertEqual(
            "PCR rose from 0.92 to 1.18 as put OI expanded.",
            metadata["ai_reasoning"],
        )
        self.assertEqual("Institutional flow favors calls.", metadata["ai_reasoning_summary"])
        self.assertEqual(82, metadata["ai_conviction"])
        self.assertEqual(["PCR rising", "Put writing"], metadata["ai_key_factors"])
        self.assertEqual(["Resistance near the next strike."], metadata["ai_risk_flags"])
        self.assertEqual("AI_RECOMMENDATION", metadata["ai_execution_mode"])

    def test_option_scrip_index_avoids_repeated_master_searches(self):
        fetcher = AngelOneDataFetcher.__new__(AngelOneDataFetcher)
        fetcher.scrip_master = [
            {
                "name": "NIFTY",
                "instrumenttype": "OPTIDX",
                "expiry": "05NOV2026",
                "strike": "2200000",
                "symbol": "NIFTY05NOV2622000CE",
                "token": "later",
            },
            {
                "name": "NIFTY",
                "instrumenttype": "OPTIDX",
                "expiry": "29OCT2026",
                "strike": "2200000",
                "symbol": "NIFTY29OCT2622000CE",
                "token": "nearest",
            },
            {"name": "NIFTY", "instrumenttype": "FUTIDX", "expiry": "29OCT2026"},
        ]
        fetcher._token_symbol_map = {}
        fetcher._option_scrips_by_expiry = {}
        fetcher._option_expiries_by_index = {}

        fetcher._build_token_symbol_map()

        self.assertEqual(["29OCT2026", "05NOV2026"], fetcher._option_expiries_by_index["NIFTY"])
        self.assertEqual(
            ("nearest", "NIFTY29OCT2622000CE"),
            fetcher.get_option_token("NIFTY", 22000, "BUY CE"),
        )

    def test_stale_or_untimestamped_chain_is_not_fresh(self):
        self.assertTrue(foreground_scanner._is_fresh_option_chain({"_fetched_at": 85}, now_ts=100))
        self.assertFalse(foreground_scanner._is_fresh_option_chain({"_fetched_at": 84.99}, now_ts=100))
        self.assertFalse(foreground_scanner._is_fresh_option_chain({}, now_ts=100))
        self.assertFalse(foreground_scanner._is_fresh_option_chain({"_fetched_at": 101}, now_ts=100))

    def test_disabled_scanner_does_not_scan(self):
        initial_scans = foreground_scanner._scanner_state["total_scans"]
        fetcher = Mock()
        with patch.object(config, "ENABLE_BACKGROUND_SCANNER", False):
            result = foreground_scanner.run_foreground_market_scan(
                fetcher, Mock(), Mock(), Mock(), Mock(), force=True
            )
            self.assertEqual("DISABLED", foreground_scanner.get_scanner_status()["status"])
        fetcher.fetch_option_chain.assert_not_called()
        self.assertEqual(initial_scans, foreground_scanner._scanner_state["total_scans"])
        self.assertIs(result, foreground_scanner._scanner_state["latest_states"])

    def test_ai_autotrade_requires_configured_successful_approval(self):
        approved, _, _, _, _ = foreground_scanner._validate_ai_entry(
            None, "NIFTY", {}, "BUY CE", 80, True, 0
        )
        self.assertFalse(approved)

        copilot = Mock()
        copilot.is_configured.return_value = True
        copilot.analyze_market_and_signals.side_effect = RuntimeError("provider unavailable")
        approved, _, recommendation, _, _ = foreground_scanner._validate_ai_entry(
            copilot, "NIFTY", {}, "BUY CE", 80, True, 0
        )
        self.assertFalse(approved)
        self.assertEqual("AI_VALIDATION_FAILED", recommendation)

        copilot.analyze_market_and_signals.side_effect = None
        copilot.analyze_market_and_signals.return_value = {
            "conviction_score": config.AI_MIN_CONVICTION,
            "recommendation": "EXECUTE_BUY_CE",
            "reasoning_summary": "Approved",
        }
        approved, _, _, _, _ = foreground_scanner._validate_ai_entry(
            copilot, "NIFTY", {}, "BUY CE", 80, True, 0
        )
        self.assertTrue(approved)

    def test_open_trade_check_and_insert_are_serialized_in_database(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()
        connection = _FakeConnection()
        with patch.object(db, "_get_connection", return_value=connection):
            result = db.upsert_trade(
                {"Index": "NIFTY", "Entry Time": "10:00:00 AM", "Status": "OPEN"},
                reject_if_open=True,
            )

        self.assertIsNone(result)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        queries = [query for query, _ in connection.test_cursor.calls]
        self.assertIn("pg_advisory_xact_lock", queries[0])
        self.assertIn("status = 'OPEN'", queries[1])
        self.assertFalse(any(query.lstrip().startswith("INSERT INTO trades") for query in queries))

    def test_stop_loss_update_preserves_open_trade_status(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()
        connection = _FakeConnection()
        connection.test_cursor.rowcount = 1

        with patch.object(db, "_get_connection", return_value=connection):
            updated = db.update_trade_stop_loss(
                "TEST_NIFTY_001",
                151.25,
                {"Index": "NIFTY", "Entry Time": "10:00:00 AM", "Strike": 22000, "Signal": "BUY CE"},
            )

        self.assertTrue(updated)
        self.assertTrue(connection.committed)
        query, params = connection.test_cursor.calls[0]
        self.assertIn("SET stop_loss = %s", query)
        self.assertIn("status = 'OPEN'", query)
        self.assertEqual(params[0], 151.25)
        self.assertNotIn("status =", query.split("WHERE")[0])


if __name__ == "__main__":
    unittest.main()
