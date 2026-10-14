"""
V12 PRO MAX — Dedicated Standalone Background Trading Daemon
Runs continuously in the background during market hours (9:15 AM - 3:30 PM),
scanning NIFTY, BANKNIFTY, and FINNIFTY.

Executes autonomous AI paper/live trades, maintains Stop Loss / Target trailing,
and logs all signal evaluations & rejections to the Signal Audit Log.
"""
import os
import sys
import time
import datetime
import logging

from utils.logger import get_logger
from config import IST, MARKET_OPEN_TIME, MARKET_CLOSE_TIME, INDEX_CONFIG

log = get_logger("background_daemon")

def main():
    print("=" * 65)
    print("  V12 PRO MAX — Autonomous Background Scanner & Audit Engine  ")
    print("=" * 65)

    try:
        from core.angelone_fetcher import get_fetcher
        from core.signal_engine import SignalEngine
        from core.risk_manager import RiskManager
        from core.trade_manager import TradeManager
        from analytics.trade_journal import TradeJournal
        from core.ai_copilot import AICopilot
        from core.background_engine import get_background_engine

        print("[*] Initializing core modules & Angel One API...")
        fetcher = get_fetcher()
        signal_engine = SignalEngine()
        risk_mgr = RiskManager()
        trade_mgr = TradeManager(notifier=None, risk_mgr=risk_mgr)
        journal = TradeJournal()
        copilot = AICopilot()

        bg_engine = get_background_engine(
            fetcher=fetcher,
            signal_engine=signal_engine,
            risk_mgr=risk_mgr,
            trade_mgr=trade_mgr,
            journal=journal,
            copilot=copilot,
        )

        bg_engine.ai_auto_trade = True
        print("[*] Starting background scanner daemon thread...")
        bg_engine.start()
        print("[+] Background Trading Engine is ACTIVE and monitoring all indices.")
        print("[+] Logs are recorded to logs/v12.log and logs/signal_audit.jsonl")
        print("[+] Press Ctrl+C at any time to stop.\n")

        last_report_ts = 0.0
        while True:
            time.sleep(5)
            now_ist = datetime.datetime.now(IST)
            now_ts = time.time()

            # Print a clean 30-second heartbeat in terminal
            if now_ts - last_report_ts >= 30.0:
                last_report_ts = now_ts
                scans = bg_engine.total_scans
                stats = bg_engine.get_audit_stats()
                tot = stats.get("total_setups", 0)
                exec_count = stats.get("executed", 0)
                rej_count = stats.get("rejected", 0)

                print(
                    f"[{now_ist.strftime('%I:%M:%S %p')}] "
                    f"Scans: {scans:,} | Setups Evaluated: {tot} | "
                    f"Executed: {exec_count} | Filtered: {rej_count} | "
                    f"Status: {bg_engine.engine_status}"
                )

    except KeyboardInterrupt:
        print("\n[*] Stopping background daemon...")
        if 'bg_engine' in locals():
            bg_engine.stop()
        print("[+] Daemon safely stopped.")
    except Exception as e:
        log.error(f"Fatal error in background daemon: {e}", exc_info=True)
        print(f"\n[!] Error: {e}")

if __name__ == "__main__":
    main()
