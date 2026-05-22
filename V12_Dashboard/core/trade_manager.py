"""
V12 PRO MAX — Trade Manager
Extracts trade lifecycle management from the original app.py.
Handles entry, live price updates, SL/target monitoring, trailing stops,
auto-square-off, manual close, and CSV log persistence.
"""
import datetime
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import LOG_COLS, IST, AUTO_SQUARE_OFF_TIME, INDEX_CONFIG

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


log = get_logger("trade_manager")


class TradeManager:
    """Manages the full trade lifecycle: entry → monitoring → exit.

    Works with trade dicts using the same LOG_COLS format as the
    original app.py. Relies on an external notifier (TelegramNotifier)
    and risk manager (RiskManager) injected at construction.
    """

    def __init__(self, notifier: Any, risk_mgr: Any) -> None:
        """Initialize with notifier and risk manager references.

        Parameters
        ----------
        notifier : object
            Must have a `send(msg: str)` method (TelegramNotifier).
        risk_mgr : RiskManager
            Risk manager instance for SL/target calculations.
        """
        self._notifier = notifier
        self._risk_mgr = risk_mgr
        log.info("TradeManager initialized")

    # ──────────────────────────────────────────────
    # NOTIFY HELPER
    # ──────────────────────────────────────────────
    def _notify(self, msg: str) -> None:
        """Send notification, gracefully handling missing/broken notifier."""
        try:
            if self._notifier is not None:
                if hasattr(self._notifier, "send"):
                    self._notifier.send(msg)
                elif callable(self._notifier):
                    self._notifier(msg)
        except Exception as e:
            log.warning("Notification failed: %s", e)

    # ──────────────────────────────────────────────
    # 1. ENTER TRADE
    # ──────────────────────────────────────────────
    def enter_trade(
        self,
        idx: str,
        signal: str,
        spot: float,
        atm: int,
        ep: float,
        lot: int,
        conf: str,
        score: int,
        spot_history: List[float],
    ) -> Dict[str, Any]:
        """Create a new trade entry.

        Parameters
        ----------
        idx : str
            Index name (e.g. "NIFTY").
        signal : str
            "BUY CE" or "BUY PE".
        spot : float
            Current spot price.
        atm : int
            ATM strike selected.
        ep : float
            Entry price (option premium).
        lot : int
            Lot size for the index.
        conf : str
            Signal confidence level (HIGH, MEDIUM).
        score : int
            Numeric confidence score (0-100).
        spot_history : list[float]
            Recent spot readings for ATR calculation.

        Returns
        -------
        dict
            Trade dict with all LOG_COLS fields populated.
        """
        now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")

        # Use ATR-based SL if sufficient history, else basic
        qty, sl_p, tgt_p, ml, tp = self._risk_mgr.calc_trade_with_atr(
            ep, lot, spot_history
        )

        trade = {
            "Entry Time": now_str,
            "Exit Time": None,
            "Index": idx,
            "Signal": signal,
            "Spot": round(spot, 2),
            "Strike": atm,
            "Entry Price": ep,
            "Live Price": ep,
            "Exit Price": None,
            "Stop Loss": sl_p,
            "Target": tgt_p,
            "Qty": qty,
            "Max Loss ₹": ml,
            "Target P&L ₹": tp,
            "Actual P&L ₹": None,
            "Status": "OPEN",
            "Result": "⏳ OPEN",
        }

        log.info(
            "ENTRY: %s %s @ Strike %d | EP=%.2f SL=%.2f TGT=%.2f Qty=%d",
            idx, signal, atm, ep, sl_p, tgt_p, qty,
        )

        # Send signal alert
        emoji = "🟢" if "CE" in signal else "🔴"
        self._notify(
            f"{emoji} *V12 {idx} SIGNAL: {signal}*\n"
            f"📍 Strike: `{atm}` | Spot: `{round(spot, 2)}`\n"
            f"💰 Entry: `{ep}` | SL: `{sl_p}` | Target: `{tgt_p}`\n"
            f"📦 Qty: `{qty}` | Max Loss: `₹{ml}` | Target P&L: `₹{tp}`\n"
            f"⏰ Time: `{now_str}` | Conf: `{conf}` | Score: `{score}`"
        )

        return trade

    # ──────────────────────────────────────────────
    # 2. UPDATE LIVE PRICES
    # ──────────────────────────────────────────────
    def update_live_prices(
        self,
        idx: str,
        trade_log: List[Dict[str, Any]],
        chain_records: Dict[float, Dict[str, Any]],
        now: datetime.datetime,
    ) -> List[Dict[str, Any]]:
        """Update live prices for all open trades and check exit conditions.

        Parameters
        ----------
        idx : str
            Index name.
        trade_log : list[dict]
            Mutable list of trade dicts for this index.
        chain_records : dict[float, dict]
            Mapping of strikePrice -> chain item from current snapshot.
        now : datetime.datetime
            Current IST-aware datetime.

        Returns
        -------
        list[dict]
            List of event dicts for trades that were closed this cycle.
            Each event: {"type": "SL_HIT"|"TARGET_HIT"|"AUTO_SQ",
                         "trade": trade, "pnl": float}
        """
        events: List[Dict[str, Any]] = []
        now_str = now.strftime("%I:%M:%S %p")
        auto_sq = now.time() >= AUTO_SQUARE_OFF_TIME

        for trade in trade_log:
            if trade.get("Status") != "OPEN":
                continue

            # ── Resolve live price from chain ──
            try:
                strike = float(trade.get("Strike", 0))
            except (ValueError, TypeError):
                strike = 0.0

            signal = trade.get("Signal", "")
            item = chain_records.get(strike, {})
            opt = item.get("CE", {}) if signal == "BUY CE" else item.get("PE", {})
            lp = round(float(opt.get("lastPrice", 0) or 0), 2)

            if lp == 0:
                # Fallback: keep previous live price
                lp = float(
                    trade.get("Live Price") or trade.get("Entry Price") or 0
                )

            ep_t = float(trade.get("Entry Price") or 0)
            qty_t = int(trade.get("Qty") or 0)
            sl = float(trade.get("Stop Loss") or 0)
            tgt = float(trade.get("Target") or 0)

            trade["Live Price"] = lp

            # ── Apply trailing stop ──
            self._risk_mgr.apply_trailing_stop(trade)
            # Re-read SL in case trailing stop raised it
            sl = float(trade.get("Stop Loss") or 0)

            # ── Check exit conditions ──
            if auto_sq:
                pnl = round((lp - ep_t) * qty_t, 2)
                trade.update({
                    "Status": "CLOSED",
                    "Result": "🟡 AUTO-SQUARE OFF",
                    "Exit Price": lp,
                    "Exit Time": now_str,
                    "Actual P&L ₹": pnl,
                })
                events.append({"type": "AUTO_SQ", "trade": trade, "pnl": pnl})
                self._notify(
                    f"🟡 *AUTO-SQUARE OFF — {idx} {signal}*\n"
                    f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                    f"💸 P&L: `₹{pnl:,.0f}` | Time: `{now_str}`"
                )
                log.info(
                    "AUTO-SQ: %s %s Strike=%s Exit=%.2f PnL=%.2f",
                    idx, signal, trade.get("Strike"), lp, pnl,
                )

            elif lp <= sl and lp > 0:
                pnl = round((lp - ep_t) * qty_t, 2)
                trade.update({
                    "Status": "CLOSED",
                    "Result": "🔴 LOSS",
                    "Exit Price": lp,
                    "Exit Time": now_str,
                    "Actual P&L ₹": pnl,
                })
                events.append({"type": "SL_HIT", "trade": trade, "pnl": pnl})
                self._notify(
                    f"🔴 *SL HIT — {idx} {signal}*\n"
                    f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                    f"💸 P&L: `₹{pnl:,.0f}` | Time: `{now_str}`"
                )
                log.info(
                    "SL HIT: %s %s Strike=%s Exit=%.2f PnL=%.2f",
                    idx, signal, trade.get("Strike"), lp, pnl,
                )

            elif lp >= tgt and lp > 0:
                pnl = round((lp - ep_t) * qty_t, 2)
                trade.update({
                    "Status": "CLOSED",
                    "Result": "🟢 WIN",
                    "Exit Price": lp,
                    "Exit Time": now_str,
                    "Actual P&L ₹": pnl,
                })
                events.append({"type": "TARGET_HIT", "trade": trade, "pnl": pnl})
                self._notify(
                    f"🟢 *TARGET HIT — {idx} {signal}*\n"
                    f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                    f"💸 P&L: `₹{pnl:,.0f}` | Time: `{now_str}`"
                )
                log.info(
                    "TARGET HIT: %s %s Strike=%s Exit=%.2f PnL=%.2f",
                    idx, signal, trade.get("Strike"), lp, pnl,
                )

        return events

    # ──────────────────────────────────────────────
    # 3. CLOSE MANUALLY
    # ──────────────────────────────────────────────
    def close_manually(
        self,
        idx: str,
        trade: Dict[str, Any],
        lp: float,
    ) -> Dict[str, Any]:
        """Close a trade at the given live price (manual exit).

        Parameters
        ----------
        idx : str
            Index name.
        trade : dict
            Trade dict to close (modified in-place).
        lp : float
            Live price to use as exit price.

        Returns
        -------
        dict
            Event dict: {"type": "MANUAL", "trade": trade, "pnl": float}
        """
        now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")

        if lp is None or lp == 0:
            lp = float(
                trade.get("Live Price") or trade.get("Entry Price") or 0
            )

        ep_t = float(trade.get("Entry Price") or 0)
        qty_t = int(trade.get("Qty") or 0)
        pnl = round((lp - ep_t) * qty_t, 2)
        signal = trade.get("Signal", "")

        trade.update({
            "Status": "CLOSED",
            "Result": "🟡 MANUAL",
            "Exit Price": lp,
            "Exit Time": now_str,
            "Actual P&L ₹": pnl,
            "Live Price": lp,
        })

        log.info(
            "MANUAL EXIT: %s %s Strike=%s Exit=%.2f PnL=%.2f",
            idx, signal, trade.get("Strike"), lp, pnl,
        )

        self._notify(
            f"🟡 *MANUAL EXIT — {idx} {signal}*\n"
            f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
            f"💸 P&L: `₹{pnl:,.0f}` | Time: `{now_str}`"
        )

        return {"type": "MANUAL", "trade": trade, "pnl": pnl}

    # ──────────────────────────────────────────────
    # 4. SAVE LOG
    # ──────────────────────────────────────────────
    def save_log(self, idx: str, trade_log: List[Dict[str, Any]]) -> None:
        """Save trade log to CSV file (same format as original app.py).

        Parameters
        ----------
        idx : str
            Index name.
        trade_log : list[dict]
            List of trade dicts.
        """
        if not trade_log:
            return

        filename = (
            f"trade_log_{idx}_"
            f"{datetime.datetime.now(IST).strftime('%Y-%m-%d')}.csv"
        )
        try:
            df = pd.DataFrame(trade_log)
            # Ensure all LOG_COLS exist
            for col in LOG_COLS:
                if col not in df.columns:
                    df[col] = None
            df[LOG_COLS].to_csv(filename, index=False)
            log.debug("Trade log saved: %s (%d trades)", filename, len(trade_log))
        except Exception as e:
            log.error("Failed to save trade log %s: %s", filename, e)

    # ──────────────────────────────────────────────
    # 5. LOAD LOG
    # ──────────────────────────────────────────────
    def load_log(self, idx: str) -> List[Dict[str, Any]]:
        """Load trade log from CSV file (same format as original app.py).

        Parameters
        ----------
        idx : str
            Index name.

        Returns
        -------
        list[dict]
            List of trade dicts, or empty list if file doesn't exist.
        """
        filename = (
            f"trade_log_{idx}_"
            f"{datetime.datetime.now(IST).strftime('%Y-%m-%d')}.csv"
        )
        if not os.path.exists(filename):
            return []

        try:
            df = pd.read_csv(filename)
            # Ensure all LOG_COLS exist
            for col in LOG_COLS:
                if col not in df.columns:
                    df[col] = None
            records = df[LOG_COLS].to_dict("records")
            log.info("Loaded %d trades from %s", len(records), filename)
            return records
        except Exception as e:
            log.error("Failed to load trade log %s: %s", filename, e)
            return []
