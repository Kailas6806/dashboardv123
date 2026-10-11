"""
Test that Trade Analytics uses Supabase PostgreSQL database as primary source.
"""
import unittest
from datetime import datetime, timedelta
from config import IST
from analytics.db import TradeDB
from analytics.trade_journal import TradeJournal

class TestAnalyticsSupabase(unittest.TestCase):

    def setUp(self):
        self.db = TradeDB()
        self.test_trade = {
            "trade_id": "TEST_ANALYTICS_001",
            "date": datetime.now(tz=IST).strftime("%Y-%m-%d"),
            "Entry Time": "10:00:00 AM",
            "Exit Time": "10:15:00 AM",
            "Index": "NIFTY",
            "Signal": "BUY CE",
            "Strike": 24500,
            "Entry Price": 100.0,
            "Exit Price": 120.0,
            "Qty": 65,
            "Actual P&L ₹": 1300.0,
            "Status": "CLOSED",
            "Result": "🟢 WIN",
        }
        self.db.upsert_trade(self.test_trade)
        self.journal = TradeJournal()

    def tearDown(self):
        try:
            conn = self.db._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM trades WHERE trade_id = 'TEST_ANALYTICS_001'")
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        try:
            self.journal.get_all_trades()
        except Exception:
            pass

    def test_journal_loads_from_supabase(self):
        """Verify TradeJournal loads all trades directly from Supabase."""
        db_trades = self.db.get_all_trades()
        self.assertGreater(len(db_trades), 0, "Supabase DB should have stored trades")
        
        journal_trades = self.journal.get_all_trades()
        self.assertEqual(len(journal_trades), len(db_trades), "Journal must match Supabase trade count")

    def test_analytics_computes_from_supabase_trades(self):
        """Verify get_analytics computes metrics across Supabase trades."""
        analytics = self.journal.get_analytics(days=36500)
        self.assertIn("total_trades", analytics)
        self.assertIn("total_pnl", analytics)
        self.assertIn("win_rate", analytics)
        self.assertIn("by_index", analytics)
        self.assertGreater(analytics["total_trades"], 0)
        print("Analytics computed successfully from Supabase:", {
            "total_trades": analytics["total_trades"],
            "wins": analytics["wins"],
            "losses": analytics["losses"],
            "win_rate": analytics["win_rate"],
            "total_pnl": analytics["total_pnl"],
        })

    def test_filter_since_with_trade_list(self):
        """Verify date filtering works accurately across multi-day trade history."""
        db_trades = self.db.get_all_trades()
        cutoff_future = datetime.now(tz=IST) + timedelta(days=1)
        future_trades = self.journal._filter_since(cutoff_future, trade_list=db_trades)
        self.assertEqual(len(future_trades), 0, "No trades should be in the future")

        cutoff_past = datetime.now(tz=IST) - timedelta(days=365)
        past_trades = self.journal._filter_since(cutoff_past, trade_list=db_trades)
        self.assertGreater(len(past_trades), 0, "Trades within past year should be returned")

if __name__ == "__main__":
    unittest.main()
