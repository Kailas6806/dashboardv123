import unittest
import threading
from unittest.mock import MagicMock, patch

from analytics.db import TradeDB
from ui.renderer import _merge_trade_records, _safe_trade_pnl


class TestOpenTradeRendering(unittest.TestCase):
    def test_trade_pnl_ignores_non_finite_and_invalid_values(self):
        self.assertEqual(125.5, _safe_trade_pnl({"Actual P&L ₹": "125.5"}))
        self.assertEqual(-12.0, _safe_trade_pnl({"Actual P&L ₹": -12}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": None}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": float("nan")}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": float("inf")}))
        self.assertEqual(0.0, _safe_trade_pnl({"Actual P&L ₹": "invalid"}))

    def test_session_log_overrides_stale_foreground_status(self):
        database_trade = {
            "trade_id": "trade-1",
            "Status": "OPEN",
            "Entry Time": "10:00 AM",
            "Strike": 24500,
        }
        foreground_trade = {**database_trade, "Status": "CLOSED"}
        session_trade = {**database_trade, "Status": "OPEN", "Live Price": 125}
        db_only_trade = {
            "trade_id": "trade-2",
            "Status": "OPEN",
            "Entry Time": "10:05 AM",
            "Strike": 24550,
        }

        merged = _merge_trade_records(
            "NIFTY",
            [database_trade, db_only_trade],
            [foreground_trade],
            [session_trade],
        )

        self.assertEqual(2, len(merged))
        self.assertEqual("OPEN", merged[0]["Status"])
        self.assertEqual(125, merged[0]["Live Price"])
        self.assertIn(db_only_trade, merged)

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


if __name__ == "__main__":
    unittest.main()
