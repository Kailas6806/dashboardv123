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
from config import IST, MARKET_OPEN_TIME, MARKET_CLOSE_TIME, INDEX_CONFIG, ENABLE_BACKGROUND_SCANNER

log = get_logger("background_daemon")

def main():
    if not ENABLE_BACKGROUND_SCANNER:
        print("[!] Automatic multi-index scanner is disabled by ENABLE_BACKGROUND_SCANNER.")
        return

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
        from core.foreground_scanner import run_foreground_market_scan, get_scanner_status
        from core.signal_audit import get_signal_auditor

        print("[*] Initializing core modules & Angel One API...")
        fetcher = get_fetcher()
        signal_engine = SignalEngine()
        risk_mgr = RiskManager()
        trade_mgr = TradeManager(notifier=None, risk_mgr=risk_mgr)
        journal = TradeJournal()
        copilot = AICopilot()
        auditor = get_signal_auditor()

        print("[*] Starting sequential multi-index market scanning loop...")
        print("[+] Scanner is ACTIVE and monitoring all indices (NIFTY, BANKNIFTY, FINNIFTY).")
        print("[+] Logs are recorded to logs/v12.log and logs/signal_audit.jsonl")
        print("[+] Press Ctrl+C at any time to stop.\n")

        last_report_ts = 0.0
        while True:
            run_foreground_market_scan(
                fetcher=fetcher,
                signal_engine=signal_engine,
                risk_mgr=risk_mgr,
                trade_mgr=trade_mgr,
                journal=journal,
                copilot=copilot,
                ai_auto_trade=True,
                force=True,
            )
            time.sleep(3)
            now_ist = datetime.datetime.now(IST)
            now_ts = time.time()

            # Print a clean 30-second heartbeat in terminal
            if now_ts - last_report_ts >= 30.0:
                last_report_ts = now_ts
                status = get_scanner_status()
                stats = auditor.get_audit_stats()
                tot = stats.get("total_setups", 0)
                exec_count = stats.get("executed", 0)
                rej_count = stats.get("rejected", 0)

                # Format real-time index signals and XGBoost observed probabilities
                from core.foreground_scanner import get_latest_index_state
                idx_summaries = []
                for _idx in INDEX_CONFIG:
                    st_snap = get_latest_index_state(_idx) or {}
                    sig = st_snap.get("final_signal", "WAIT")
                    prob = st_snap.get("ml_probability")
                    if prob is not None:
                        idx_summaries.append(f"{_idx}: {sig} [XGB: {prob*100:.1f}%]")
                    else:
                        idx_summaries.append(f"{_idx}: {sig}")

                print(
                    f"[{now_ist.strftime('%I:%M:%S %p')}] "
                    f"Scans: {status.get('total_scans', 0):,} | " + " | ".join(idx_summaries) + f" | Evaluated: {tot} | Exec: {exec_count}"
                )

    except KeyboardInterrupt:
        print("\n[*] Stopping scanner...")
        print("[+] Safely stopped.")
    except Exception as e:
        log.error(f"Fatal error in background daemon: {e}", exc_info=True)
        print(f"\n[!] Error: {e}")

if __name__ == "__main__":
    main()
