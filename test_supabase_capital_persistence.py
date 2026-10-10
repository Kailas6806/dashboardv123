"""
Verification Test for Supabase Capital Persistence
Validates:
1. Base capital is ₹60,000
2. Supabase account_capital table stores wallet balance
3. When Streamlit restarts / sleeps, capital is restored from Supabase without resetting
4. Trade exit P&L updates wallet balance in real time
"""
import os
import unittest
from analytics.db import TradeDB
from core.risk_manager import RiskManager
from config import CAPITAL

class TestSupabaseCapital(unittest.TestCase):
    def setUp(self):
        self.db = TradeDB()
        self.risk_mgr = RiskManager()

    def test_1_config_capital(self):
        self.assertEqual(CAPITAL, 60000, "Base CAPITAL must be 60,000")

    def test_2_get_or_init_capital(self):
        cap = self.db.get_or_init_capital(default_base=60000.0)
        self.assertIsNotNone(cap)
        self.assertEqual(cap["base_capital"], 60000.0)
        self.assertIn("current_balance", cap)
        self.assertIn("cumulative_realized_pnl", cap)
        print("Fetched Supabase Capital State:", cap)

    def test_3_sleep_restart_persistence(self):
        # 1. Fetch current balance
        initial_cap = self.db.get_or_init_capital(default_base=60000.0)
        initial_bal = initial_cap["current_balance"]

        # 2. Apply a test profit of +₹500
        updated = self.db.apply_trade_pnl_to_capital(500.0)
        self.assertAlmostEqual(updated["current_balance"], initial_bal + 500.0)

        # 3. Simulate Streamlit server sleeping / restarting by destroying TradeDB instance
        del self.db
        new_db = TradeDB()
        restored = new_db.get_or_init_capital(default_base=60000.0)

        # 4. Verify it did NOT reset to 60k
        self.assertAlmostEqual(restored["current_balance"], initial_bal + 500.0)
        print("Restored after simulated sleep/restart:", restored["current_balance"])

        # 5. Clean up the test delta of -₹500 to keep capital clean
        cleaned = new_db.apply_trade_pnl_to_capital(-500.0)
        self.assertAlmostEqual(cleaned["current_balance"], initial_bal)
        print("Capital restored to clean state:", cleaned["current_balance"])

    def test_4_risk_manager_equity_calculation(self):
        cap = self.db.get_or_init_capital(default_base=60000.0)
        base = cap["base_capital"]
        all_time_pnl = cap["cumulative_realized_pnl"]

        trades = [
            {"Status": "OPEN", "Qty": 65, "Entry Price": 100.0, "Live Price": 120.0}, # +1300 unrealized, 6500 margin
            {"Status": "CLOSED", "Actual P&L ₹": 1500.0},
        ]
        stats = self.risk_mgr.calculate_portfolio_equity(base, trades, all_time_pnl=all_time_pnl)
        self.assertEqual(stats["base_capital"], 60000.0)
        self.assertEqual(stats["margin_used"], 6500.0)
        self.assertEqual(stats["unrealized_pnl"], 1300.0)
        expected_cash = 60000.0 + all_time_pnl
        self.assertEqual(stats["cash_balance"], expected_cash)
        self.assertEqual(stats["total_equity"], expected_cash + 1300.0)
        self.assertEqual(stats["available_margin"], expected_cash - 6500.0)
        print("Portfolio Equity Stats:", stats)

if __name__ == "__main__":
    unittest.main()
