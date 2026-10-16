import unittest
import threading
from unittest.mock import MagicMock, patch

from analytics.db import TradeDB
from ui.renderer import _get_trades_for_date, _merge_trade_records, _safe_trade_pnl


class TestOpenTradeRendering(unittest.TestCase):
    def test_trade_pnl_ignores_non_finite_and_invalid_values(self):
        self.assertEqual(125.5, _safe_trade_pnl({"Actual P&L ₹": "125.5"}))
        self.assertEqual(-12.0, _safe_trade_pnl({"Actual P&L ₹": -12}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": None}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": float("nan")}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": float("inf")}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": "invalid"}))

    def test_database_status_is_authoritative_and_session_price_stays_live(self):
        database_trade = {
            "trade_id": "trade-1",
            "Status": "OPEN",
            "Entry Time": "10:00 AM",
            "Strike": 24500,
            "_live_price_updated_at": None,
        }
        foreground_trade = {
            **database_trade,
            "Status": "CLOSED",
            "Live Price": 120,
            "_live_price_updated_at": 100.0,
        }
        session_trade = {
            **database_trade,
            "Status": "CLOSED",
            "Live Price": 125,
            "_live_price_updated_at": 101.0,
        }

        merged = _merge_trade_records(
            "NIFTY",
            [database_trade],
            [foreground_trade],
            [session_trade],
        )

        self.assertEqual(1, len(merged))
        self.assertEqual("OPEN", merged[0]["Status"])
        self.assertEqual(125, merged[0]["Live Price"])
        self.assertEqual(101.0, merged[0]["_live_price_updated_at"])

    def test_database_closed_status_overrides_cached_open_status(self):
        database_trade = {"trade_id": "trade-1", "Status": "CLOSED"}
        cached_trade = {"trade_id": "trade-1", "Status": "OPEN", "Live Price": 125}

        merged = _merge_trade_records("NIFTY", [database_trade], [], [cached_trade])

        self.assertEqual("CLOSED", merged[0]["Status"])

    def test_older_browser_quote_cannot_replace_newer_database_quote(self):
        database_trade = {
            "trade_id": "trade-1",
            "Status": "OPEN",
            "Live Price": 130.0,
            "_live_price_updated_at": 1000.0,
        }
        cached_trade = {
            "trade_id": "trade-1",
            "Status": "OPEN",
            "Live Price": 125.0,
            "_live_price_updated_at": 999.0,
        }

        merged = _merge_trade_records("NIFTY", [database_trade], [], [cached_trade])

        self.assertEqual(130.0, merged[0]["Live Price"])
        self.assertEqual(1000.0, merged[0]["_live_price_updated_at"])

    def test_successful_empty_database_does_not_resurrect_cached_open_trade(self):
        cached_trade = {
            "trade_id": "stale-trade",
            "Status": "OPEN",
            "Entry Time": "10:00 AM",
            "Strike": 24500,
        }

        merged = _merge_trade_records("NIFTY", [], [], [cached_trade])

        self.assertEqual([], merged)

    def test_local_trades_are_used_when_database_read_is_unavailable(self):
        cached_trade = {"trade_id": "cached-trade", "Status": "OPEN"}

        merged = _merge_trade_records("NIFTY", None, [], [cached_trade])

        self.assertEqual([cached_trade], merged)

    def test_trade_date_filter_is_applied_in_database_query(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()
        connection = MagicMock()
        connection.cursor.return_value.fetchall.return_value = []

        with patch.object(db, "_get_connection", return_value=connection):
            self.assertEqual([], db.get_all_trades(trade_date="2026-10-16"))

        cursor = connection.cursor.return_value
        query, params = cursor.execute.call_args.args
        self.assertIn("AND trade_date = %s", query)
        self.assertEqual(("2026-10-16",), params)

    def test_cached_legacy_database_client_falls_back_to_date_filtering(self):
        class LegacyTradeDB:
            def get_all_trades(self):
                return [
                    {"date": "2026-10-16", "trade_id": "today"},
                    {"date": "2026-10-15", "trade_id": "yesterday"},
                ]

        trades = _get_trades_for_date(LegacyTradeDB(), "2026-10-16")

        self.assertEqual(["today"], [trade["trade_id"] for trade in trades])


if __name__ == "__main__":
    unittest.main()
