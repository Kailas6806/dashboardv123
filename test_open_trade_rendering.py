import unittest

from ui.renderer import _merge_trade_records


class TestOpenTradeRendering(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
