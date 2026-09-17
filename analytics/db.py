"""
V12 PRO MAX — SQLite Trade Database
Provides ACID-compliant, durable storage for all trades (Rule-based, AI, and Manual).
Works seamlessly with trade_journal.json and CSV logs for triple-tier redundancy.
"""
import os
import json
import sqlite3
import datetime
import threading
from typing import Any, Dict, List, Optional, Tuple

from config import BASE_DIR, LOG_DIR, JOURNAL_FILE, IST

try:
    from utils.logger import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
            logger.setLevel(logging.INFO)
        return logger

log = get_logger("trade_db")

DB_PATH = os.path.join(BASE_DIR, "trades.db")


class TradeDB:
    """Thread-safe SQLite database manager for trade history and journal entries."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the trades table and indexes if they don't exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        trade_id TEXT PRIMARY KEY,
                        trade_date TEXT,
                        entry_time TEXT,
                        exit_time TEXT,
                        instrument TEXT,
                        signal TEXT,
                        spot REAL,
                        strike REAL,
                        entry_price REAL,
                        live_price REAL,
                        exit_price REAL,
                        stop_loss REAL,
                        target REAL,
                        quantity INTEGER,
                        max_loss REAL,
                        target_pnl REAL,
                        actual_pnl REAL,
                        status TEXT,
                        result TEXT,
                        confidence_score INTEGER,
                        ai_generated INTEGER DEFAULT 0,
                        ai_conviction INTEGER,
                        ai_reasoning TEXT,
                        metadata_json TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_instrument ON trades(instrument)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
                conn.commit()
                log.info("TradeDB initialized at %s", self.db_path)
            finally:
                conn.close()

    @staticmethod
    def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
        if val is None or val == "" or str(val).strip() == "":
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
        if val is None or val == "" or str(val).strip() == "":
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def upsert_trade(
        self,
        trade: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Insert or update a trade record atomically."""
        with self._lock:
            now_ist = datetime.datetime.now(IST)
            idx = str(trade.get("Index") or trade.get("instrument") or "INDEX").upper()
            entry_time = str(trade.get("Entry Time") or trade.get("entry_time") or now_ist.strftime("%I:%M:%S %p"))
            raw_date = str(trade.get("date") or trade.get("trade_date") or trade.get("recorded_at") or now_ist.strftime("%Y-%m-%d"))[:10]
            if not raw_date or len(raw_date) < 10:
                raw_date = now_ist.strftime("%Y-%m-%d")

            strike = self._safe_float(trade.get("Strike") or trade.get("strike"), 0.0)
            signal = str(trade.get("Signal") or trade.get("signal") or "BUY CE").upper()

            # Trade ID generation or preservation
            trade_id = str(trade.get("trade_id") or trade.get("_journal_id") or "")
            if not trade_id:
                clean_time = entry_time.replace(":", "").replace(" ", "").upper()
                trade_id = f"{idx}_{raw_date.replace('-', '')}_{clean_time}"

            created_at = str(trade.get("recorded_at") or trade.get("created_at") or now_ist.isoformat())
            updated_at = now_ist.isoformat()

            ep = self._safe_float(trade.get("Entry Price") or trade.get("entry_price"))
            lp = self._safe_float(trade.get("Live Price") or trade.get("live_price") or ep)
            xp = self._safe_float(trade.get("Exit Price") or trade.get("exit_price"))
            sl = self._safe_float(trade.get("Stop Loss") or trade.get("stop_loss"))
            tgt = self._safe_float(trade.get("Target") or trade.get("target"))
            qty = self._safe_int(trade.get("Qty") or trade.get("quantity"), 0)
            spot = self._safe_float(trade.get("Spot") or trade.get("spot"))
            ml = self._safe_float(trade.get("Max Loss ₹") or trade.get("max_loss"))
            tp = self._safe_float(trade.get("Target P&L ₹") or trade.get("target_pnl"))
            pnl = self._safe_float(trade.get("Actual P&L ₹") or trade.get("actual_pnl"))
            status = str(trade.get("Status") or trade.get("status") or "OPEN").upper()
            result = str(trade.get("Result") or trade.get("result") or ("⏳ OPEN" if status == "OPEN" else "CLOSED"))

            conf = self._safe_int(trade.get("Confidence Score") or trade.get("confidence_score"))
            ai_gen = 1 if bool(trade.get("_ai_generated") or trade.get("ai_generated")) else 0
            ai_conv = self._safe_int(trade.get("_ai_conviction") or trade.get("ai_conviction"))
            ai_reason = str(trade.get("_ai_reasoning") or trade.get("ai_reasoning") or "")

            meta_d = dict(metadata) if metadata else (trade.get("signal_metadata") or {})
            meta_json = json.dumps(meta_d) if meta_d else "{}"

            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO trades (
                        trade_id, trade_date, entry_time, exit_time, instrument, signal,
                        spot, strike, entry_price, live_price, exit_price, stop_loss, target,
                        quantity, max_loss, target_pnl, actual_pnl, status, result,
                        confidence_score, ai_generated, ai_conviction, ai_reasoning,
                        metadata_json, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(trade_id) DO UPDATE SET
                        exit_time = COALESCE(excluded.exit_time, trades.exit_time),
                        live_price = excluded.live_price,
                        exit_price = COALESCE(excluded.exit_price, trades.exit_price),
                        actual_pnl = COALESCE(excluded.actual_pnl, trades.actual_pnl),
                        status = excluded.status,
                        result = excluded.result,
                        updated_at = excluded.updated_at
                """, (
                    trade_id, raw_date, entry_time, trade.get("Exit Time") or trade.get("exit_time"),
                    idx, signal, spot, strike, ep, lp, xp, sl, tgt, qty, ml, tp, pnl,
                    status, result, conf, ai_gen, ai_conv, ai_reason, meta_json,
                    created_at, updated_at
                ))
                conn.commit()
                return trade_id
            finally:
                conn.close()

    def update_trade_exit(
        self,
        trade_id: str,
        exit_data: Dict[str, Any],
        trade_dict: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update an existing trade with exit information."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_ist = datetime.datetime.now(IST).isoformat()
                exit_time = exit_data.get("Exit Time") or exit_data.get("exit_time")
                exit_price = self._safe_float(exit_data.get("Exit Price") or exit_data.get("exit_price"))
                actual_pnl = self._safe_float(exit_data.get("Actual P&L ₹") or exit_data.get("actual_pnl"))
                status = str(exit_data.get("Status") or exit_data.get("status") or "CLOSED").upper()
                result = str(exit_data.get("Result") or exit_data.get("result") or "CLOSED")

                if trade_id:
                    cursor.execute("""
                        UPDATE trades SET
                            exit_time = COALESCE(?, exit_time),
                            exit_price = COALESCE(?, exit_price),
                            live_price = COALESCE(?, live_price),
                            actual_pnl = COALESCE(?, actual_pnl),
                            status = ?,
                            result = ?,
                            updated_at = ?
                        WHERE trade_id = ?
                    """, (exit_time, exit_price, exit_price, actual_pnl, status, result, now_ist, trade_id))
                    if cursor.rowcount > 0:
                        conn.commit()
                        return True

                # Fallback: Match by instrument, strike, signal and entry_time if trade_dict provided
                if trade_dict:
                    idx = str(trade_dict.get("Index") or trade_dict.get("instrument") or "").upper()
                    strike = self._safe_float(trade_dict.get("Strike") or trade_dict.get("strike"))
                    etime = trade_dict.get("Entry Time")
                    sig = trade_dict.get("Signal")
                    cursor.execute("""
                        UPDATE trades SET
                            exit_time = COALESCE(?, exit_time),
                            exit_price = COALESCE(?, exit_price),
                            live_price = COALESCE(?, live_price),
                            actual_pnl = COALESCE(?, actual_pnl),
                            status = ?,
                            result = ?,
                            updated_at = ?
                        WHERE instrument = ? AND strike = ? AND entry_time = ? AND signal = ?
                    """, (exit_time, exit_price, exit_price, actual_pnl, status, result, now_ist, idx, strike, etime, sig))
                    if cursor.rowcount > 0:
                        conn.commit()
                        return True

                return False
            finally:
                conn.close()

    def get_all_trades(
        self,
        status: Optional[str] = None,
        instrument: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve all trades formatted for the dashboard and journal."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM trades WHERE 1=1"
                params = []
                if status:
                    query += " AND status = ?"
                    params.append(status.upper())
                if instrument and instrument != "ALL":
                    query += " AND instrument = ?"
                    params.append(instrument.upper())
                query += " ORDER BY trade_date DESC, entry_time DESC, created_at DESC"
                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    t = dict(row)
                    # Convert to V12 LOG_COLS standard format
                    trade_dict = {
                        "trade_id": t["trade_id"],
                        "Entry Time": t["entry_time"],
                        "Exit Time": t["exit_time"],
                        "Index": t["instrument"],
                        "Signal": t["signal"],
                        "Spot": t["spot"],
                        "Strike": t["strike"],
                        "Entry Price": t["entry_price"],
                        "Live Price": t["live_price"],
                        "Exit Price": t["exit_price"],
                        "Stop Loss": t["stop_loss"],
                        "Target": t["target"],
                        "Qty": t["quantity"],
                        "Max Loss ₹": t["max_loss"],
                        "Target P&L ₹": t["target_pnl"],
                        "Actual P&L ₹": t["actual_pnl"],
                        "Status": t["status"],
                        "Result": t["result"],
                        "Confidence Score": t["confidence_score"],
                        "_ai_generated": bool(t["ai_generated"]),
                        "_ai_conviction": t["ai_conviction"],
                        "_ai_reasoning": t["ai_reasoning"],
                        "recorded_at": t["created_at"],
                        "date": t["trade_date"],
                        "signal_metadata": json.loads(t["metadata_json"]) if t["metadata_json"] else {},
                    }
                    results.append(trade_dict)
                return results
            finally:
                conn.close()

    def sync_from_json_and_csv(self) -> int:
        """Proactively import all trades from trade_journal.json and all CSV logs into SQLite."""
        imported = 0
        # 1. Sync from trade_journal.json
        if os.path.exists(JOURNAL_FILE):
            try:
                with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                    j_trades = json.load(f)
                if isinstance(j_trades, list):
                    for jt in j_trades:
                        self.upsert_trade(jt, jt.get("signal_metadata"))
                        imported += 1
            except Exception as e:
                log.warning("Sync from journal failed: %s", e)

        # 2. Sync from CSV logs
        try:
            import glob
            import pandas as pd
            search_dirs = [LOG_DIR, BASE_DIR]
            csv_files = []
            for d in search_dirs:
                if os.path.isdir(d):
                    csv_files.extend(glob.glob(os.path.join(d, "trade_log_*.csv")))
            for fpath in set(csv_files):
                fname = os.path.basename(fpath)
                parts = fname.replace(".csv", "").split("_")
                if len(parts) < 4:
                    continue
                d_str = parts[3]
                try:
                    df = pd.read_csv(fpath, encoding="utf-8")
                    for _, row in df.iterrows():
                        r_dict = row.to_dict()
                        r_dict["date"] = d_str
                        self.upsert_trade(r_dict)
                        imported += 1
                except Exception:
                    pass
        except Exception as e:
            log.warning("Sync from CSV failed: %s", e)

        log.info("Synced %d total trade entries into TradeDB", imported)
        return imported
