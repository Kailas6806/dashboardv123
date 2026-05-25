"""
V12 PRO MAX — Risk Manager
Position sizing, stop-loss, trailing stops, cooldown, and daily loss limits.
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
    TRAILING_STOP_ACTIVATION,
    TRAILING_STOP_LOCK_PCT,
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
    """Manages risk calculations for trade entry, trailing stops, and cooldowns.

    Design principle: qty is ALWAYS = lot (1 lot only). No dynamic
    position sizing. This keeps risk fixed and predictable.
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
        qty = lot  # Always 1 lot
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
    # 3. TRAILING STOP
    # ──────────────────────────────────────────────
    def apply_trailing_stop(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Apply trailing stop logic to an open trade.

        Activates when unrealized profit >= TRAILING_STOP_ACTIVATION * target_pnl.
        Once activated, locks in TRAILING_STOP_LOCK_PCT of the highest seen profit
        by raising the stop-loss price.

        Parameters
        ----------
        trade : dict
            Trade dict with LOG_COLS fields. Modified in-place and returned.
            Uses internal key '_highest_pnl' to track watermark.

        Returns
        -------
        dict
            The (potentially modified) trade dict.
        """
        if trade.get("Status") != "OPEN":
            return trade

        ep = float(trade.get("Entry Price") or 0)
        lp = float(trade.get("Live Price") or ep)
        qty = int(trade.get("Qty") or 0)
        target_pnl = float(trade.get("Target P&L ₹") or 0)

        if qty <= 0 or target_pnl <= 0:
            return trade

        unrealized = (lp - ep) * qty
        activation_threshold = TRAILING_STOP_ACTIVATION * target_pnl

        if unrealized < activation_threshold:
            return trade

        # Track highest seen profit
        highest = float(trade.get("_highest_pnl", 0))
        if unrealized > highest:
            highest = unrealized
            trade["_highest_pnl"] = highest

        # Lock in portion of highest profit
        locked_profit = highest * TRAILING_STOP_LOCK_PCT
        locked_per_unit = locked_profit / qty
        new_sl = round(ep + locked_per_unit, 2)

        current_sl = float(trade.get("Stop Loss") or 0)
        if new_sl > current_sl:
            log.info(
                "Trailing stop raised: %.2f → %.2f (locked ₹%.0f of ₹%.0f highest)",
                current_sl, new_sl, locked_profit, highest,
            )
            trade["Stop Loss"] = new_sl

        return trade

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
            last_closed = closed_trades[0]  # most recent (list is newest-first)
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

        # Count consecutive losses from most recent
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
