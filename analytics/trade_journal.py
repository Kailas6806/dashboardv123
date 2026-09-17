"""
V12 PRO MAX — Trade Journal
Persistent trade journal that records every trade with full signal metadata
for cross-day analytics and performance tracking.
"""

import json
import os
import logging
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any, Dict, List, Optional

from config import JOURNAL_FILE, IST

logger = logging.getLogger("v12.trade_journal")


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

class TradeJournal:
    """Persistent JSON-backed trade journal with analytics capabilities."""

    # Fields copied from each trade row
    _TRADE_FIELDS = [
        "Entry Time", "Exit Time", "Index", "Signal", "Spot", "Strike",
        "Entry Price", "Live Price", "Exit Price",
        "Stop Loss", "Target", "Qty", "Max Loss ₹", "Target P&L ₹",
        "Actual P&L ₹", "Status", "Result", "Confidence Score",
    ]

    def __init__(self, journal_path: Optional[str] = None) -> None:
        """Initialise the journal, loading existing data if available.

        Args:
            journal_path: Path to the JSON journal file.
                          Defaults to ``config.JOURNAL_FILE``.
        """
        self._lock = threading.RLock()
        self.journal_path: str = journal_path or JOURNAL_FILE
        self.trades: List[Dict[str, Any]] = []
        self._load_failed = False
        self.db = None
        try:
            from analytics.db import TradeDB
            self.db = TradeDB()
        except Exception as e:
            logger.warning("TradeDB init in TradeJournal: %s", e)
        self._load()
        if not self._load_failed and (journal_path is None or journal_path == JOURNAL_FILE):
            self._import_from_csv()
            self._reconcile_stale_open_trades()

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_strike(val: Any) -> str:
        """Normalize strike to a consistent string for comparison.

        Handles int (54900), float (54900.0), and string ('54900.0') inputs,
        always returning '54900'.
        """
        try:
            return str(int(float(val)))
        except (ValueError, TypeError):
            return str(val)

    def _trade_exists(
        self,
        idx: str,
        entry_time: str,
        strike: Any,
        signal: str,
        date_str: Optional[str] = None,
    ) -> bool:
        """Check if a trade with the same key fields already exists.
        
        If date_str is provided, only matches entries recorded on that date.
        """
        norm_strike = self._normalize_strike(strike)
        for entry in self.trades:
            if (entry.get("Index") == idx
                    and entry.get("Entry Time") == entry_time
                    and self._normalize_strike(entry.get("Strike")) == norm_strike
                    and entry.get("Signal") == signal):
                if date_str:
                    rec_date = str(entry.get("recorded_at") or "")[:10]
                    if rec_date and rec_date != date_str:
                        continue
                return True
        return False

    def record_trade(
        self,
        trade: Dict[str, Any],
        signal_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append a new trade entry and persist immediately.

        Deduplicates by (Index, Date, Entry Time, Strike, Signal) — if a matching
        entry already exists, the existing trade_id is returned and no new
        record is created.

        Args:
            trade: Dictionary containing trade fields (see ``_TRADE_FIELDS``).
            signal_metadata: Optional dict with signal context — keys such as
                ``pcr``, ``vwap``, ``oi_delta_ce``, ``oi_delta_pe``,
                ``confidence_score``, ``buffer_state``, ``pcr_momentum``,
                ``trap``.

        Returns:
            The generated ``trade_id`` string.
        """
        self._lock.acquire()
        try:
            self._load()
            idx = trade.get("Index", "UNK")
            entry_time = trade.get("Entry Time", "")
            strike = trade.get("Strike", "")
            signal = trade.get("Signal", "")
            now = datetime.now(tz=IST)
            today_str = now.strftime("%Y-%m-%d")

            # Dedup: skip if this trade already exists in the journal today
            if self._trade_exists(idx, entry_time, strike, signal, date_str=today_str):
                # Return existing trade_id
                for entry in self.trades:
                    rec_date = str(entry.get("recorded_at") or "")[:10]
                    if (entry.get("Index") == idx
                            and entry.get("Entry Time") == entry_time
                            and self._normalize_strike(entry.get("Strike")) == self._normalize_strike(strike)
                            and entry.get("Signal") == signal
                            and (not rec_date or rec_date == today_str)):
                        existing_id = entry.get("trade_id", "")
                        logger.debug("Trade already exists: %s — skipping duplicate", existing_id)
                        return existing_id

            timestamp = now.strftime("%Y%m%d_%H%M%S")
            trade_id = f"{idx}_{timestamp}"

            entry: Dict[str, Any] = {"trade_id": trade_id}

            # Copy every known trade field (missing fields get None)
            for field in self._TRADE_FIELDS:
                value = trade.get(field)
                # Convert datetime objects to ISO strings for JSON serialisation
                if isinstance(value, datetime):
                    value = value.isoformat()
                entry[field] = value

            entry["signal_metadata"] = dict(signal_metadata) if signal_metadata else {}
            entry["recorded_at"] = now.isoformat()

            self.trades.append(entry)
            self._save()
            if self.db:
                try:
                    self.db.upsert_trade(entry, signal_metadata)
                except Exception as e:
                    logger.warning("TradeDB upsert error: %s", e)
            logger.info("Recorded trade %s", trade_id)
            return trade_id
        finally:
            self._lock.release()

    def update_trade(self, trade_id: str, exit_data: Dict[str, Any], trade_dict: Optional[Dict[str, Any]] = None) -> bool:
        """Update an existing trade with exit information.

        Args:
            trade_id: The unique trade identifier returned by ``record_trade``.
            exit_data: Dict containing any of ``Exit Time``, ``Exit Price``,
                       ``Actual P&L ₹``, ``Status``, ``Result``, etc.
            trade_dict: Optional trade dictionary to match by fields if trade_id is empty/not found.

        Returns:
            ``True`` if the trade was found and updated, ``False`` otherwise.
        """
        self._lock.acquire()
        try:
            self._load()
            # Try finding by trade_id first
            if trade_id:
                for entry in self.trades:
                    if entry.get("trade_id") == trade_id:
                        for key, value in exit_data.items():
                            if isinstance(value, datetime):
                                value = value.isoformat()
                            entry[key] = value
                        entry["updated_at"] = datetime.now(tz=IST).isoformat()
                        self._save()
                        if self.db:
                            try:
                                self.db.update_trade_exit(trade_id, exit_data, trade_dict)
                            except Exception as e:
                                logger.warning("TradeDB update exit error: %s", e)
                        logger.info("Updated trade %s with exit data", trade_id)
                        return True

            # Fallback: Try finding by fields if trade_dict is provided
            # NOTE: We do NOT filter by Status=="OPEN" because trade_manager may have
            # already set Status="CLOSED" on the in-memory dict before journal.update_trade
            # is called. We match on the most recent entry (no updated_at) first.
            if trade_dict:
                idx = trade_dict.get("Index")
                etime = trade_dict.get("Entry Time")
                strike = trade_dict.get("Strike")
                sig = trade_dict.get("Signal")
                # Prefer entries that haven't been updated yet (no updated_at)
                candidates = [
                    entry for entry in self.trades
                    if (entry.get("Index") == idx
                        and entry.get("Entry Time") == etime
                        and self._normalize_strike(entry.get("Strike")) == self._normalize_strike(strike)
                        and entry.get("Signal") == sig)
                ]
                # Sort: prefer not-yet-updated entries first
                candidates.sort(key=lambda e: (1 if "updated_at" in e else 0))
                if candidates:
                    entry = candidates[0]
                    for key, value in exit_data.items():
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        entry[key] = value
                    entry["updated_at"] = datetime.now(tz=IST).isoformat()
                    self._save()
                    if self.db:
                        try:
                            self.db.update_trade_exit(entry.get("trade_id", ""), exit_data, trade_dict)
                        except Exception as e:
                            logger.warning("TradeDB fallback update exit error: %s", e)
                    logger.info("Updated trade by fields (Index=%s, EntryTime=%s) with exit data", idx, etime)
                    return True

            if self.db and (trade_id or trade_dict):
                try:
                    ok = self.db.update_trade_exit(trade_id, exit_data, trade_dict)
                    if ok:
                        return True
                except Exception as e:
                    logger.warning("TradeDB direct update exit error: %s", e)

            logger.warning("Trade %s not found for update", trade_id)
            return False
        finally:
            self._lock.release()

    def get_all_trades(self) -> List[Dict[str, Any]]:
        """Return a copy of every trade in the journal (preferring SQLite DB)."""
        with self._lock:
            if self.db:
                try:
                    db_trades = self.db.get_all_trades()
                    if db_trades:
                        return db_trades
                except Exception as e:
                    logger.warning("TradeDB get_all_trades error: %s", e)
            self._load()
            return list(self.trades)

    def get_trades_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        """Return trades whose recorded_at falls on *date_str*.

        Args:
            date_str: Date in ``YYYY-MM-DD`` format.
        """
        with self._lock:
            self._load()
            results: List[Dict[str, Any]] = []
            for t in self.trades:
                recorded_at = t.get("recorded_at", "")
                if recorded_at and str(recorded_at)[:10] == date_str:
                    results.append(t)
            return results

    def get_analytics(self, days: int = 7) -> Dict[str, Any]:
        """Compute comprehensive analytics over the last *days* days.

        Returns a dict with keys:
            total_trades, wins, losses, win_rate,
            total_pnl, avg_win, avg_loss, risk_reward_ratio,
            max_drawdown, best_trade, worst_trade,
            by_index, by_signal_type, by_hour,
            current_streak, consecutive_losses.
        """
        with self._lock:
            self._load()
            cutoff = datetime.now(tz=IST) - timedelta(days=days)
            trades = self._filter_since(cutoff)

        analytics: Dict[str, Any] = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "risk_reward_ratio": 0.0,
            "max_drawdown": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "by_index": {},
            "by_signal_type": {},
            "by_hour": {},
            "current_streak": {"type": "NONE", "count": 0},
            "consecutive_losses": 0,
        }

        closed_trades = [t for t in trades if t.get("Status") == "CLOSED"]
        open_trades = [t for t in trades if t.get("Status") == "OPEN"]

        analytics["open_trades"] = len(open_trades)

        if not closed_trades:
            return analytics

        win_pnls: List[float] = []
        loss_pnls: List[float] = []
        all_pnls: List[float] = []
        best_pnl = float("-inf")
        worst_pnl = float("inf")
        best_trade: Optional[Dict[str, Any]] = None
        worst_trade: Optional[Dict[str, Any]] = None

        # Accumulators
        by_index: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        )
        by_signal: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        )
        by_hour: Dict[int, Dict[str, Any]] = defaultdict(
            lambda: {"trades": 0, "pnl": 0.0}
        )

        for t in closed_trades:
            pnl = self._safe_float(t.get("Actual P&L ₹", 0))
            all_pnls.append(pnl)
            is_win = pnl > 0

            if is_win:
                win_pnls.append(pnl)
            else:
                loss_pnls.append(pnl)

            if pnl > best_pnl:
                best_pnl = pnl
                best_trade = t
            if pnl < worst_pnl:
                worst_pnl = pnl
                worst_trade = t

            # by_index
            idx = t.get("Index", "UNKNOWN")
            by_index[idx]["trades"] += 1
            by_index[idx]["pnl"] += pnl
            if is_win:
                by_index[idx]["wins"] += 1
            else:
                by_index[idx]["losses"] += 1

            # by_signal
            sig = t.get("Signal", "UNKNOWN")
            by_signal[sig]["trades"] += 1
            by_signal[sig]["pnl"] += pnl
            if is_win:
                by_signal[sig]["wins"] += 1
            else:
                by_signal[sig]["losses"] += 1

            # by_hour
            hour = self._extract_hour(t.get("recorded_at"))
            if hour is not None:
                by_hour[hour]["trades"] += 1
                by_hour[hour]["pnl"] += pnl

        total = len(closed_trades)
        wins = len(win_pnls)
        losses = len(loss_pnls)

        analytics["total_trades"] = total
        analytics["wins"] = wins
        analytics["losses"] = losses
        analytics["win_rate"] = round((wins / total) * 100, 2) if total else 0.0
        analytics["total_pnl"] = round(sum(all_pnls), 2)
        analytics["avg_win"] = round(sum(win_pnls) / wins, 2) if wins else 0.0
        analytics["avg_loss"] = round(sum(loss_pnls) / losses, 2) if losses else 0.0
        analytics["risk_reward_ratio"] = round(
            abs(analytics["avg_win"] / analytics["avg_loss"]), 2
        ) if analytics["avg_loss"] != 0 else 0.0

        # Max drawdown from cumulative P&L
        analytics["max_drawdown"] = self._max_drawdown(all_pnls)
        analytics["best_trade"] = best_trade
        analytics["worst_trade"] = worst_trade

        # Convert defaultdicts to plain dicts for JSON safety
        analytics["by_index"] = {k: dict(v) for k, v in by_index.items()}
        analytics["by_signal_type"] = {k: dict(v) for k, v in by_signal.items()}
        analytics["by_hour"] = {k: dict(v) for k, v in by_hour.items()}

        # Streaks
        analytics["current_streak"] = self._current_streak(closed_trades)
        analytics["consecutive_losses"] = self._trailing_consecutive_losses(closed_trades)

        return analytics

    # ------------------------------------------------------------------ #
    #  Persistence                                                        #
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        """Write the journal list to the JSON file atomically and resiliently."""
        if self._load_failed:
            logger.error("Save blocked: Journal file load failed previously (corrupted file). Overwrite prevented to protect data.")
            return

        # Protection: never wipe an existing non-empty file with an empty list unless forced
        if not self.trades and os.path.isfile(self.journal_path):
            try:
                if os.path.getsize(self.journal_path) > 50:
                    logger.warning("Save blocked: attempting to overwrite populated journal file with empty trades list")
                    return
            except OSError:
                pass

        dir_name = os.path.dirname(self.journal_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        import tempfile
        import time
        for attempt in range(3):
            tmp_path = None
            try:
                fd, tmp_path = tempfile.mkstemp(dir=dir_name or '.', prefix="trade_journal_tmp_", suffix=".json", text=True)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.trades, fh, indent=2, ensure_ascii=False, cls=NpEncoder)
                os.replace(tmp_path, self.journal_path)
                return
            except (OSError, TypeError) as exc:
                logger.warning("Save attempt %d failed: %s", attempt + 1, exc)
                time.sleep(0.05 * (attempt + 1))
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        logger.error("Failed to save journal after 3 attempts")

    def _load(self) -> None:
        """Read the journal list from the JSON file with retry and fallback."""
        import time
        if not os.path.isfile(self.journal_path):
            return

        loaded_data = None
        for attempt in range(3):
            try:
                if os.path.getsize(self.journal_path) > 0:
                    with open(self.journal_path, "r", encoding="utf-8") as fh:
                        loaded_data = json.load(fh)
                    break
                else:
                    time.sleep(0.05 * (attempt + 1))
            except (json.JSONDecodeError, OSError) as exc:
                time.sleep(0.05 * (attempt + 1))

        if isinstance(loaded_data, list):
            self.trades = loaded_data
            self._load_failed = False
            logger.debug("Loaded %d trades from journal", len(self.trades))
        elif loaded_data is not None:
            logger.warning("Journal file is not a list")
        else:
            if not self.trades:
                self.trades = []
            else:
                logger.warning("Could not read journal file; preserving %d in-memory trades", len(self.trades))

        if not self._load_failed and self.trades:
            # Deduplicate any existing entries
            deduped = self._deduplicate(self.trades)
            if len(deduped) < len(self.trades):
                logger.info(
                    "Removed %d duplicate journal entries on load",
                    len(self.trades) - len(deduped),
                )
                self.trades = deduped
                self._save()

    def _reconcile_stale_open_trades(self) -> None:
        """Auto-close any open trades from previous dates to prevent stale open state."""
        today_str = datetime.now(tz=IST).strftime("%Y-%m-%d")
        reconciled = False
        for t in self.trades:
            if t.get("Status") == "OPEN":
                rec_at = str(t.get("recorded_at") or "")[:10]
                if rec_at and rec_at < today_str:
                    t["Status"] = "CLOSED"
                    t["Result"] = t.get("Result") if t.get("Result") not in ("⏳ OPEN", "OPEN", None) else "🟡 AUTO-CLOSED (EOD)"
                    t["Exit Time"] = t.get("Exit Time") or "03:30:00 PM"
                    if t.get("Actual P&L ₹") is None:
                        ep = self._safe_float(t.get("Entry Price"))
                        lp = self._safe_float(t.get("Live Price") or ep)
                        qty = self._safe_float(t.get("Qty") or 0)
                        t["Actual P&L ₹"] = round((lp - ep) * qty, 2)
                    reconciled = True
        if reconciled:
            self._save()

    def _import_from_csv(self) -> None:
        """Proactively import missing closed trades from daily CSV logs across all dates."""
        try:
            import glob
            import pandas as pd
            from config import LOG_DIR, BASE_DIR
            search_dirs = [LOG_DIR, BASE_DIR]
            csv_files = []
            for d in search_dirs:
                if os.path.isdir(d):
                    csv_files.extend(glob.glob(os.path.join(d, "trade_log_*.csv")))
            csv_files = list(set(csv_files))
            imported_count = 0
            for filepath in csv_files:
                filename = os.path.basename(filepath)
                # Parse index and date from trade_log_{Index}_{YYYY-MM-DD}.csv
                parts = filename.replace(".csv", "").split("_")
                if len(parts) < 4:
                    continue
                idx_part = parts[2]
                date_part = parts[3]

                try:
                    df = pd.read_csv(filepath, encoding="utf-8")
                except Exception:
                    continue

                if df.empty:
                    continue

                for _, row in df.iterrows():
                    etime = str(row.get("Entry Time") or "").strip()
                    strike = row.get("Strike")
                    sig = str(row.get("Signal") or "").strip()
                    status = str(row.get("Status") or "").strip().upper()

                    # Check if already present in journal
                    if self._trade_exists(idx_part, etime, strike, sig, date_str=date_part):
                        continue

                    # Construct recorded_at timestamp
                    now_str = datetime.now(tz=IST).isoformat()
                    try:
                        dt_str = f"{date_part} {etime}"
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %I:%M:%S %p").replace(tzinfo=IST)
                        recorded_at = dt.isoformat()
                    except Exception:
                        try:
                            dt = datetime.strptime(f"{date_part} 09:15:00 AM", "%Y-%m-%d %I:%M:%S %p").replace(tzinfo=IST)
                            recorded_at = dt.isoformat()
                        except Exception:
                            recorded_at = now_str

                    # Generate trade ID
                    try:
                        timestamp = datetime.fromisoformat(recorded_at).strftime("%Y%m%d_%H%M%S")
                    except Exception:
                        timestamp = datetime.now(tz=IST).strftime("%Y%m%d_%H%M%S")
                    trade_id = f"{idx_part}_{timestamp}"

                    entry = {"trade_id": trade_id}
                    for field in self._TRADE_FIELDS:
                        val = row.get(field)
                        if pd.isna(val):
                            val = None
                        elif isinstance(val, (int, float)):
                            val = float(val)
                        entry[field] = val

                    today_str = datetime.now(tz=IST).strftime("%Y-%m-%d")
                    if date_part < today_str and status == "OPEN":
                        entry["Status"] = "CLOSED"
                        entry["Result"] = "🟡 AUTO-CLOSED (EOD)"
                        entry["Exit Time"] = entry.get("Exit Time") or "03:30:00 PM"
                        if entry.get("Actual P&L ₹") is None:
                            entry["Actual P&L ₹"] = 0.0

                    entry["signal_metadata"] = {}
                    entry["recorded_at"] = recorded_at
                    entry["imported_from_csv"] = True

                    self.trades.append(entry)
                    imported_count += 1

            if imported_count > 0:
                logger.info("Imported %d historical trades from CSV logs into journal", imported_count)
                self.trades.sort(key=lambda t: str(t.get("recorded_at") or ""))
                self._save()
        except Exception as e:
            logger.error("Failed to import historical trades from CSV logs: %s", e)

    @staticmethod
    def _deduplicate(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate trades, keeping the most-updated copy of each.

        Uniqueness key: (Index, Date, Entry Time, Strike, Signal).
        When duplicates exist, prefer the entry that has ``updated_at``
        (i.e. was closed/updated), falling back to the last occurrence.
        """
        seen: Dict[str, Dict[str, Any]] = {}
        for entry in trades:
            rec_at = str(entry.get("recorded_at") or "")
            date_part = rec_at[:10] if len(rec_at) >= 10 else ""
            if not date_part:
                tid = entry.get("trade_id", "")
                parts = str(tid).split("_")
                if len(parts) >= 2 and len(parts[1]) == 8 and parts[1].isdigit():
                    date_part = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]}"

            key = (
                f"{entry.get('Index')}|"
                f"{date_part}|"
                f"{entry.get('Entry Time')}|"
                f"{TradeJournal._normalize_strike(entry.get('Strike'))}|"
                f"{entry.get('Signal')}"
            )
            existing = seen.get(key)
            if existing is None:
                seen[key] = entry
            else:
                new_has_update = "updated_at" in entry or entry.get("Status") == "CLOSED"
                old_has_update = "updated_at" in existing or existing.get("Status") == "CLOSED"
                if new_has_update and not old_has_update:
                    seen[key] = entry
                elif new_has_update == old_has_update:
                    seen[key] = entry
        return list(seen.values())

    def export_to_json(self) -> str:
        """Export all trades to a formatted JSON string."""
        with self._lock:
            self._load()
            return json.dumps(self.trades, indent=2, ensure_ascii=False, cls=NpEncoder)

    def export_to_csv(self) -> str:
        """Export all trades to a CSV string."""
        import io
        import pandas as pd
        with self._lock:
            self._load()
            if not self.trades:
                return ""
            df = pd.DataFrame(self.trades)
            # Remove complex objects from signal_metadata for clean CSV export
            if "signal_metadata" in df.columns:
                df["signal_metadata"] = df["signal_metadata"].apply(lambda x: json.dumps(x) if isinstance(x, dict) else x)
            buf = io.StringIO()
            df.to_csv(buf, index=False, encoding="utf-8")
            return buf.getvalue()

    def import_from_json_string(self, json_str: str) -> int:
        """Import and merge trades from a JSON string.
        
        Returns the number of newly added trades.
        """
        with self._lock:
            try:
                data = json.loads(json_str)
                if not isinstance(data, list):
                    logger.error("Import failed: JSON data is not a list")
                    return 0
                
                initial_count = len(self.trades)
                merged = list(self.trades) + data
                deduped = self._deduplicate(merged)
                self.trades = deduped
                self._save()
                added = len(self.trades) - initial_count
                logger.info("Imported %d new trades into journal", max(0, added))
                return max(0, added)
            except Exception as e:
                logger.error("Failed to import trades from JSON: %s", e)
                return 0

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _filter_since(self, cutoff: datetime) -> List[Dict[str, Any]]:
        """Return trades with recorded_at >= *cutoff*."""
        results: List[Dict[str, Any]] = []
        for t in self.trades:
            recorded_at = t.get("recorded_at", "")
            if not recorded_at:
                continue
            try:
                recorded_dt = datetime.fromisoformat(str(recorded_at))
                # Attach IST if naive
                if recorded_dt.tzinfo is None:
                    recorded_dt = recorded_dt.replace(tzinfo=IST)
                if recorded_dt >= cutoff:
                    results.append(t)
            except (ValueError, TypeError):
                pass
        return results

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Convert *value* to float, returning 0.0 on failure."""
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _extract_hour(recorded_at: Any) -> Optional[int]:
        """Extract the hour component from recorded_at value."""
        if recorded_at is None:
            return None
        try:
            dt = datetime.fromisoformat(str(recorded_at))
            return dt.hour
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _max_drawdown(pnls: List[float]) -> float:
        """Compute maximum drawdown from a sequence of per-trade P&Ls."""
        if not pnls:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 2)

    @staticmethod
    def _current_streak(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Determine the current WIN/LOSS streak from the tail of *trades*."""
        if not trades:
            return {"type": "NONE", "count": 0}

        streak_type: Optional[str] = None
        count = 0

        for t in reversed(trades):
            pnl = TradeJournal._safe_float(t.get("Actual P&L ₹", 0))
            current = "WIN" if pnl > 0 else "LOSS"

            if streak_type is None:
                streak_type = current
                count = 1
            elif current == streak_type:
                count += 1
            else:
                break

        return {"type": streak_type or "NONE", "count": count}

    @staticmethod
    def _trailing_consecutive_losses(trades: List[Dict[str, Any]]) -> int:
        """Count consecutive losses from the end of the trade list.

        Returns 0 if the most recent trade is a win.
        """
        count = 0
        for t in reversed(trades):
            pnl = TradeJournal._safe_float(t.get("Actual P&L ₹", 0))
            is_loss = pnl <= 0
            if is_loss:
                count += 1
            else:
                break
        return count
