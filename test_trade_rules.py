"""
Unit test suite verifying:
1. Stop loss strictly capped at <= MAX_LOSS (₹1,500) under all conditions (including large ATR).
2. Profit target set based on DAILY_TGT (₹3,000 / 1:2 R:R).
3. Max daily trades limit across the portfolio (MAX_DAILY_TRADES = 10).
4. Cumulative daily loss limit across the portfolio (MAX_DAILY_LOSS = ₹9,000).
5. Dynamic R-Multiple Trailing Profit Lock:
   - When trade reaches 1:2 R or higher, SL is moved to lock guaranteed profit.
   - Pullback triggers exit with locked profit (PROFIT_LOCKED_EXIT).
"""
import datetime
import unittest
from config import (
    IST, MAX_LOSS, MAX_DAILY_LOSS, DAILY_TGT, MAX_DAILY_TRADES,
)
from core.risk_manager import RiskManager
from core.trade_manager import TradeManager


class DummyNotifier:
    def __init__(self):
        self.messages = []

    def send(self, msg: str):
        self.messages.append(msg)

    def send_signal_alert(self, **kwargs):
        self.messages.append(f"SIGNAL_ALERT: {kwargs}")


class TestTradeRules(unittest.TestCase):
    def setUp(self):
        self.risk_mgr = RiskManager()
        self.notifier = DummyNotifier()
        self.trade_mgr = TradeManager(self.notifier, self.risk_mgr)

    def test_fixed_sl_capped(self):
        """Fixed SL must produce max loss <= MAX_LOSS for all index lot sizes."""
        for lot in [65, 30, 60]:  # NIFTY, BANKNIFTY, FINNIFTY
            qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade(ep=200.0, lot=lot)
            self.assertEqual(qty, lot)
            self.assertLessEqual(ml, MAX_LOSS)
            self.assertGreaterEqual(tp, DAILY_TGT - 1.0)
            actual_loss = round((200.0 - sl_p) * qty, 2)
            self.assertLessEqual(actual_loss, MAX_LOSS)

    def test_atr_sl_strictly_clamped(self):
        """Even with huge spot ATR, SL must never exceed MAX_LOSS."""
        huge_atr_history = [24000.0 + (100.0 if i % 2 == 0 else 0.0) for i in range(20)]
        for lot in [65, 30, 60]:
            qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade_with_atr(
                ep=250.0, lot=lot, spot_history=huge_atr_history
            )
            self.assertLessEqual(ml, MAX_LOSS, f"Max loss exceeded ₹{MAX_LOSS} for lot {lot}: {ml}")
            actual_loss = round((250.0 - sl_p) * qty, 2)
            self.assertLessEqual(actual_loss, MAX_LOSS, f"Calculated loss {actual_loss} > {MAX_LOSS} for lot {lot}")
            self.assertGreaterEqual(tp, DAILY_TGT - 1.0)

    def test_max_daily_trades_limit(self):
        """Portfolio should block new trades when MAX_DAILY_TRADES limit is reached."""
        now = datetime.datetime.now(IST)
        # 9 trades: allowed
        trades = [
            {"Entry Time": f"09:{i:02d}:00 AM", "Status": "CLOSED", "Actual P&L ₹": 100, "Result": "🟢 WIN"}
            for i in range(MAX_DAILY_TRADES - 1)
        ]
        allowed, _ = self.risk_mgr.check_daily_limits(trades)
        self.assertTrue(allowed)

        # 10 trades: blocked!
        trades.append(
            {"Entry Time": "11:00:00 AM", "Status": "CLOSED", "Actual P&L ₹": 100, "Result": "🟢 WIN"}
        )
        allowed, reason = self.risk_mgr.check_daily_limits(trades)
        self.assertFalse(allowed)
        self.assertIn(f"Daily limit reached: {MAX_DAILY_TRADES}/{MAX_DAILY_TRADES}", reason)

        # Verify should_allow_trade respects portfolio_trades
        allowed_should, reason_should = self.risk_mgr.should_allow_trade(
            "NIFTY", [], now, portfolio_trades=trades
        )
        self.assertFalse(allowed_should)
        self.assertIn(f"Daily limit reached: {MAX_DAILY_TRADES}/{MAX_DAILY_TRADES}", reason_should)

    def test_daily_loss_limit(self):
        """Portfolio loss limit blocks trading when losses reach MAX_DAILY_LOSS."""
        # Losses below limit: allowed
        trades = [
            {"Entry Time": "09:30:00 AM", "Status": "CLOSED", "Actual P&L ₹": -2000.0, "Result": "🔴 LOSS"},
        ]
        allowed, _ = self.risk_mgr.check_daily_limits(trades)
        self.assertTrue(allowed)

        # Losses reaching MAX_DAILY_LOSS: blocked
        trades.append(
            {"Entry Time": "10:30:00 AM", "Status": "CLOSED", "Actual P&L ₹": -(MAX_DAILY_LOSS + 100), "Result": "🔴 LOSS"},
        )
        allowed, reason = self.risk_mgr.check_daily_limits(trades)
        self.assertFalse(allowed)
        self.assertIn("Max daily portfolio loss reached", reason)

    def test_dynamic_r_trailing_profit_lock(self):
        """
        Verify dynamic R-multiple trailing:
        1. Entry @ 100 with qty 30.
        2. Target @ 200 (Risk = (200-100)/2 = 50 pts, 1R = 50 pts).
        3. When price reaches 210 (profit 110 pts >= 2R = 100 pts):
           Trailing SL locks at 1R = 150.0.
        4. Pullback to 145 triggers PROFIT_LOCKED_EXIT with secured profit!
        """
        now = datetime.datetime.now(IST).replace(hour=10, minute=30)
        lot = 30
        ep = 100.0
        tgt = 200.0
        sl = 50.0

        trade = {
            "Entry Time": "10:30:00 AM",
            "Exit Time": None,
            "Index": "BANKNIFTY",
            "Signal": "BUY CE",
            "Spot": 51000.0,
            "Strike": 51000,
            "Entry Price": ep,
            "Live Price": ep,
            "Exit Price": None,
            "Stop Loss": sl,
            "Target": tgt,
            "Qty": lot,
            "Max Loss ₹": 1500,
            "Target P&L ₹": 3000,
            "Actual P&L ₹": None,
            "Status": "OPEN",
            "Result": "⏳ OPEN",
            "_profit_locked": False,
            "_locked_profit": 0,
            "_peak_price": ep,
        }
        trade_log = [trade]

        # Step 1: Price reaches 210 (+110 pts >= 2R = 100 pts) -> SL locks at 1R (150.0)
        records = {51000.0: {"CE": {"lastPrice": 210.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 0, "Trade should stay OPEN while above trailing SL")
        self.assertTrue(trade.get("_profit_locked"))
        self.assertEqual(trade["Stop Loss"], 150.0)
        self.assertEqual(trade["_locked_profit"], 1500.0)

        # Step 2: Price pulls back to 148 (below 150 trailing SL) -> Exits with locked profit
        records = {51000.0: {"CE": {"lastPrice": 148.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "PROFIT_LOCKED_EXIT")
        self.assertEqual(trade["Status"], "CLOSED")
        self.assertEqual(trade["Result"], "🟢 WIN (LOCKED)")
        self.assertEqual(trade["Actual P&L ₹"], 1440.0)


if __name__ == "__main__":
    unittest.main()
