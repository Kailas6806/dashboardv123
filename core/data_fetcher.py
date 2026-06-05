"""
V12 PRO MAX — NSE Data Fetcher
Fetches option chain data from NSE via jugaad_data with:
- TTL cache to avoid duplicate fetches within refresh cycles
- Exponential backoff retries on failure
- Auto session recovery after consecutive failures
- Per-index rate limiting
- Health check
"""
import threading
import time
from typing import Any, Dict, Optional, Tuple

import streamlit as st
from jugaad_data.nse import NSELive

from config import (
    CACHE_TTL_SECONDS,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
    AUTO_RECOVERY_THRESHOLD,
    MIN_REQUEST_INTERVAL,
    INDEX_CONFIG,
)
from utils.cache import TTLCache

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


log = get_logger("data_fetcher")


class NSEDataFetcher:
    """Resilient NSE option chain fetcher with caching and auto-recovery.

    Uses jugaad_data's NSELive under the hood. Wraps it with:
    - TTLCache to avoid hammering NSE within the same refresh cycle
    - Exponential backoff on transient failures
    - Full session rebuild after AUTO_RECOVERY_THRESHOLD consecutive failures
    - Per-index rate limiting to respect MIN_REQUEST_INTERVAL
    """

    def __init__(self) -> None:
        """Initialize fetcher with fresh NSELive session."""
        self._nse: Optional[NSELive] = None
        self._cache = TTLCache(default_ttl=CACHE_TTL_SECONDS)
        self._consecutive_failures: int = 0
        self._total_fetches: int = 0
        self._total_errors: int = 0
        self._last_request_time: Dict[str, float] = {}  # idx -> timestamp

        self._create_session()
        log.info("NSEDataFetcher initialized")

    # ──────────────────────────────────────────────
    # SESSION MANAGEMENT
    # ──────────────────────────────────────────────
    def _create_session(self) -> None:
        """Create a fresh NSELive instance."""
        try:
            self._nse = NSELive()
            log.info("NSELive session created")
        except Exception as e:
            log.error("Failed to create NSELive session: %s", e)
            self._nse = None

    def _rebuild_session(self) -> None:
        """Full teardown and rebuild of the NSE session."""
        log.warning(
            "Rebuilding NSE session after %d consecutive failures",
            self._consecutive_failures,
        )
        # Teardown
        self._nse = None
        self._cache.clear()
        time.sleep(1)  # brief pause before reconnecting

        # Rebuild
        self._create_session()
        self._consecutive_failures = 0
        log.info("NSE session rebuilt successfully")

    # ──────────────────────────────────────────────
    # FETCH OPTION CHAIN
    # ──────────────────────────────────────────────
    def fetch_option_chain(self, idx_name: str) -> Optional[Dict[str, Any]]:
        """Fetch option chain data for an index.

        Parameters
        ----------
        idx_name : str
            Index name, e.g. "NIFTY", "BANKNIFTY", "FINNIFTY".

        Returns
        -------
        dict or None
            Raw option chain dict from NSE, or None on failure.
        """
        # ── Check cache first ──
        cached = self._cache.get(idx_name)
        if cached is not None:
            return cached

        # ── Rate limit check ──
        now = time.time()
        last_req = self._last_request_time.get(idx_name, 0)
        elapsed = now - last_req
        if elapsed < MIN_REQUEST_INTERVAL:
            wait = MIN_REQUEST_INTERVAL - elapsed
            log.debug("Rate limit: waiting %.2fs for %s", wait, idx_name)
            time.sleep(wait)

        # ── Fetch with retries ──
        for attempt in range(MAX_RETRIES):
            try:
                self._last_request_time[idx_name] = time.time()
                self._total_fetches += 1

                if self._nse is None:
                    self._create_session()
                    if self._nse is None:
                        raise ConnectionError("Cannot create NSELive session")

                data = self._nse.index_option_chain(idx_name)

                if data and "records" in data and data["records"].get("data"):
                    # Success — reset failure counter, cache, return
                    self._consecutive_failures = 0
                    self._cache.set(idx_name, data)
                    return data
                else:
                    self._consecutive_failures += 1
                    log.warning(
                        "%s: Empty/invalid response on attempt %d",
                        idx_name, attempt + 1,
                    )

            except Exception as e:
                self._total_errors += 1
                self._consecutive_failures += 1
                log.warning(
                    "%s: Fetch error on attempt %d/%d: %s",
                    idx_name, attempt + 1, MAX_RETRIES, e,
                )

                # Auto recovery check
                if self._consecutive_failures >= AUTO_RECOVERY_THRESHOLD:
                    self._rebuild_session()

                # Exponential backoff
                if attempt < MAX_RETRIES - 1:
                    backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    log.debug("Backing off %.2fs before retry", backoff)
                    time.sleep(backoff)

                # Session might be stale — recreate for next attempt
                self._nse = None

        log.error(
            "%s: All %d fetch attempts failed (%d consecutive failures)",
            idx_name, MAX_RETRIES, self._consecutive_failures,
        )
        return None

    # ──────────────────────────────────────────────
    # GET STRIKE PRICE
    # ──────────────────────────────────────────────
    def get_strike_price(
        self, idx_name: str, strike: float, signal: str
    ) -> Tuple[Optional[float], Optional[float]]:
        """Get LTP for a specific strike from the option chain.

        Parameters
        ----------
        idx_name : str
            Index name.
        strike : float
            Strike price to look up.
        signal : str
            "BUY CE" or "BUY PE" to determine which option side.

        Returns
        -------
        (ltp, spot) or (None, None)
        """
        try:
            data = self.fetch_option_chain(idx_name)
            if not data or "records" not in data:
                return None, None

            records = data["records"]["data"]
            spot = data["records"]["underlyingValue"]

            try:
                strike = float(strike)
            except (ValueError, TypeError):
                return None, spot

            for item in records:
                if float(item.get("strikePrice", 0)) == strike:
                    if signal == "BUY CE":
                        ce_opt = item.get("CE") or {}
                        ltp = round(
                            float(ce_opt.get("lastPrice", 0) or 0), 2
                        )
                    else:
                        pe_opt = item.get("PE") or {}
                        ltp = round(
                            float(pe_opt.get("lastPrice", 0) or 0), 2
                        )
                    return ltp, spot

            return None, spot

        except Exception as e:
            log.error("get_strike_price error for %s strike=%.0f: %s", idx_name, strike, e)
            return None, None

    # ──────────────────────────────────────────────
    # GET ATM PRICES
    # ──────────────────────────────────────────────
    def get_atm_prices(
        self, idx_name: str
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Get ATM CE and PE LTPs for an index.

        Parameters
        ----------
        idx_name : str
            Index name.

        Returns
        -------
        (ce_ltp, pe_ltp, spot) or (None, None, None)
        """
        try:
            step = INDEX_CONFIG[idx_name]["step"]
            data = self.fetch_option_chain(idx_name)
            if not data or "records" not in data:
                return None, None, None

            records = data["records"]["data"]
            spot = data["records"]["underlyingValue"]
            atm = round(spot / step) * step

            best_dist = float("inf")
            ce_ltp = 0.0
            pe_ltp = 0.0

            for item in records:
                s = item.get("strikePrice", 0)
                dist = abs(s - atm)
                if dist < best_dist:
                    best_dist = dist
                    ce_opt = item.get("CE") or {}
                    pe_opt = item.get("PE") or {}
                    ce_ltp = ce_opt.get("lastPrice", 0) or 0
                    pe_ltp = pe_opt.get("lastPrice", 0) or 0

            return round(float(ce_ltp), 2), round(float(pe_ltp), 2), spot

        except Exception as e:
            log.error("get_atm_prices error for %s: %s", idx_name, e)
            return None, None, None

    # ──────────────────────────────────────────────
    # HEALTH CHECK
    # ──────────────────────────────────────────────
    def health_check(self) -> bool:
        """Try a simple fetch to verify connectivity.

        Returns
        -------
        bool
            True if NSE is reachable and returning data.
        """
        try:
            data = self.fetch_option_chain("NIFTY")
            healthy = data is not None
            log.info("Health check: %s", "PASS" if healthy else "FAIL")
            return healthy
        except Exception as e:
            log.error("Health check failed: %s", e)
            return False

    # ──────────────────────────────────────────────
    # CACHE MANAGEMENT
    # ──────────────────────────────────────────────
    def invalidate_cache(self, idx_name: str) -> None:
        """Force-expire cache for a specific index.

        Parameters
        ----------
        idx_name : str
            Index name whose cache entry should be invalidated.
        """
        self._cache.invalidate(idx_name)
        log.debug("Cache invalidated for %s", idx_name)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache and fetcher performance statistics.

        Returns
        -------
        dict
            Combined stats: cache hits/misses + fetcher totals/errors.
        """
        cache_stats = self._cache.get_stats()
        return {
            **cache_stats,
            "total_fetches": self._total_fetches,
            "total_errors": self._total_errors,
            "consecutive_failures": self._consecutive_failures,
            "session_active": self._nse is not None,
        }


# ──────────────────────────────────────────────────
# THREAD-SAFE SINGLETON
# ──────────────────────────────────────────────────
_fetcher_lock = threading.Lock()
_global_fetcher = None

def get_fetcher() -> NSEDataFetcher:
    """Get or create the singleton NSEDataFetcher (thread-safe).

    Returns
    -------
    NSEDataFetcher
        The shared fetcher instance.
    """
    global _global_fetcher
    if _global_fetcher is None:
        with _fetcher_lock:
            if _global_fetcher is None:
                _global_fetcher = NSEDataFetcher()
    return _global_fetcher
