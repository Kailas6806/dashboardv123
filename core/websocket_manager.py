"""
V12 PRO MAX — Angel One SmartWebSocket Manager
Streams real-time sub-50ms ticks for Spot Indices and Option Contracts.
Provides high-frequency live pricing and Open Interest to the SignalEngine and TradeManager.
"""
import time
import threading
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import config

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

    _active_instance: Optional["SmartWebSocketManager"] = None
    _global_ws_lock = threading.RLock()

    def __init__(
        self,
        auth_token: str,
        api_key: str,
        client_code: str,
        feed_token: str,
        max_retries: int = 5,
        token_refresher: Optional[Callable[[], Tuple[Optional[str], Optional[str]]]] = None,
    ) -> None:
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_code = client_code
        self.feed_token = feed_token
        self.max_retries = max_retries
        self._token_refresher = token_refresher

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
        self._reconnect_attempts: int = 0

        # Live telemetry tracking
        self._recent_ticks: List[Dict[str, Any]] = []
        self._last_tick_time: Optional[float] = None
        self._total_ticks_received: int = 0

    @staticmethod
    def is_market_hours() -> bool:
        """Return True only on weekdays between 09:00 and 15:35 IST."""
        try:
            import datetime
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            now = datetime.datetime.now(ist)
        except Exception:
            import datetime
            now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

        # 5 = Saturday, 6 = Sunday
        if now.weekday() >= 5:
            return False

        t = now.time()
        import datetime as _dt
        return _dt.time(9, 0) <= t <= _dt.time(15, 35)

    def start(self) -> bool:
        """Start WebSocket connection in a background daemon thread."""
        if not HAS_SMART_WS:
            log.warning("SmartWebSocketV2 unavailable. Cannot start streaming.")
            return False

        try:
            import config
            if not getattr(config, "ENABLE_WEBSOCKET", True):
                log.info("SmartWebSocket is disabled via ENABLE_WEBSOCKET=False config.")
                return False
        except Exception:
            pass

        if not self.is_market_hours():
            log.info("Market is closed. SmartWebSocket streaming halted to protect Angel One account from lockout.")
            return False

        with SmartWebSocketManager._global_ws_lock:
            # Enforce strict process-level singleton: stop any existing active instance
            if SmartWebSocketManager._active_instance is not None and SmartWebSocketManager._active_instance is not self:
                try:
                    log.info("Halting previous SmartWebSocketManager instance to prevent socket collision...")
                    SmartWebSocketManager._active_instance.stop()
                except Exception as ex:
                    log.debug("Error stopping previous WebSocket instance: %s", ex)
            SmartWebSocketManager._active_instance = self

        with self._lock:
            if self._is_running and self._thread and self._thread.is_alive():
                return True

            try:
                self.sws = SmartWebSocketV2(
                    auth_token=self.auth_token,
                    api_key=self.api_key,
                    client_code=self.client_code,
                    feed_token=self.feed_token,
                    max_retry_attempt=2,
                    retry_strategy=1,
                    retry_delay=5,
                )

                self.sws.on_open = self._on_open
                self.sws.on_data = self._on_data
                self.sws.on_error = self._on_error
                self.sws.on_close = self._on_close

                self._is_running = True
                self._reconnect_attempts = 0
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
        """Worker thread executing sws.connect(). Halts immediately on off-market or repeated disconnects."""
        self._reconnect_attempts = 0
        while self._is_running:
            if not self.is_market_hours():
                log.info("Market is closed. Halting WebSocket background connection to protect account.")
                with self._lock:
                    self._is_running = False
                    self._is_connected = False
                break

            try:
                log.info("Connecting to Angel One WebSocket...")
                if self.sws:
                    self.sws.connect()
            except Exception as e:
                log.warning("WebSocket connect error: %s", e)

            # Check if market closed or manager stopped while connect() was blocking
            if not self._is_running or not self.is_market_hours():
                with self._lock:
                    self._is_running = False
                    self._is_connected = False
                break

            self._reconnect_attempts += 1

            # Auto-refresh session tokens on persistent disconnects:
            # If socket fails 2 consecutive times, re-authenticate with Angel One to fetch a fresh feedToken
            if self._reconnect_attempts >= 2 and self._token_refresher:
                log.warning("WebSocket disconnected (%d consecutive attempts). Re-authenticating with Angel One for fresh feedToken...", self._reconnect_attempts)
                try:
                    new_auth, new_feed = self._token_refresher()
                    if new_auth and new_feed:
                        with self._lock:
                            self.auth_token = new_auth
                            self.feed_token = new_feed
                        log.info("Fresh Angel One tokens acquired for WebSocket.")
                except Exception as ex:
                    log.warning("Failed to refresh Angel One WebSocket tokens: %s", ex)

            # Always re-instantiate a clean SmartWebSocketV2 client to reset internal retry counters
            with self._lock:
                try:
                    self.sws = SmartWebSocketV2(
                        auth_token=self.auth_token,
                        api_key=self.api_key,
                        client_code=self.client_code,
                        feed_token=self.feed_token,
                        max_retry_attempt=2,
                        retry_strategy=1,
                        retry_delay=5,
                    )
                    self.sws.on_open = self._on_open
                    self.sws.on_data = self._on_data
                    self.sws.on_error = self._on_error
                    self.sws.on_close = self._on_close
                except Exception as ws_ex:
                    log.warning("Failed to re-instantiate SmartWebSocketV2: %s", ws_ex)

            if self._reconnect_attempts >= 5:
                log.warning("WebSocket disconnected (%d consecutive attempts). Cooling down for 30s before reconnecting...", self._reconnect_attempts)
                time.sleep(30)
                self._reconnect_attempts = 0
            else:
                backoff = min(5 * self._reconnect_attempts, 20)
                log.info("Reconnecting WebSocket in %ds (attempt %d)...", backoff, self._reconnect_attempts)
                time.sleep(backoff)

    def _on_open(self, wsapp: Any) -> None:
        """Handle successful connection."""
        log.info("WebSocket connected to Angel One server successfully")
        with self._lock:
            self._is_connected = True
            self._reconnect_attempts = 0
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

            now_ts = time.time()
            with self._lock:
                self._last_tick_time = now_ts
                self._total_ticks_received += 1
                existing = self._ticks.get(token, {})
                tick_entry = {
                    "token": token,
                    "ltp": ltp if ltp > 0 else existing.get("ltp", 0.0),
                    "oi": oi if oi > 0 else existing.get("oi", 0),
                    "vol": vol if vol > 0 else existing.get("vol", 0),
                    "exchange_type": exch_type,
                    "updated_at": now_ts,
                }
                self._ticks[token] = tick_entry

                self._recent_ticks.insert(0, {
                    "token": token,
                    "ltp": ltp if ltp > 0 else existing.get("ltp", 0.0),
                    "oi": oi if oi > 0 else existing.get("oi", 0),
                    "vol": vol if vol > 0 else existing.get("vol", 0),
                    "exchange_type": exch_type,
                    "timestamp": now_ts,
                })
                if len(self._recent_ticks) > 50:
                    self._recent_ticks = self._recent_ticks[:50]
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
                "total_ticks_received": self._total_ticks_received,
                "last_tick_time": self._last_tick_time,
                "subscribed_cm": len(self._subscriptions.get(1, set())),
                "subscribed_fo": len(self._subscriptions.get(2, set())),
            }

    def get_all_ticks(self) -> Dict[str, Dict[str, Any]]:
        """Return a snapshot copy of all current live ticks in memory."""
        with self._lock:
            return {tok: dict(data) for tok, data in self._ticks.items()}

    def get_recent_ticks_stream(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Return the most recent incoming live ticks stream."""
        with self._lock:
            return [dict(t) for t in self._recent_ticks[:limit]]

    def get_subscriptions(self) -> Dict[int, Set[str]]:
        """Return subscribed tokens by exchange."""
        with self._lock:
            return {exch: set(tokens) for exch, tokens in self._subscriptions.items()}

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
        with SmartWebSocketManager._global_ws_lock:
            if SmartWebSocketManager._active_instance is self:
                SmartWebSocketManager._active_instance = None
        log.info("SmartWebSocketManager stopped")
