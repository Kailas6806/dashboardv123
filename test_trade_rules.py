"""
Unit test suite verifying:
1. Stop loss strictly capped at <= ₹1,000 under all conditions (including large ATR).
2. Profit target set to >= ₹2,000.
3. Max 3 trades per day across the portfolio.
4. Trailing profit lock:
   - Locks SL at +₹2,000 when profit reaches ₹2,000.
   - Keeps trade open to capture further upside.
   - Trails SL higher behind price.
   - Closes with 'WIN (LOCKED)' at >= ₹2,000 profit if price reverses to SL.
"""
import datetime
import unittest
from config import IST, MAX_LOSS, DAILY_TGT, MAX_DAILY_TRADES, PROFIT_LOCK_THRESHOLD
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
            self.assertGreaterEqual(tp, 2000.0)
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
            self.assertGreaterEqual(tp, 2000.0)

    def test_max_3_trades_limit(self):
        """Portfolio should block new trades when 3 trades have already been taken."""
        now = datetime.datetime.now(IST)
        # 0 trades: allowed
        trades = []
        allowed, _ = self.risk_mgr.check_daily_limits(trades)
        self.assertTrue(allowed)

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

        # Also verify should_allow_trade respects portfolio_trades
        allowed_should, reason_should = self.risk_mgr.should_allow_trade(
            "NIFTY", [], now, portfolio_trades=trades
        )
        self.assertFalse(allowed_should)
        self.assertIn("Daily limit reached: 3/3", reason_should)

    def test_trailing_profit_lock_lifecycle(self):
        """
        Verify complete profit lock lifecycle:
        1. Trade enters @ 100 with 30 qty (BANKNIFTY). Initial SL = 66.67 (-1000 loss).
        2. Price rises to 150 -> PnL = (150-100)*30 = +₹1500 (< 2000). Trade still open, not locked.
        3. Price rises to 170 -> PnL = (170-100)*30 = +₹2100 (>= 2000).
           -> Profit lock triggers: SL moved to 100 + (2000/30) = 166.67.
           -> Trade stays OPEN to capture upside!
        4. Price rises further to 200 -> Peak updates, SL trails to 200 - (500/30) = 183.33.
        5. Price reverses to 180 (below trailed SL 183.33):
           -> Exits with 'WIN (LOCKED)'!
           -> Realized PnL = (180-100)*30 = +₹2400 (well above ₹2000!).
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
            "_peak_price": ep,
        }
        trade_log = [trade]

        # Step 2: Price goes to 150 (+₹1,500)
        records = {51000.0: {"CE": {"lastPrice": 150.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 0)
        self.assertEqual(trade["Status"], "OPEN")
        self.assertFalse(trade["_profit_locked"])
        self.assertEqual(trade["Stop Loss"], sl_p)

        # Step 3: Price goes to 170 (+₹2,100) -> PROFIT LOCK TRIGGERS!
        records = {51000.0: {"CE": {"lastPrice": 170.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 0, "Trade should NOT close immediately at ₹2,000; it must ride upside!")
        self.assertEqual(trade["Status"], "OPEN")
        self.assertTrue(trade["_profit_locked"])
        expected_locked_sl = round(100.0 + (2000.0 / 30), 2)  # 166.67
        self.assertEqual(trade["Stop Loss"], expected_locked_sl)
        self.assertEqual(trade["Result"], "🟢 PROFIT LOCKED (+₹2,000)")

        # Step 4: Price climbs to 200 (+₹3,000) -> Trailing SL updates higher!
        records = {51000.0: {"CE": {"lastPrice": 200.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 0)
        self.assertEqual(trade["Status"], "OPEN")
        expected_trailed_sl = round(200.0 - (500.0 / 30), 2)  # 183.33
        self.assertEqual(trade["Stop Loss"], expected_trailed_sl)

        # Step 5: Price pulls back to 180 (drops below 183.33 SL) -> Exit with secured profit!
        records = {51000.0: {"CE": {"lastPrice": 180.0}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "PROFIT_LOCKED_EXIT")
        self.assertEqual(trade["Status"], "CLOSED")
        self.assertEqual(trade["Result"], "🟢 WIN (LOCKED)")
        self.assertEqual(trade["Exit Price"], 180.0)
        self.assertEqual(trade["Actual P&L ₹"], 2400.0)
        self.assertGreaterEqual(trade["Actual P&L ₹"], 2000.0)

    def test_regular_sl_loss_capped_at_1000(self):
        """When price drops without reaching target, loss is capped at ₹1,000."""
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
            "_peak_price": ep,
        }
        trade_log = [trade]
        # Price drops to sl_p
        records = {51000.0: {"CE": {"lastPrice": sl_p}}}
        events = self.trade_mgr.update_live_prices("BANKNIFTY", trade_log, records, now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "SL_HIT")
        self.assertEqual(trade["Status"], "CLOSED")
        self.assertEqual(trade["Result"], "🔴 LOSS")
        self.assertGreaterEqual(trade["Actual P&L ₹"], -1000.0)


if __name__ == "__main__":
    unittest.main()
