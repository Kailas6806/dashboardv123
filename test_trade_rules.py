"""
Unit test suite verifying:
1. Stop loss strictly capped at <= ₹1,000 under all conditions (including large ATR).
2. Profit target set to ₹4,000.
3. Max 3 trades per day across the portfolio.
4. Cumulative daily loss limit at ₹2,000 (allows 2nd/3rd trade after 1 loss).
5. Step Trailing Profit Lock:
   - Locks SL at +₹2,000 when profit reaches ₹2,000 (trade stays open).
   - Increases SL to +₹3,000 when profit reaches ₹3,000 (trade stays open).
   - Pullback triggers exit with locked profit.
6. Max Profit Exit:
   - Exits immediately at +₹4,000 profit (TARGET 4K HIT).
"""
import datetime
import unittest
from config import (
    IST, MAX_LOSS, MAX_DAILY_LOSS, DAILY_TGT, MAX_DAILY_TRADES,
    PROFIT_LOCK_START, PROFIT_LOCK_STEP, MAX_PROFIT_EXIT,
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

    def test_fixed_sl_capped_at_1000(self):
        """Fixed SL must produce max loss <= ₹1,000 for all index lot sizes."""
        for lot in [65, 30, 60]:  # NIFTY, BANKNIFTY, FINNIFTY
            qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade(ep=200.0, lot=lot)
            self.assertEqual(qty, lot)
            self.assertLessEqual(ml, 1000.0)
            self.assertGreaterEqual(tp, 4000.0)
            # Calculated loss if sl_p is hit
            actual_loss = round((200.0 - sl_p) * qty, 2)
            self.assertLessEqual(actual_loss, 1000.0)

    def test_atr_sl_strictly_clamped_to_1000(self):
        """Even with huge spot ATR, SL must never exceed ₹1,000."""
        # Spot history with wild swings: 100 pt moves
        huge_atr_history = [24000.0 + (100.0 if i % 2 == 0 else 0.0) for i in range(20)]
        for lot in [65, 30, 60]:
            qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade_with_atr(
                ep=250.0, lot=lot, spot_history=huge_atr_history
            )
            self.assertLessEqual(ml, 1000.0, f"Max loss exceeded ₹1000 for lot {lot}: {ml}")
            actual_loss = round((250.0 - sl_p) * qty, 2)
            self.assertLessEqual(actual_loss, 1000.0, f"Calculated loss {actual_loss} > 1000 for lot {lot}")
            self.assertGreaterEqual(tp, 4000.0)

    def test_max_3_trades_limit(self):
        """Portfolio should block new trades when 3 trades have already been taken."""
        now = datetime.datetime.now(IST)
        # 2 trades: allowed
        trades = [
            {"Entry Time": "09:30:00 AM", "Status": "CLOSED", "Actual P&L ₹": 500, "Result": "🟢 WIN"},
            {"Entry Time": "10:15:00 AM", "Status": "CLOSED", "Actual P&L ₹": -400, "Result": "🔴 LOSS"},
        ]
        allowed, _ = self.risk_mgr.check_daily_limits(trades)
        self.assertTrue(allowed)

        # 3 trades: blocked!
        trades.append(
            {"Entry Time": "11:00:00 AM", "Status": "CLOSED", "Actual P&L ₹": 800, "Result": "🟢 WIN"}
        )
        allowed, reason = self.risk_mgr.check_daily_limits(trades)
        self.assertFalse(allowed)
        self.assertIn("Daily limit reached: 3/3", reason)

        # Verify should_allow_trade respects portfolio_trades
        allowed_should, reason_should = self.risk_mgr.should_allow_trade(
            "NIFTY", [], now, portfolio_trades=trades
        )
        self.assertFalse(allowed_should)
        self.assertIn("Daily limit reached: 3/3", reason_should)

    def test_daily_loss_limit_at_2000(self):
        """Single ₹1,000 loss should NOT block next trade; ₹2,000 loss SHOULD block."""
        # 1 loss of -₹999: should still be allowed
        trades = [
            {"Entry Time": "09:30:00 AM", "Status": "CLOSED", "Actual P&L ₹": -999.0, "Result": "🔴 LOSS"},
        ]
        allowed, _ = self.risk_mgr.check_daily_limits(trades)
        self.assertTrue(allowed, "1 loss of ₹1,000 must not block trading for the day (allow 2nd/3rd trade)")

        # 2 losses totaling -₹2,000: should be blocked
        trades.append(
            {"Entry Time": "10:30:00 AM", "Status": "CLOSED", "Actual P&L ₹": -1001.0, "Result": "🔴 LOSS"},
        )
        allowed, reason = self.risk_mgr.check_daily_limits(trades)
        self.assertFalse(allowed)
        self.assertIn("Max daily loss reached", reason)

    def test_step_trailing_profit_lock_2k_and_3k(self):
        """
        Verify step trailing:
        1. Entry @ 100 with qty 30.
        2. Price rises to 170 (+₹2,100) -> SL moves to +₹2,000 (166.67), stays OPEN.
        3. Price rises to 205 (+₹3,150) -> SL moves to +₹3,000 (200.00), stays OPEN.
        4. Price pulls back to 198 (below 200) -> Exits with WIN (LOCKED) at +₹2,940!
        """
        now = datetime.datetime.now(IST).replace(hour=10, minute=30)
        lot = 30
        ep = 100.0
        qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade(ep=ep, lot=lot)

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
            "Stop Loss": sl_p,
            "Target": tgt_p,
            "Qty": qty,
            "Max Loss ₹": ml,
            "Target P&L ₹": tp,
            "Actual P&L ₹": None,
            "Status": "OPEN",
            "Result": "⏳ OPEN",
            "_profit_locked": False,
            "_locked_profit": 0,
            "_peak_price": ep,
        }
        trade_log = [trade]

        # Step 2: Price reaches 170 (+₹2,100) -> First lock at ₹2,000
        records = {51000.0: {"CE": {"lastPrice": 170.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 0, "Trade should stay OPEN to capture more upside")
        self.assertTrue(trade["_profit_locked"])
        self.assertEqual(trade["_locked_profit"], 2000)
        expected_sl_2k = round(100.0 + (2000.0 / 30), 2)  # 166.67
        self.assertEqual(trade["Stop Loss"], expected_sl_2k)

        # Step 3: Price reaches 205 (+₹3,150) -> Second lock at ₹3,000!
        records = {51000.0: {"CE": {"lastPrice": 205.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 0, "Trade should stay OPEN to ride further")
        self.assertEqual(trade["_locked_profit"], 3000)
        expected_sl_3k = round(100.0 + (3000.0 / 30), 2)  # 200.00
        self.assertEqual(trade["Stop Loss"], expected_sl_3k)

        # Step 4: Price pulls back to 198 (below 200 SL) -> Exits with locked profit!
        records = {51000.0: {"CE": {"lastPrice": 198.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "PROFIT_LOCKED_EXIT")
        self.assertEqual(trade["Status"], "CLOSED")
        self.assertEqual(trade["Result"], "🟢 WIN (LOCKED)")
        self.assertEqual(trade["Actual P&L ₹"], 2940.0)

    def test_max_profit_exit_at_4k(self):
        """When profit reaches +₹4,000, trade must immediately EXIT with full profit."""
        now = datetime.datetime.now(IST).replace(hour=10, minute=30)
        lot = 30
        ep = 100.0
        qty, sl_p, tgt_p, ml, tp = self.risk_mgr.calc_trade(ep=ep, lot=lot)

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
            "Stop Loss": sl_p,
            "Target": tgt_p,
            "Qty": qty,
            "Max Loss ₹": ml,
            "Target P&L ₹": tp,
            "Actual P&L ₹": None,
            "Status": "OPEN",
            "Result": "⏳ OPEN",
            "_profit_locked": False,
            "_locked_profit": 0,
            "_peak_price": ep,
        }
        trade_log = [trade]

        # Price reaches 234 (+₹4,020 >= 4000) -> Immediate 4k Exit!
        records = {51000.0: {"CE": {"lastPrice": 234.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "TARGET_4K_HIT")
        self.assertEqual(trade["Status"], "CLOSED")
        self.assertEqual(trade["Result"], "🟢 WIN (TARGET 4K HIT)")
        self.assertEqual(trade["Exit Price"], 234.0)
        self.assertEqual(trade["Actual P&L ₹"], 4020.0)


if __name__ == "__main__":
    unittest.main()
