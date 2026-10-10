"""
V12 PRO MAX — Angel One SmartWebSocket Manager
Streams real-time sub-50ms ticks for Spot Indices and Option Contracts.
Provides high-frequency live pricing and Open Interest to the SignalEngine and TradeManager.
"""
import time
import threading
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from utils.logger import get_logger
    log = get_logger("websocket_manager")
except ImportError:
    log = logging.getLogger("websocket_manager")
    if not log.handlers:
        log.addHandler(logging.StreamHandler())
        log.setLevel(logging.INFO)

try:
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    HAS_SMART_WS = True
except ImportError:
    HAS_SMART_WS = False
    log.warning("SmartWebSocketV2 not installed in Python environment.")


class SmartWebSocketManager:
    """Thread-safe WebSocket manager streaming live market ticks from Angel One."""

    def __init__(
        self,
        auth_token: str,
        api_key: str,
        client_code: str,
        feed_token: str,
        max_retries: int = 5,
    ) -> None:
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_code = client_code
        self.feed_token = feed_token
        self.max_retries = max_retries

        self._lock = threading.RLock()
        self._is_connected = False
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self.sws: Optional[SmartWebSocketV2] = None

        # Thread-safe in-memory cache: token (str) -> dict
        # { "ltp": float, "oi": int, "vol": int, "updated_at": float, "exchange_type": int }
        self._ticks: Dict[str, Dict[str, Any]] = {}

        # Subscriptions tracking: exchangeType (int) -> set of tokens (str)
        # 1 = NSE_CM, 2 = NSE_FO
        self._subscriptions: Dict[int, Set[str]] = {1: set(), 2: set()}

        # Rate-limiting / deduplication for subscription calls
        self._pending_subscriptions: Dict[int, Set[str]] = {1: set(), 2: set()}

    def start(self) -> bool:
        """Start WebSocket connection in a background daemon thread."""
        if not HAS_SMART_WS:
            log.warning("SmartWebSocketV2 unavailable. Cannot start streaming.")
            return False

        with self._lock:
            if self._is_running:
                return True

            try:
                self.sws = SmartWebSocketV2(
                    auth_token=self.auth_token,
                    api_key=self.api_key,
                    client_code=self.client_code,
                    feed_token=self.feed_token,
                    max_retry_attempt=self.max_retries,
                    retry_strategy=1,
                    retry_delay=5,
                )

                self.sws.on_open = self._on_open
                self.sws.on_data = self._on_data
                self.sws.on_error = self._on_error
                self.sws.on_close = self._on_close

                self._is_running = True
                self._thread = threading.Thread(
                    target=self._run_connection,
                    name="AngelOne_WS_Thread",
                    daemon=True,
                )
                self._thread.start()
                log.info("SmartWebSocketManager started in background thread")
                return True
            except Exception as e:
                log.error("Failed to start SmartWebSocketManager: %s", e)
                self._is_running = False
                return False

    def _run_connection(self) -> None:
        """Worker thread executing sws.connect()."""
        while self._is_running:
            try:
                log.info("Connecting to Angel One WebSocket...")
                if self.sws:
                    self.sws.connect()
            except Exception as e:
                log.warning("WebSocket connect error: %s", e)
            
            if not self._is_running:
                break
            time.sleep(3)

    def _on_open(self, wsapp: Any) -> None:
        """Handle successful connection."""
        log.info("WebSocket connected to Angel One server successfully")
        with self._lock:
            self._is_connected = True
            # Re-subscribe all active tokens upon connection
            self._resubscribe_all()

    def _on_data(self, wsapp: Any, data: Dict[str, Any]) -> None:
        """Process incoming live binary tick."""
        try:
            token = str(data.get("token", "")).strip()
            if not token:
                return

            raw_ltp = data.get("last_traded_price")
            raw_oi = data.get("open_interest")
            raw_vol = data.get("volume_trade_for_the_day")
            exch_type = data.get("exchange_type", 1)

            # LTP from binary stream is in paise (divide by 100 to get rupees)
            ltp = round(float(raw_ltp) / 100.0, 2) if raw_ltp is not None else 0.0
            oi = int(raw_oi) if raw_oi is not None else 0
            vol = int(raw_vol) if raw_vol is not None else 0

            with self._lock:
                existing = self._ticks.get(token, {})
                self._ticks[token] = {
                    "ltp": ltp if ltp > 0 else existing.get("ltp", 0.0),
                    "oi": oi if oi > 0 else existing.get("oi", 0),
                    "vol": vol if vol > 0 else existing.get("vol", 0),
                    "exchange_type": exch_type,
                    "updated_at": time.time(),
                }
        except Exception as e:
            log.debug("Error parsing live tick: %s", e)

    def _on_error(self, wsapp: Any, error: Any) -> None:
        """Handle error from WebSocket."""
        log.warning("WebSocket error: %s", error)

    def _on_close(self, wsapp: Any) -> None:
        """Handle connection closure."""
        with self._lock:
            self._is_connected = False
        log.info("WebSocket connection closed")

    def _resubscribe_all(self) -> None:
        """Resubscribe all registered tokens (e.g. after reconnect)."""
        if not self.sws or not self._is_connected:
            return

        with self._lock:
            token_list = []
            for exch, tokens in self._subscriptions.items():
                if tokens:
                    token_list.append({"exchangeType": exch, "tokens": list(tokens)})

            if token_list:
                try:
                    # mode=3 (SNAP_QUOTE) brings both LTP and Open Interest (OI)
                    self.sws.subscribe(correlation_id="v12_resub", mode=3, token_list=token_list)
                    log.info("Resubscribed %d total tokens across exchanges", sum(len(t) for t in self._subscriptions.values()))
                except Exception as e:
                    log.warning("Resubscription failed: %s", e)

    def subscribe_tokens(self, exchange_type: int, tokens: List[str]) -> bool:
        """Subscribe a list of tokens on exchange_type (1=NSE_CM, 2=NSE_FO)."""
        if not tokens:
            return True

        clean_tokens = [str(t).strip() for t in tokens if str(t).strip()]
        new_tokens = []

        with self._lock:
            curr_set = self._subscriptions.setdefault(exchange_type, set())
            for t in clean_tokens:
                if t not in curr_set:
                    curr_set.add(t)
                    new_tokens.append(t)

        if not new_tokens or not self._is_connected or not self.sws:
            return False

        try:
            # Batch into groups of 50
            for i in range(0, len(new_tokens), 50):
                batch = new_tokens[i:i + 50]
                token_list = [{"exchangeType": exchange_type, "tokens": batch}]
                self.sws.subscribe(
                    correlation_id=f"sub_{exchange_type}_{i}",
                    mode=3,  # SNAP_QUOTE: LTP + OI
                    token_list=token_list,
                )
            log.info("Subscribed %d new tokens on exchange %d", len(new_tokens), exchange_type)
            return True
        except Exception as e:
            log.warning("Subscription error on exchange %d: %s", exchange_type, e)
            return False

    def unsubscribe_tokens(self, exchange_type: int, tokens: List[str]) -> bool:
        """Unsubscribe tokens when a trade closes to keep stream efficient."""
        if not tokens:
            return True

        clean_tokens = [str(t).strip() for t in tokens if str(t).strip()]
        with self._lock:
            curr_set = self._subscriptions.get(exchange_type, set())
            removed = []
            for t in clean_tokens:
                if t in curr_set:
                    curr_set.remove(t)
                    removed.append(t)

        if not removed or not self._is_connected or not self.sws:
            return False

        try:
            token_list = [{"exchangeType": exchange_type, "tokens": removed}]
            self.sws.unsubscribe(
                correlation_id=f"unsub_{exchange_type}",
                mode=3,
                token_list=token_list,
            )
            return True
        except Exception as e:
            log.warning("Unsubscribe error: %s", e)
            return False

    def get_live_tick(self, token: str) -> Optional[Dict[str, Any]]:
        """Return the latest live tick dict for token: {'ltp', 'oi', 'vol', 'updated_at'}."""
        with self._lock:
            return self._ticks.get(str(token))

    def get_live_ltp(self, token: str) -> Optional[float]:
        """Return the latest LTP in rupees for token if available."""
        with self._lock:
            tick = self._ticks.get(str(token))
            if tick and tick.get("ltp", 0.0) > 0:
                return float(tick["ltp"])
        return None

    def get_live_oi(self, token: str) -> Optional[int]:
        """Return the latest Open Interest for token if available."""
        with self._lock:
            tick = self._ticks.get(str(token))
            if tick and tick.get("oi", 0) > 0:
                return int(tick["oi"])
        return None

    def is_connected(self) -> bool:
        """Return True if WebSocket connection is live and active."""
        return self._is_connected

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic metrics for the WebSocket manager."""
        with self._lock:
            return {
                "connected": self._is_connected,
                "running": self._is_running,
                "cached_ticks_count": len(self._ticks),
                "subscribed_cm": len(self._subscriptions.get(1, set())),
                "subscribed_fo": len(self._subscriptions.get(2, set())),
            }

    def stop(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._is_running = False
        with self._lock:
            if self.sws:
                try:
                    self.sws.close_connection()
                except Exception:
                    pass
            self._is_connected = False
        log.info("SmartWebSocketManager stopped")
