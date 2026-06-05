"""
V12 PRO MAX — Risk Manager
Position sizing, fixed stop-loss (₹1000), cooldown, and daily loss limits.
IMPORTANT: qty is ALWAYS = lot (1 lot only, no dynamic scaling).
"""
import datetime
from typing import Any, Dict, List, Optional, Tuple

from config import (
    MAX_LOSS,
    DAILY_TGT,
    CAPITAL,
    ATR_PERIOD,
    ATR_SL_MULTIPLIER,
    COOLDOWN_SECONDS,
    MAX_DAILY_LOSSES,
    MARKET_OPEN_BUFFER_MIN,
    MARKET_OPEN_TIME,
    IST,
)

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


log = get_logger("risk_manager")


class RiskManager:
    """Manages risk calculations for trade entry, fixed SL, and cooldowns.

    Design principle: qty is ALWAYS = lot (1 lot only). No dynamic
    position sizing. SL is fixed at ₹1000 (MAX_LOSS). No trailing stop.
    """

    # ──────────────────────────────────────────────
    # 1. CALC TRADE (basic, fixed SL)
    # ──────────────────────────────────────────────
    def calc_trade(
        self, ep: float, lot: int
    ) -> Tuple[int, float, float, float, float]:
        """Calculate trade parameters with fixed stop-loss.

        Parameters
        ----------
        ep : float
            Entry price (option premium).
        lot : int
            Lot size for the index.

        Returns
        -------
        (qty, sl_p, tgt_p, max_loss, target_pnl)
            qty      – always = lot (1 lot)
            sl_p     – stop-loss price
            tgt_p    – target price
            max_loss – max loss in ₹
            target_pnl – target profit in ₹
        """
        qty = max(1, lot)  # Always 1 lot; clamp to 1 to prevent division-by-zero
        sl_u = round(MAX_LOSS / qty, 2)
        tgt_u = round(DAILY_TGT / qty, 2)  # Use 2000 as target per trade
        sl_p = max(0.05, round(ep - sl_u, 2))
        tgt_p = round(ep + tgt_u, 2)
        return qty, sl_p, tgt_p, float(MAX_LOSS), float(DAILY_TGT)

    # ──────────────────────────────────────────────
    # 2. CALC TRADE WITH ATR
    # ──────────────────────────────────────────────
    def calc_trade_with_atr(
        self, ep: float, lot: int, spot_history: List[float]
    ) -> Tuple[int, float, float, float, float]:
        """Statically calculate trade parameters with fixed Stop Loss at MAX_LOSS (1000) and Target at DAILY_TGT (2000)."""
        return self.calc_trade(ep, lot)


    # ──────────────────────────────────────────────
    # 4. SHOULD ALLOW TRADE
    # ──────────────────────────────────────────────
    def should_allow_trade(
        self,
        idx: str,
        trade_log: List[Dict[str, Any]],
        now: datetime.datetime,
    ) -> Tuple[bool, str]:
        """Check whether a new trade entry is allowed.

        Checks
        ------
        1. Cooldown: if last closed trade on this idx was SL hit within
           COOLDOWN_SECONDS, block.
        2. Daily loss limit: if MAX_DAILY_LOSSES consecutive losses, block.
        3. Market open buffer: if now is within MARKET_OPEN_BUFFER_MIN of
           9:15, block.

        Parameters
        ----------
        idx : str
            Index name (e.g. "NIFTY").
        trade_log : list[dict]
            Trade log for this index.
        now : datetime.datetime
            Current time (IST-aware).

        Returns
        -------
        (allowed, reason)
        """
        # ── Market open buffer ──
        market_open_dt = datetime.datetime.combine(
            now.date(), MARKET_OPEN_TIME, tzinfo=IST
        )
        buffer_end = market_open_dt + datetime.timedelta(minutes=MARKET_OPEN_BUFFER_MIN)
        if market_open_dt <= now < buffer_end:
            return False, (
                f"⏳ Market open buffer — wait until "
                f"{buffer_end.strftime('%H:%M')} ({MARKET_OPEN_BUFFER_MIN}min)"
            )

        # ── Cooldown after SL hit ──
        closed_trades = [
            t for t in trade_log
            if t.get("Status") == "CLOSED"
            and t.get("Index", "") == idx
            and t.get("Result", "")  # has a result
        ]
        if closed_trades:
            # Trade log uses .insert(0, ...) so index 0 is newest (newest-first ordering).
            last_closed = closed_trades[0]
            if "LOSS" in str(last_closed.get("Result", "")):
                exit_time_str = last_closed.get("Exit Time", "")
                if exit_time_str:
                    try:
                        exit_time = datetime.datetime.strptime(
                            exit_time_str, "%I:%M:%S %p"
                        ).replace(
                            year=now.year,
                            month=now.month,
                            day=now.day,
                            tzinfo=IST,
                        )
                        elapsed = (now - exit_time).total_seconds()
                        if elapsed < COOLDOWN_SECONDS:
                            remaining = int(COOLDOWN_SECONDS - elapsed)
                            return False, (
                                f"🧊 Cooldown active — {remaining}s remaining "
                                f"after SL hit on {idx}"
                            )
                    except (ValueError, TypeError):
                        pass  # can't parse time, skip cooldown check

        # ── Daily loss limit ──
        allowed, reason = self.check_daily_limits(trade_log)
        if not allowed:
            return False, reason

        return True, ""

    # ──────────────────────────────────────────────
    # 5. CHECK DAILY LIMITS
    # ──────────────────────────────────────────────
    def check_daily_limits(
        self, trade_log: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """Check consecutive loss limit across all indices.

        Parameters
        ----------
        trade_log : list[dict]
            Combined trade log (may include multiple indices).

        Returns
        -------
        (allowed, reason)
        """
        closed = [t for t in trade_log if t.get("Status") == "CLOSED"]
        if not closed:
            return True, ""

        # Count consecutive losses from most recent.
        # Trade log uses .insert(0, ...) so closed[0] is newest (newest-first ordering).
        consecutive_losses = 0
        for t in closed:
            result = str(t.get("Result", ""))
            if "LOSS" in result:
                consecutive_losses += 1
            else:
                break  # streak broken

        if consecutive_losses >= MAX_DAILY_LOSSES:
            return False, (
                f"🛑 Daily loss limit reached — {consecutive_losses} consecutive "
                f"losses (max {MAX_DAILY_LOSSES}). Trading paused."
            )

        return True, ""
