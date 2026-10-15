"""
Unit tests for AI Copilot module.
"""
import unittest
import os
import sys
from unittest.mock import Mock

from core.ai_copilot import AICopilot
from core.risk_manager import RiskManager
from core.trade_manager import TradeManager
from analytics.trade_journal import TradeJournal


class TestAICopilot(unittest.TestCase):
    def setUp(self):
        self.copilot = AICopilot()
        self.risk_mgr = RiskManager()
        self.trade_mgr = TradeManager(notifier=None, risk_mgr=self.risk_mgr)
        import unittest.mock
        self.trade_mgr.save_log = unittest.mock.MagicMock()
        self.test_journal_file = "test_ai_journal_tmp.json"
        self.journal = TradeJournal(self.test_journal_file)

    def tearDown(self):
        if os.path.exists(self.test_journal_file):
            try:
                os.remove(self.test_journal_file)
            except Exception:
                pass

    def test_configured(self):
        self.assertTrue(self.copilot.is_configured())

    def test_extract_json(self):
        raw_md = '```json\n{"market_bias": "BULLISH", "conviction_score": 85}\n```'
        parsed = self.copilot._extract_json(raw_md)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("market_bias"), "BULLISH")
        self.assertEqual(parsed.get("conviction_score"), 85)

    def test_take_trade_execution(self):
        self.journal.db = Mock()
        mock_md = {
            "spot": 24500.0,
            "atm_actual": 24500,
            "pcr": 1.2,
            "pcr_momentum": "RISING",
            "vwap_proxy": 24480.0,
            "total_ce_delta": 40000,
            "total_pe_delta": 150000,
            "atm_row": {"CE LTP": 120.0, "PE LTP": 95.0},
            "spot_history": [24450, 24470, 24490, 24500],
        }
        tlog = []
        ok, trade, msg = self.copilot.take_trade(
            idx="NIFTY",
            signal_type="BUY CE",
            md=mock_md,
            trade_mgr=self.trade_mgr,
            risk_mgr=self.risk_mgr,
            journal=self.journal,
            tlog=tlog,
            ai_conviction=88,
            ai_reasoning="Strong Put writing at 24500",
            ai_analysis={
                "reasoning_summary": "Put writing supports a bullish setup.",
                "detailed_reasoning": "PCR climbed while put OI increased near ATM.",
                "recommendation": "EXECUTE_BUY_CE",
                "market_bias": "BULLISH",
                "conviction_score": 88,
                "key_factors": ["PCR rising", "Put writing"],
                "risk_warning": "Nearby call resistance.",
                "provider": "Gemini",
            },
            force=True,
        )
        self.assertTrue(ok)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["Index"], "NIFTY")
        self.assertEqual(trade["Signal"], "BUY CE")
        self.assertEqual(trade["Strike"], 24500)
        self.assertEqual(trade["Entry Price"], 120.0)
        self.assertEqual(trade["_ai_conviction"], 88)
        self.assertEqual(trade["_ai_reasoning"], "PCR climbed while put OI increased near ATM.")
        self.assertTrue(trade["_ai_generated"])
        self.assertEqual(len(tlog), 1)
        self.assertEqual(
            "PCR climbed while put OI increased near ATM.",
            self.journal.trades[0]["_ai_reasoning"],
        )
        saved_metadata = self.journal.trades[0]["signal_metadata"]
        self.assertEqual("EXECUTE_BUY_CE", saved_metadata["ai_recommendation"])
        self.assertEqual(["PCR rising", "Put writing"], saved_metadata["ai_key_factors"])
        self.assertEqual("Nearby call resistance.", saved_metadata["ai_risk_flags"][0])
        persisted_trade, persisted_metadata = self.journal.db.upsert_trade.call_args.args
        self.assertEqual(
            "PCR climbed while put OI increased near ATM.",
            persisted_trade["_ai_reasoning"],
        )
        self.assertEqual(
            "EXECUTE_BUY_CE",
            persisted_metadata["ai_recommendation"],
        )


if __name__ == "__main__":
    unittest.main()
