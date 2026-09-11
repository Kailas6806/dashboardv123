"""
V12 PRO MAX — NSE Data Fetcher
Fetches option chain data from NSE via indian_options_fetcher with:
- TTL cache to avoid duplicate fetches within refresh cycles
- Exponential backoff retries on failure
- Per-index rate limiting
- Health check
"""
import threading
import time
from typing import Any, Dict, Optional, Tuple

from jugaad_data.nse import NSELive

from config import (
    CACHE_TTL_SECONDS,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
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


def _map_response(raw: Any) -> Optional[Dict[str, Any]]:
    """Map indian_options_fetcher compact response to the NSE dict shape.

    Expected output shape:
        {
            "records": {
                "data": [ {"strikePrice": N, "CE": {"lastPrice": N, "openInterest": N}, "PE": {...}}, ... ],
                "underlyingValue": N,
            }
        }
    """
    if raw is None:
        return None

    # indian_options_fetcher returns a dict with "data" list and "underlyingValue"
    # Handle both flat dict and nested-records dict returned by the library.
    if isinstance(raw, dict) and "records" in raw:
        # Already NSE-shaped — pass through
        return raw

    # Compact format: top-level keys "data" and "underlyingValue"
    try:
        underlying = float(raw.get("underlyingValue") or raw.get("underlying_value") or 0)
        rows = raw.get("data") or raw.get("strikes") or []

        mapped_rows = []
        for row in rows:
            strike = row.get("strikePrice") or row.get("strike_price") or row.get("strike", 0)
            ce_raw = row.get("CE") or row.get("ce") or {}
            pe_raw = row.get("PE") or row.get("pe") or {}

            mapped_rows.append({
                "strikePrice": float(strike),
                "CE": {
                    "lastPrice": float(ce_raw.get("lastPrice") or ce_raw.get("last_price") or 0),
                    "openInterest": float(ce_raw.get("openInterest") or ce_raw.get("open_interest") or 0),
                    "changeinOpenInterest": float(
                        ce_raw.get("changeinOpenInterest") or ce_raw.get("change_in_open_interest") or 0
                    ),
                },
                "PE": {
                    "lastPrice": float(pe_raw.get("lastPrice") or pe_raw.get("last_price") or 0),
                    "openInterest": float(pe_raw.get("openInterest") or pe_raw.get("open_interest") or 0),
                    "changeinOpenInterest": float(
                        pe_raw.get("changeinOpenInterest") or pe_raw.get("change_in_open_interest") or 0
                    ),
                },
            })

        return {
            "records": {
                "data": mapped_rows,
                "underlyingValue": underlying,
            }
        }
    except Exception as e:
        log.error("_map_response: failed to map response: %s", e)
        return None


class NSEDataFetcher:
    """Resilient NSE option chain fetcher with caching.

    Uses indian_options_fetcher under the hood. Wraps it with:
    - TTLCache to avoid hammering NSE within the same refresh cycle
    - Exponential backoff on transient failures
    - Per-index rate limiting to respect MIN_REQUEST_INTERVAL
    """

    def __init__(self) -> None:
        """Initialize fetcher."""
        self._cache = TTLCache(default_ttl=CACHE_TTL_SECONDS)
        self._total_fetches: int = 0
        self._total_errors: int = 0
        self._last_request_time: Dict[str, float] = {}  # idx -> timestamp
        self._nse = NSELive()
        log.info("NSEDataFetcher initialized (jugaad_data backend)")

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
            Option chain dict with keys records.data and records.underlyingValue,
            or None on failure.
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

                try:
                    raw = self._nse.index_option_chain(idx_name)
                except Exception:
                    # Recreate session if expired
                    self._nse = NSELive()
                    raw = self._nse.index_option_chain(idx_name)

                data = _map_response(raw)

                if data and "records" in data and data["records"].get("data"):
                    self._cache.set(idx_name, data)
                    return data
                else:
                    log.warning(
                        "%s: Empty/invalid response on attempt %d",
                        idx_name, attempt + 1,
                    )

            except Exception as e:
                self._total_errors += 1
                log.warning(
                    "%s: Fetch error on attempt %d/%d: %s",
                    idx_name, attempt + 1, MAX_RETRIES, e,
                )

                # Exponential backoff
                if attempt < MAX_RETRIES - 1:
                    backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    log.debug("Backing off %.2fs before retry", backoff)
                    time.sleep(backoff)

        log.error(
            "%s: All %d fetch attempts failed",
            idx_name, MAX_RETRIES,
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
        """Force-expire cache for a specific index."""
        self._cache.invalidate(idx_name)
        log.debug("Cache invalidated for %s", idx_name)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache and fetcher performance statistics."""
        cache_stats = self._cache.get_stats()
        return {
            **cache_stats,
            "total_fetches": self._total_fetches,
            "total_errors": self._total_errors,
        }


# ──────────────────────────────────────────────────
# THREAD-SAFE SINGLETON
# ──────────────────────────────────────────────────
_fetcher_lock = threading.Lock()
_global_fetcher = None

def get_fetcher() -> NSEDataFetcher:
    """Get or create the singleton NSEDataFetcher (thread-safe)."""
    global _global_fetcher
    if _global_fetcher is None:
        with _fetcher_lock:
            if _global_fetcher is None:
                _global_fetcher = NSEDataFetcher()
    return _global_fetcher
