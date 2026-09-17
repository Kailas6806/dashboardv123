"""
Unit test for TradeDB SQLite database.
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from analytics.db import TradeDB


class TestTradeDB(unittest.TestCase):
    def setUp(self):
        self.test_db_path = "test_trades_tmp.db"
        self.db = TradeDB(db_path=self.test_db_path)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def test_upsert_and_retrieve(self):
        trade_data = {
            "trade_id": "TEST_NIFTY_001",
            "date": "2026-09-17",
            "Entry Time": "10:00:00 AM",
            "Index": "NIFTY",
            "Signal": "BUY CE",
            "Spot": 24500.0,
            "Strike": 24500,
            "Entry Price": 120.0,
            "Stop Loss": 105.0,
            "Target": 150.0,
            "Qty": 65,
            "Status": "OPEN",
            "Result": "⏳ OPEN",
            "_ai_generated": True,
            "_ai_conviction": 85,
            "_ai_reasoning": "Test trade",
        }
        tid = self.db.upsert_trade(trade_data)
        self.assertEqual(tid, "TEST_NIFTY_001")

        trades = self.db.get_all_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["Index"], "NIFTY")
        self.assertEqual(trades[0]["Strike"], 24500.0)
        self.assertEqual(trades[0]["Status"], "OPEN")
        self.assertTrue(trades[0]["_ai_generated"])
        self.assertEqual(trades[0]["_ai_conviction"], 85)

    def test_update_trade_exit(self):
        trade_data = {
            "trade_id": "TEST_NIFTY_002",
            "Index": "NIFTY",
            "Signal": "BUY CE",
            "Strike": 24500,
            "Entry Price": 100.0,
            "Qty": 65,
            "Status": "OPEN",
        }
        self.db.upsert_trade(trade_data)

        ok = self.db.update_trade_exit("TEST_NIFTY_002", {
            "Exit Time": "10:30:00 AM",
            "Exit Price": 130.0,
            "Actual P&L ₹": 1950.0,
            "Status": "CLOSED",
            "Result": "🟢 WIN",
        })
        self.assertTrue(ok)

        trades = self.db.get_all_trades(status="CLOSED")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["Exit Price"], 130.0)
        self.assertEqual(trades[0]["Actual P&L ₹"], 1950.0)
        self.assertEqual(trades[0]["Status"], "CLOSED")
        self.assertEqual(trades[0]["Result"], "🟢 WIN")


if __name__ == "__main__":
    unittest.main()
