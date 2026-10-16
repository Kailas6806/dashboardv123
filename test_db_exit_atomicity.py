import threading
import unittest
from unittest.mock import MagicMock, patch

from analytics.db import TradeDB


class TestTradeExitAtomicity(unittest.TestCase):
    def test_capital_fallback_is_marked_as_process_local(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()

        with (
            patch.object(db, "_get_connection", side_effect=RuntimeError("database unavailable")),
            patch.object(
                db,
                "_load_local_capital_cache",
                return_value={"base_capital": 60000.0, "current_balance": 60100.0},
            ),
        ):
            capital = db.get_or_init_capital()

        self.assertEqual("local_cache", capital["_source"])

    def test_duplicate_exit_updates_capital_only_once(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()

        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"trade_id": "trade-1"},
            {
                "account_id": "DEFAULT",
                "base_capital": 60000.0,
                "cumulative_realized_pnl": 250.0,
                "current_balance": 60250.0,
            },
            None,
        ]
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with (
            patch.object(db, "_get_connection", return_value=connection),
            patch.object(db, "_save_local_capital_cache") as save_capital_cache,
        ):
            first_result = db.update_trade_exit(
                "trade-1",
                {
                    "Exit Time": "10:00 AM",
                    "Exit Price": 105.0,
                    "Actual P&L ₹": 250.0,
                    "Status": "CLOSED",
                    "Result": "WIN",
                },
            )
            second_result = db.update_trade_exit(
                "trade-1",
                {
                    "Exit Time": "10:00 AM",
                    "Exit Price": 105.0,
                    "Actual P&L ₹": 250.0,
                    "Status": "CLOSED",
                    "Result": "WIN",
                },
            )

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(1, connection.commit.call_count)
        self.assertEqual(1, save_capital_cache.call_count)
        capital_updates = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if "INSERT INTO account_capital" in call.args[0]
        ]
        self.assertEqual(1, len(capital_updates))
        self.assertIn("AND status = 'OPEN'", cursor.execute.call_args_list[0].args[0])

    def test_live_price_update_requires_newer_open_trade_quote(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()
        cursor = MagicMock()
        cursor.rowcount = 1
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with patch.object(db, "_get_connection", return_value=connection):
            updated = db.update_trade_live_price("trade-1", 123.45, 1000.0)

        self.assertTrue(updated)
        query, params = cursor.execute.call_args.args
        self.assertIn("live_price_updated_at < to_timestamp(%s)", query)
        self.assertIn("status = 'OPEN'", query)
        self.assertEqual((123.45, 1000.0, "trade-1", 1000.0), params)
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
