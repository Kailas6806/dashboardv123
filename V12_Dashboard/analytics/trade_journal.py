"""
V12 PRO MAX — Trade Journal
Persistent trade journal that records every trade with full signal metadata
for cross-day analytics and performance tracking.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any, Dict, List, Optional

from config import JOURNAL_FILE, IST

logger = logging.getLogger("v12.trade_journal")


class TradeJournal:
    """Persistent JSON-backed trade journal with analytics capabilities."""

    # Fields copied from each trade row
    _TRADE_FIELDS = [
        "Entry Time", "Exit Time", "Index", "Signal", "Spot", "Strike",
        "Entry Price", "Live Price", "Exit Price",
        "Stop Loss", "Target", "Qty", "Max Loss ₹", "Target P&L ₹",
        "Actual P&L ₹", "Status", "Result",
    ]

    def __init__(self, journal_path: Optional[str] = None) -> None:
        """Initialise the journal, loading existing data if available.

        Args:
            journal_path: Path to the JSON journal file.
                          Defaults to ``config.JOURNAL_FILE``.
        """
        self.journal_path: str = journal_path or JOURNAL_FILE
        self.trades: List[Dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def record_trade(
        self,
        trade: Dict[str, Any],
        signal_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append a new trade entry and persist immediately.

        Args:
            trade: Dictionary containing trade fields (see ``_TRADE_FIELDS``).
            signal_metadata: Optional dict with signal context — keys such as
                ``pcr``, ``vwap``, ``oi_delta_ce``, ``oi_delta_pe``,
                ``confidence_score``, ``buffer_state``, ``pcr_momentum``,
                ``trap``.

        Returns:
            The generated ``trade_id`` string.
        """
        now = datetime.now(tz=IST)
        idx = trade.get("Index", "UNK")
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
        logger.info("Recorded trade %s", trade_id)
        return trade_id

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
                    logger.info("Updated trade %s with exit data", trade_id)
                    return True

        # Fallback: Try finding by fields if trade_dict is provided
        if trade_dict:
            idx = trade_dict.get("Index")
            etime = trade_dict.get("Entry Time")
            strike = trade_dict.get("Strike")
            sig = trade_dict.get("Signal")
            for entry in self.trades:
                if (entry.get("Index") == idx 
                    and entry.get("Entry Time") == etime 
                    and str(entry.get("Strike")) == str(strike) 
                    and entry.get("Signal") == sig
                    and entry.get("Status") == "OPEN"):
                    for key, value in exit_data.items():
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        entry[key] = value
                    entry["updated_at"] = datetime.now(tz=IST).isoformat()
                    self._save()
                    logger.info("Updated trade by fields (Index=%s, EntryTime=%s) with exit data", idx, etime)
                    return True

        logger.warning("Trade %s not found for update", trade_id)
        return False

    def get_all_trades(self) -> List[Dict[str, Any]]:
        """Return a copy of every trade in the journal."""
        return list(self.trades)

    def get_trades_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        """Return trades whose recorded_at falls on *date_str*.

        Args:
            date_str: Date in ``YYYY-MM-DD`` format.
        """
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

        if not trades:
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

        for t in trades:
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

        total = len(trades)
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
        analytics["current_streak"] = self._current_streak(trades)
        analytics["consecutive_losses"] = self._trailing_consecutive_losses(trades)

        return analytics

    # ------------------------------------------------------------------ #
    #  Persistence                                                        #
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        """Write the journal list to the JSON file."""
        try:
            dir_name = os.path.dirname(self.journal_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(self.journal_path, "w", encoding="utf-8") as fh:
                json.dump(self.trades, fh, indent=2, ensure_ascii=False)
        except (OSError, TypeError) as exc:
            logger.error("Failed to save journal: %s", exc)

    def _load(self) -> None:
        """Read the journal list from the JSON file (if it exists)."""
        if not os.path.isfile(self.journal_path):
            logger.info("No existing journal at %s — starting fresh", self.journal_path)
            return
        try:
            with open(self.journal_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                self.trades = data
                logger.info("Loaded %d trades from journal", len(self.trades))
            else:
                logger.warning("Journal file is not a list — starting fresh")
                self.trades = []
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load journal: %s", exc)
            self.trades = []

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
