"""
V12 PRO MAX — Risk Manager
Position sizing, fixed stop-loss (₹1000), cooldown, and daily loss limits.
IMPORTANT: qty is ALWAYS = lot (1 lot only, no dynamic scaling).
"""
import datetime
import math
from typing import Any, Dict, List, Optional, Tuple

from config import (
    MAX_LOSS,
    MAX_INDEX_DAILY_LOSS,
    MAX_DAILY_LOSS,
    DAILY_TGT,
    MAX_DAILY_TRADES,
    PROFIT_LOCK_START,
    PROFIT_LOCK_STEP,
    MAX_PROFIT_EXIT,
    PROFIT_LOCK_THRESHOLD,
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
        self, ep: float, lot: int, max_loss_override: Optional[float] = None
    ) -> Tuple[int, float, float, float, float]:
        """Calculate trade parameters with fixed stop-loss.

        Parameters
        ----------
        ep : float
            Entry price (option premium).
        lot : int
            Lot size for the index.
        max_loss_override : float, optional
            Custom max loss limit (defaults to MAX_LOSS = ₹2,000).

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
        eff_max_loss = max_loss_override if max_loss_override is not None else MAX_LOSS
        # Floor SL points so that (sl_u * qty) strictly NEVER exceeds MAX_LOSS (₹2,000)
        sl_u = math.floor((eff_max_loss / qty) * 100) / 100.0
        # Ceil target points so that target profit strictly reaches at least DAILY_TGT (₹4,000)
        tgt_u = math.ceil((DAILY_TGT / qty) * 100) / 100.0
        sl_p = max(0.05, round(ep - sl_u, 2))
        tgt_p = round(ep + tgt_u, 2)
        max_loss = min(round(sl_u * qty, 2), float(eff_max_loss))
        target_pnl = round(tgt_u * qty, 2)
        return qty, sl_p, tgt_p, max_loss, target_pnl

    # ──────────────────────────────────────────────
    # 2. CALC TRADE WITH ATR
    # ──────────────────────────────────────────────
    def calc_trade_with_atr(
        self, ep: float, lot: int, spot_history: List[float], max_loss_override: Optional[float] = None
    ) -> Tuple[int, float, float, float, float]:
        """Calculate trade parameters using ATR-based stop loss.

        If spot_history has enough bars, computes ATR as the mean of
        absolute bar-to-bar changes over the last ATR_PERIOD bars and
        derives SL/target from that. Falls back to calc_trade() when
        history is insufficient.

        Returns
        -------
        (qty, sl_p, tgt_p, max_loss, target_pnl)
        """
        eff_max_loss = max_loss_override if max_loss_override is not None else MAX_LOSS
        if len(spot_history) >= ATR_PERIOD:
            recent = spot_history[-ATR_PERIOD:]
            atr = sum(
                abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))
            ) / (ATR_PERIOD - 1)

            qty = max(1, lot)
            # HARD CEILING: Floored to ensure (max_sl_pts * qty) NEVER exceeds MAX_LOSS (₹2,000)
            max_sl_pts = math.floor((eff_max_loss / qty) * 100) / 100.0
            atr_sl_points = min(round(atr * ATR_SL_MULTIPLIER, 2), max_sl_pts)

            # Target must achieve at least DAILY_TGT (₹4,000), or 2x ATR SL points if larger
            min_tgt_pts = math.ceil((DAILY_TGT / qty) * 100) / 100.0
            tgt_pts = max(min_tgt_pts, round(atr_sl_points * 2, 2))

            sl_p = max(0.05, round(ep - atr_sl_points, 2))
            tgt_p = round(ep + tgt_pts, 2)
            max_loss = min(round(atr_sl_points * qty, 2), float(eff_max_loss))
            target_pnl = round(tgt_pts * qty, 2)

            log.debug(
                "ATR SL: atr=%.2f mult=%.2f sl_pts=%.2f sl_p=%.2f tgt_p=%.2f ml=%.2f tp=%.2f",
                atr, ATR_SL_MULTIPLIER, atr_sl_points, sl_p, tgt_p, max_loss, target_pnl,
            )
            return qty, sl_p, tgt_p, max_loss, target_pnl

        # Fallback: insufficient history
        log.debug(
            "ATR fallback: only %d bars available (need %d)",
            len(spot_history), ATR_PERIOD,
        )
        return self.calc_trade(ep, lot, max_loss_override=eff_max_loss)


    # ──────────────────────────────────────────────
    # 4. SHOULD ALLOW TRADE
    # ──────────────────────────────────────────────
    def should_allow_trade(
        self,
        idx: str,
        trade_log: List[Dict[str, Any]],
        now: datetime.datetime,
        portfolio_trades: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, str]:
        """Check whether a new trade entry is allowed.

        Checks
        ------
        1. Cooldown: if last closed trade on this idx was SL hit within
           COOLDOWN_SECONDS, block.
        2. Daily trade count: max MAX_DAILY_TRADES (3) trades per day.
        3. Daily loss limit: max MAX_DAILY_LOSSES consecutive losses or total loss >= MAX_LOSS.
        4. Market open buffer: if now is within MARKET_OPEN_BUFFER_MIN of 9:15, block.

        Parameters
        ----------
        idx : str
            Index name (e.g. "NIFTY").
        trade_log : list[dict]
            Trade log for this index.
        now : datetime.datetime
            Current time (IST-aware).
        portfolio_trades : list[dict], optional
            Combined trade log across all indices for portfolio-wide limits.

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

        # ── Per-Index daily loss limit (₹2,000 max per index) ──
        closed_idx = [t for t in trade_log if t.get("Status") == "CLOSED"]
        idx_pnl = sum(float(t.get("Actual P&L ₹") or 0) for t in closed_idx if t.get("Actual P&L ₹") is not None)
        if idx_pnl <= -MAX_INDEX_DAILY_LOSS:
            return False, (
                f"🛑 Max daily loss for {idx} reached (-₹{abs(idx_pnl):,.0f} ≤ -₹{MAX_INDEX_DAILY_LOSS:,}). "
                f"Trading paused for {idx} today."
            )

        # ── Daily limits (checked across entire portfolio if provided) ──
        limits_trades = portfolio_trades if portfolio_trades is not None else trade_log
        allowed, reason = self.check_daily_limits(limits_trades)
        if not allowed:
            return False, reason

        return True, ""

    # ──────────────────────────────────────────────
    # 5. CHECK DAILY LIMITS
    # ──────────────────────────────────────────────
    def check_daily_limits(
        self, trade_log: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """Check daily limits across all indices:
        1. Max trades per day total (MAX_DAILY_TRADES = 6).
        2. Consecutive loss limit.
        3. Max daily portfolio loss limit (₹6,000).

        Parameters
        ----------
        trade_log : list[dict]
            Combined trade log (may include multiple indices).

        Returns
        -------
        (allowed, reason)
        """
        if not trade_log:
            return True, ""

        # 1. Total trades taken today
        valid_trades = [t for t in trade_log if t.get("Entry Time")]
        if len(valid_trades) >= MAX_DAILY_TRADES:
            return False, (
                f"🛑 Daily limit reached: {len(valid_trades)}/{MAX_DAILY_TRADES} trades "
                f"already taken today. No new trades allowed."
            )

        closed = [t for t in trade_log if t.get("Status") == "CLOSED"]
        if not closed:
            return True, ""

        # 2. Consecutive loss limit
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

        # 3. Max daily loss limit in ₹ (₹6,000 portfolio total across 3 indices)
        total_pnl = sum(
            float(t.get("Actual P&L ₹") or 0)
            for t in closed
            if t.get("Actual P&L ₹") is not None
        )
        if total_pnl <= -MAX_DAILY_LOSS:
            return False, (
                f"🛑 Max daily portfolio loss reached (Realized P&L: -₹{abs(total_pnl):,.0f} ≤ -₹{MAX_DAILY_LOSS:,}). "
                f"Trading paused for today to preserve capital."
            )

        return True, ""
