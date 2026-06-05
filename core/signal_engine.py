"""
V12 PRO MAX — Signal Engine
Core signal generation logic extracted from app.py.
The generate_signal(), confirm_signal(), and detect_trap() methods
preserve the EXACT original logic — do not modify.
"""
import statistics
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import (
    SIGNAL_BUFFER_SIZE,
    SIGNAL_CONFIRM_COUNT,
    SIDEWAYS_PCR_LOW,
    SIDEWAYS_PCR_HIGH,
    SIDEWAYS_SPOT_STDEV_PCT,
    VWAP_HISTORY_SIZE,
    OI_UNUSUAL_THRESHOLD,
    CONF_WEIGHT_PCR,
    CONF_WEIGHT_VWAP,
    CONF_WEIGHT_OI_DELTA,
    CONF_WEIGHT_PCR_MOM,
    CONF_WEIGHT_SR_PROX,
    CONF_PENALTY_TRAP,
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


log = get_logger("signal_engine")


class SignalEngine:
    """Generates trading signals from option chain data.

    The core signal thresholds (PCR levels, VWAP checks, OI momentum)
    are the trading philosophy and MUST NOT be altered.
    """

    # ──────────────────────────────────────────────
    # 1. COMPUTE MARKET DATA
    # ──────────────────────────────────────────────
    def compute_market_data(
        self,
        df: pd.DataFrame,
        spot: float,
        step: int,
        idx: str,
        spot_history: List[float],
        pcr_history: List[float],
        prev_df: Optional[pd.DataFrame],
        oi_baseline: Optional[pd.DataFrame],
    ) -> Dict[str, Any]:
        """Compute all market-derived metrics from an option chain snapshot.

        Parameters
        ----------
        df : pd.DataFrame
            Option chain rows with columns Strike, CE LTP, CE OI, PE LTP, PE OI.
        spot : float
            Current spot price.
        step : int
            Strike step size for the index.
        idx : str
            Index name (e.g. "NIFTY").
        spot_history : list[float]
            Running list of recent spot readings (mutable, will be appended to).
        pcr_history : list[float]
            Running list of recent PCR readings (mutable, will be appended to).
        prev_df : pd.DataFrame | None
            Previous snapshot for OI delta calculation.
        oi_baseline : pd.DataFrame | None
            Session-start baseline for OI delta if prev_df is unavailable.

        Returns
        -------
        dict
            MarketData dict with all computed fields.
        """
        # ── ATM ──
        atm = round(spot / step) * step
        df["dist"] = (df["Strike"] - spot).abs()
        if df.empty:
            return None
        atm_actual = int(df.loc[df["dist"].idxmin(), "Strike"])
        atm_row = df[df["Strike"] == atm_actual].iloc[0]

        # ── OI Delta (compare with previous snapshot / baseline) ──
        updated_oi_baseline = oi_baseline
        if prev_df is not None:
            m = pd.merge(df, prev_df, on="Strike", how="left", suffixes=("", "_p"))
            df["CE OI Δ"] = (m["CE OI"] - m["CE OI_p"]).fillna(0)
            df["PE OI Δ"] = (m["PE OI"] - m["PE OI_p"]).fillna(0)
        elif oi_baseline is not None:
            m = pd.merge(df, oi_baseline, on="Strike", how="left", suffixes=("", "_b"))
            df["CE OI Δ"] = (m["CE OI"] - m["CE OI_b"]).fillna(0)
            df["PE OI Δ"] = (m["PE OI"] - m["PE OI_b"]).fillna(0)
        else:
            df["CE OI Δ"] = 0
            df["PE OI Δ"] = 0
            updated_oi_baseline = df[["Strike", "CE OI", "PE OI"]].copy()

        updated_prev_df = df[["Strike", "CE OI", "PE OI"]].copy()

        # ── Totals & PCR ──
        tot_ce = df["CE OI"].sum()
        tot_pe = df["PE OI"].sum()
        pcr = round(tot_pe / tot_ce, 2) if tot_ce > 0 else 0

        # ── Bias ──
        bias = "Bullish" if pcr > 1.2 else ("Bearish" if pcr < 0.8 else "Neutral")

        # ── Support / Resistance (max OI strikes) ──
        support = int(df.loc[df["PE OI"].idxmax(), "Strike"])
        resistance = int(df.loc[df["CE OI"].idxmax(), "Strike"])

        # ── Secondary S/R (2nd-highest OI strike) ──
        secondary_support = support
        secondary_resistance = resistance
        try:
            pe_top3 = df.nlargest(3, "PE OI")
            if len(pe_top3) >= 2:
                secondary_support = int(pe_top3.iloc[1]["Strike"])
        except Exception:
            pass
        try:
            ce_top3 = df.nlargest(3, "CE OI")
            if len(ce_top3) >= 2:
                secondary_resistance = int(ce_top3.iloc[1]["Strike"])
        except Exception:
            pass

        # ── OI Delta aggregates ──
        ce_delta_idx = (
            df["CE OI Δ"].idxmax()
            if df["CE OI Δ"].max() > 0
            else df["CE OI"].idxmax()
        )
        pe_delta_idx = (
            df["PE OI Δ"].idxmax()
            if df["PE OI Δ"].max() > 0
            else df["PE OI"].idxmax()
        )
        ce_build = int(df.loc[ce_delta_idx, "Strike"])
        pe_build = int(df.loc[pe_delta_idx, "Strike"])
        total_ce_delta = df["CE OI Δ"].sum()
        total_pe_delta = df["PE OI Δ"].sum()

        # ── OI Momentum ──
        oi_momentum_bullish = total_pe_delta > total_ce_delta
        oi_momentum_bearish = total_ce_delta > total_pe_delta

        # ── OI Unusual Activity ──
        total_abs_delta = abs(total_ce_delta) + abs(total_pe_delta)
        oi_unusual_activity = False
        if total_abs_delta > 0:
            max_single_ce = df["CE OI Δ"].abs().max()
            max_single_pe = df["PE OI Δ"].abs().max()
            max_single = max(max_single_ce, max_single_pe)
            if max_single > OI_UNUSUAL_THRESHOLD * total_abs_delta:
                oi_unusual_activity = True

        # ── OI Active ──
        oi_active = tot_ce > 0 and tot_pe > 0

        # ── PCR History & Momentum ──
        pcr_history.append(pcr)
        pcr_history[:] = pcr_history[-5:]
        pcr_momentum = "FLAT"
        if len(pcr_history) >= 3:
            if pcr_history[-1] > pcr_history[-3] + 0.02:
                pcr_momentum = "RISING"
            elif pcr_history[-1] < pcr_history[-3] - 0.02:
                pcr_momentum = "FALLING"

        # ── Spot History & VWAP Proxy ──
        spot_history.append(spot)
        spot_history[:] = spot_history[-VWAP_HISTORY_SIZE:]

        # Volume-weighted average using total OI as weight approximation
        # Since we only have one OI snapshot per refresh, use simple
        # moving average of spot readings (same semantic as original)
        vwap_proxy = round(sum(spot_history) / len(spot_history), 2)
        spot_vs_vwap = "ABOVE" if spot > vwap_proxy else "BELOW"

        # ── Sideways Detection ──
        is_sideways, sideways_strength = self.detect_sideways(spot_history, pcr)

        log.debug(
            "%s market_data: pcr=%.2f bias=%s sup=%d res=%d vwap=%.2f",
            idx, pcr, bias, support, resistance, vwap_proxy,
        )

        return {
            "idx": idx,
            "atm_actual": atm_actual,
            "atm_row": atm_row,
            "pcr": pcr,
            "bias": bias,
            "support": support,
            "resistance": resistance,
            "secondary_support": secondary_support,
            "secondary_resistance": secondary_resistance,
            "ce_build": ce_build,
            "pe_build": pe_build,
            "total_ce_delta": total_ce_delta,
            "total_pe_delta": total_pe_delta,
            "oi_momentum_bullish": oi_momentum_bullish,
            "oi_momentum_bearish": oi_momentum_bearish,
            "oi_unusual_activity": oi_unusual_activity,
            "oi_active": oi_active,
            "pcr_momentum": pcr_momentum,
            "spot_vs_vwap": spot_vs_vwap,
            "vwap_proxy": vwap_proxy,
            "spot": spot,
            "is_sideways": is_sideways,
            "sideways_strength": sideways_strength,
            "df": df,
            "prev_df": updated_prev_df,
            "oi_baseline": updated_oi_baseline,
            "pcr_history": pcr_history,
            "spot_history": spot_history,
        }

    # ──────────────────────────────────────────────
    # 2. GENERATE SIGNAL  *** VERBATIM FROM app.py ***
    # ──────────────────────────────────────────────
    def generate_signal(
        self, market_data: Dict[str, Any], in_window: bool
    ) -> Tuple[str, str, str]:
        """Generate raw signal from market data.

        Returns
        -------
        (signal, confidence, filter_reason)
        """
        pcr = market_data["pcr"]
        spot = market_data["spot"]
        support = market_data["support"]
        resistance = market_data["resistance"]
        spot_vs_vwap = market_data["spot_vs_vwap"]
        pcr_momentum = market_data["pcr_momentum"]
        oi_momentum_bullish = market_data["oi_momentum_bullish"]
        oi_momentum_bearish = market_data["oi_momentum_bearish"]
        bias = market_data["bias"]
        oi_active = market_data["oi_active"]

        # ── SIGNAL LOGIC (Fixed & Improved) ──
        # Primary logic: PCR + spot position relative to support/resistance + VWAP
        signal="WAIT"; confidence="LOW"; filter_reason=""

        if not in_window:
            filter_reason="⏰ Outside trading hours (9:15–3:30)"
        elif not oi_active:
            filter_reason="📉 No OI data — market closed?"
        else:
            # HIGH confidence: PCR + VWAP + OI momentum all align
            if (pcr > 1.2 and spot > support and spot_vs_vwap == "ABOVE"
                    and pcr_momentum in ("RISING", "FLAT") and oi_momentum_bullish):
                signal="BUY CE"; confidence="HIGH"
            elif (pcr < 0.8 and spot < resistance and spot_vs_vwap == "BELOW"
                    and pcr_momentum in ("FALLING", "FLAT") and oi_momentum_bearish):
                signal="BUY PE"; confidence="HIGH"

            # MEDIUM confidence: PCR + VWAP align (even if OI momentum not confirmed)
            elif pcr > 1.15 and spot > support and spot_vs_vwap == "ABOVE":
                signal="BUY CE"; confidence="MEDIUM"
            elif pcr < 0.85 and spot < resistance and spot_vs_vwap == "BELOW":
                signal="BUY PE"; confidence="MEDIUM"

            # LOW confidence: pure PCR signal
            elif pcr > 1.1 and spot > support:
                signal="BUY CE"; confidence="LOW"
            elif pcr < 0.9 and spot < resistance:
                signal="BUY PE"; confidence="LOW"
            elif bias == "Neutral":
                signal="⚠️ SIDEWAYS"; confidence="AVOID"

        return signal, confidence, filter_reason

    # ──────────────────────────────────────────────
    # 3. CONFIRM SIGNAL  *** VERBATIM FROM app.py ***
    # ──────────────────────────────────────────────
    def confirm_signal(
        self,
        signal: str,
        confidence: str,
        signal_buffer: List[str],
    ) -> Tuple[str, str, List[str]]:
        """Confirm signal across refreshes using buffer.

        Returns
        -------
        (final_signal, final_conf, updated_buffer)
        """
        buf = list(signal_buffer)  # work on a copy
        buf.append(signal)
        buf = buf[-SIGNAL_BUFFER_SIZE:]

        # Confirm signal: needs 2 of last 3 refreshes to agree.
        # Final confidence = actual signal confidence (not auto-promoted to HIGH)
        if buf.count("BUY CE") >= 2:
            final_signal = "BUY CE"
            # Only HIGH if underlying confidence is HIGH; else keep MEDIUM
            final_conf = confidence if confidence == "HIGH" else "MEDIUM"
        elif buf.count("BUY PE") >= 2:
            final_signal = "BUY PE"
            final_conf = confidence if confidence == "HIGH" else "MEDIUM"
        elif buf.count("BUY CE") >= 1 and confidence in ("HIGH", "MEDIUM"):
            final_signal = "BUY CE"; final_conf = "MEDIUM"
        elif buf.count("BUY PE") >= 1 and confidence in ("HIGH", "MEDIUM"):
            final_signal = "BUY PE"; final_conf = "MEDIUM"
        else:
            final_signal = "WAIT"; final_conf = "LOW"

        return final_signal, final_conf, buf

    # ──────────────────────────────────────────────
    # 4. DETECT TRAP  *** VERBATIM FROM app.py ***
    # ──────────────────────────────────────────────
    def detect_trap(
        self,
        spot: float,
        support: int,
        resistance: int,
        total_ce_delta: float,
        total_pe_delta: float,
    ) -> str:
        """Detect bull/bear traps based on spot vs S/R and OI delta flow.

        Returns
        -------
        str
            "NONE", "🚨 BULL TRAP", or "🚨 BEAR TRAP"
        """
        trap="NONE"
        if spot>resistance and total_ce_delta>total_pe_delta: trap="🚨 BULL TRAP"
        elif spot<support and total_pe_delta>total_ce_delta:  trap="🚨 BEAR TRAP"
        return trap

    # ──────────────────────────────────────────────
    # 5. CONFIDENCE SCORE (display-only numeric)
    # ──────────────────────────────────────────────
    def compute_confidence_score(
        self,
        market_data: Dict[str, Any],
        signal: str,
        trap: str,
    ) -> int:
        """Compute a 0-100 numeric confidence score for display purposes.

        This score does NOT gate trading decisions — only the categorical
        signal + buffer confirmation does.

        Breakdown
        ---------
        PCR strength          : 0-25   (how far PCR is from 1.0)
        VWAP distance         : 0-20   (how far spot is from VWAP proxy)
        OI delta magnitude    : 0-20   (imbalance between CE/PE delta)
        PCR momentum          : 0-15   (RISING/FALLING vs FLAT)
        S/R proximity         : 0-10   (how close spot is to S/R)
        Trap penalty          : -10    (if trap detected)
        """
        pcr = market_data["pcr"]
        spot = market_data["spot"]
        vwap_proxy = market_data["vwap_proxy"]
        total_ce_delta = market_data["total_ce_delta"]
        total_pe_delta = market_data["total_pe_delta"]
        pcr_momentum = market_data["pcr_momentum"]
        support = market_data["support"]
        resistance = market_data["resistance"]

        score = 0

        # ── PCR strength: distance from neutral (1.0) ──
        pcr_dist = abs(pcr - 1.0)
        pcr_score = min(CONF_WEIGHT_PCR, round(pcr_dist / 0.5 * CONF_WEIGHT_PCR))
        score += pcr_score

        # ── VWAP distance ──
        if vwap_proxy > 0:
            vwap_pct = abs(spot - vwap_proxy) / vwap_proxy
            vwap_score = min(CONF_WEIGHT_VWAP, round(vwap_pct / 0.005 * CONF_WEIGHT_VWAP))
        else:
            vwap_score = 0
        score += vwap_score

        # ── OI delta magnitude ──
        delta_diff = abs(total_pe_delta - total_ce_delta)
        total_delta = abs(total_ce_delta) + abs(total_pe_delta)
        if total_delta > 0:
            delta_ratio = delta_diff / total_delta
            oi_score = min(CONF_WEIGHT_OI_DELTA, round(delta_ratio * CONF_WEIGHT_OI_DELTA))
        else:
            oi_score = 0
        score += oi_score

        # ── PCR momentum ──
        if pcr_momentum in ("RISING", "FALLING"):
            score += CONF_WEIGHT_PCR_MOM
        else:
            score += max(0, CONF_WEIGHT_PCR_MOM // 3)  # ~5 for FLAT

        # ── S/R proximity ──
        sr_range = abs(resistance - support) if resistance != support else 1
        if signal == "BUY CE":
            sr_dist = abs(spot - support)
        elif signal == "BUY PE":
            sr_dist = abs(spot - resistance)
        else:
            sr_dist = min(abs(spot - support), abs(spot - resistance))

        sr_ratio = 1.0 - min(1.0, sr_dist / sr_range)
        score += min(CONF_WEIGHT_SR_PROX, round(sr_ratio * CONF_WEIGHT_SR_PROX))

        # ── Trap penalty ──
        if trap != "NONE":
            score -= CONF_PENALTY_TRAP

        return max(0, min(100, score))

    # ──────────────────────────────────────────────
    # 6. SIDEWAYS DETECTION (advisory only)
    # ──────────────────────────────────────────────
    def detect_sideways(
        self,
        spot_history: List[float],
        pcr: float,
    ) -> Tuple[bool, str]:
        """Detect sideways/range-bound market conditions.

        Parameters
        ----------
        spot_history : list[float]
            Recent spot readings.
        pcr : float
            Current PCR value.

        Returns
        -------
        (is_sideways, sideways_strength)
            sideways_strength is "STRONG SIDEWAYS", "MILD SIDEWAYS", or ""
        """
        pcr_neutral = SIDEWAYS_PCR_LOW <= pcr <= SIDEWAYS_PCR_HIGH

        if len(spot_history) >= 20:
            recent = spot_history[-20:]
            mean_spot = statistics.mean(recent)
            if mean_spot > 0:
                stdev = statistics.stdev(recent)
                stdev_pct = stdev / mean_spot
                if stdev_pct < SIDEWAYS_SPOT_STDEV_PCT and pcr_neutral:
                    return True, "STRONG SIDEWAYS"

        if pcr_neutral:
            return True, "MILD SIDEWAYS"

        return False, ""
