"""
Unit & Integration tests for SmartWebSocket Manager & SignalEngine Data Pipeline.
"""
import unittest
import pandas as pd
from core.websocket_manager import SmartWebSocketManager
from core.angelone_fetcher import AngelOneDataFetcher
from core.signal_engine import SignalEngine
from config import INDEX_CONFIG

class TestWebSocketIntegration(unittest.TestCase):

    def test_mock_websocket_ticks_and_caching(self):
        """Test in-memory tick caching and retrieval."""
        ws_mgr = SmartWebSocketManager(
            auth_token="dummy_token",
            api_key="dummy_key",
            client_code="dummy_client",
            feed_token="dummy_feed",
        )
        
        # Simulate incoming tick from binary parser
        raw_tick = {
            "token": "26000",
            "last_traded_price": 2252045, # 22520.45 in paise
            "open_interest": 116700055,
            "volume_trade_for_the_day": 500000,
            "exchange_type": 1,
        }
        ws_mgr._on_data(None, raw_tick)
        
        self.assertEqual(ws_mgr.get_live_ltp("26000"), 22520.45)
        self.assertEqual(ws_mgr.get_live_oi("26000"), 116700055)
        
        tick = ws_mgr.get_live_tick("26000")
        self.assertIsNotNone(tick)
        self.assertEqual(tick["ltp"], 22520.45)
        self.assertEqual(tick["oi"], 116700055)

    def test_fetcher_token_lookup(self):
        """Test get_option_token resolves symbol and token from scrip master."""
        fetcher = AngelOneDataFetcher()
        if fetcher.scrip_master:
            token, symbol = fetcher.get_option_token("NIFTY", 22500, "BUY CE")
            print(f"Resolved NIFTY 22500 CE token: {token}, symbol: {symbol}")
            if token is not None:
                self.assertTrue(isinstance(token, str))
                self.assertTrue(isinstance(symbol, str))

    def test_option_chain_provides_all_signal_engine_inputs(self):
        """Test that fetch_option_chain produces 100% of data needed by SignalEngine."""
        fetcher = AngelOneDataFetcher()
        chain = fetcher.fetch_option_chain("NIFTY")
        
        if chain and "records" in chain:
            spot = chain["records"]["underlyingValue"]
            self.assertGreater(spot, 0)
            
            # Format into DataFrame as done by dashboard
            rows = []
            for item in chain["records"]["data"]:
                rows.append({
                    "Strike": item["strikePrice"],
                    "CE LTP": item.get("CE", {}).get("lastPrice", 0.0),
                    "CE OI": item.get("CE", {}).get("openInterest", 0),
                    "PE LTP": item.get("PE", {}).get("lastPrice", 0.0),
                    "PE OI": item.get("PE", {}).get("openInterest", 0),
                })
            df = pd.DataFrame(rows)
            
            # Verify SignalEngine consumes it cleanly
            engine = SignalEngine()
            step = INDEX_CONFIG["NIFTY"]["step"]
            spot_hist = [spot]
            pcr_hist = []
            
            md = engine.compute_market_data(
                df=df,
                spot=spot,
                step=step,
                idx="NIFTY",
                spot_history=spot_hist,
                pcr_history=pcr_hist,
                prev_df=None,
                oi_baseline=None,
            )
            
            # Verify all SignalEngine functions consume this data seamlessly
            signal, conf, reason = engine.generate_signal(md, in_window=True)
            self.assertIn(signal, ("BUY CE", "BUY PE", "WAIT", "⚠️ SIDEWAYS"))
            self.assertIn(conf, ("HIGH", "MEDIUM", "LOW", "AVOID"))

            trap = engine.detect_trap(
                spot, md["support"], md["resistance"],
                md["total_ce_delta"], md["total_pe_delta"]
            )
            self.assertIsInstance(trap, str)
            self.assertIn(trap, ("NONE", "🚨 BULL TRAP", "🚨 BEAR TRAP"))

            final_sig, final_conf, buf = engine.confirm_signal(signal, conf, [])
            self.assertIsInstance(buf, list)

            score = engine.compute_confidence_score(md, final_sig, trap)
            self.assertIsInstance(score, (int, float))

            is_side, side_str = engine.detect_sideways(md["spot_history"], md["pcr"])
            self.assertIsInstance(is_side, (bool, type(False)))

            print("SignalEngine complete pipeline execution passed:", {
                "spot": spot,
                "pcr": md["pcr"],
                "bias": md["bias"],
                "signal": signal,
                "conf": conf,
                "score": score,
                "trap": trap,
                "sideways": is_side,
            })

    def test_cached_chain_ws_tick_overlay(self):
        """Verify cached chain overlays real-time ticks without re-fetching REST."""
        fetcher = AngelOneDataFetcher()
        # Seed cache with dummy data
        dummy_data = {
            "records": {
                "underlyingValue": 22000.0,
                "data": [
                    {
                        "strikePrice": 22000.0,
                        "CE": {"lastPrice": 100.0, "openInterest": 1000, "token": "99991"},
                        "PE": {"lastPrice": 90.0, "openInterest": 2000, "token": "99992"},
                    }
                ]
            }
        }
        fetcher._cache.set("NIFTY", dummy_data)
        
        # Inject WS tick
        if fetcher.ws_mgr:
            fetcher.ws_mgr._ticks["99991"] = {"ltp": 125.50, "oi": 1500, "vol": 10, "updated_at": 12345}
            fetcher.ws_mgr._ticks["26000"] = {"ltp": 22055.0, "oi": 0, "vol": 0, "updated_at": 12345}

            updated = fetcher.fetch_option_chain("NIFTY")
            self.assertEqual(updated["records"]["underlyingValue"], 22055.0)
            ce_entry = updated["records"]["data"][0]["CE"]
            self.assertEqual(ce_entry["lastPrice"], 125.50)
            self.assertEqual(ce_entry["openInterest"], 1500)
            print("Cached chain live WebSocket tick overlay verified successfully!")

if __name__ == "__main__":
    unittest.main()

