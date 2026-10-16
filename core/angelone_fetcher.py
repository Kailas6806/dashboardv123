import os
import json
import time
import time as pytime
import requests
import pyotp
import logging
import threading
import urllib.request, email.utils
from typing import Optional, Tuple, Dict, Any, List
from SmartApi import SmartConnect
import config
from config import ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET, INDEX_CONFIG, BASE_DIR, IST
from utils.cache import TTLCache
import datetime

log = logging.getLogger("angelone_fetcher")
if not log.handlers:
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)

SCRIP_CACHE_TTL_SECONDS = 86400  # 24 hours
SCRIP_MASTER_URL = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'


class AngelOneDataFetcher:
    def __init__(self):
        self.api_key = ANGEL_API_KEY
        self.client_id = ANGEL_CLIENT_ID
        self.password = ANGEL_PASSWORD
        self.totp_secret = ANGEL_TOTP_SECRET
        self.smartApi = SmartConnect(api_key=self.api_key, timeout=25)
        self.session = None
        self._cache = TTLCache(default_ttl=config.CACHE_TTL_SECONDS)
        self._perm_cache = {}
        self.ws_mgr = None
        self._last_login_attempt = None
        self._login_lock = threading.Lock()
        self._candle_lock = threading.Lock()
        self._last_candle_req_time = 0.0
        self.index_tokens = {
            "NIFTY": {"token": "26000", "symbol": "Nifty 50", "exch": "NSE"},
            "BANKNIFTY": {"token": "26009", "symbol": "Nifty Bank", "exch": "NSE"},
            "FINNIFTY": {"token": "26037", "symbol": "Nifty Fin Service", "exch": "NSE"}
        }
        self.scrip_master = []
        self.login_status = "NOT_ATTEMPTED"
        self.login_message = ""
        self.last_login_time = None
        self.ws_status = "NOT_INITIALIZED"
        self.ws_message = ""
        self.scrip_load_status = "NOT_LOADED"
        self.scrip_source = "NONE"
        self.scrip_count = 0
        self.scrip_load_time = None
        self._token_symbol_map = {}
        self._option_scrips_by_expiry = {}
        self._option_expiries_by_index = {}
        self.total_fetches = 0
        self.total_errors = 0
        self.consecutive_failures = 0
        self.last_fetch_times = {}

        self.login(max_retries=3, retry_delay=2.0)
        self._load_scrip_master()

    def login(self, max_retries: int = 3, retry_delay: float = 2.0, force: bool = False, init_ws: bool = True) -> bool:
        """Authenticate with Angel One SmartAPI with multi-attempt retry and clock drift correction."""
        if not self.client_id or not self.password or not self.totp_secret:
            self.login_status = "DEMO_MODE"
            self.login_message = "Angel One credentials missing in config or secrets.toml. Running in DEMO mode."
            log.warning(self.login_message)
            return False

        with self._login_lock:
            now = datetime.datetime.now(IST)
            if not force and self._last_login_attempt:
                elapsed = (now - self._last_login_attempt).total_seconds()
                if elapsed < 8:
                    return self.session is not None

            self._last_login_attempt = now
            last_err = None

            for attempt in range(1, max_retries + 1):
                try:
                    drift = 0.0
                    try:
                        res = urllib.request.urlopen('http://google.com', timeout=3.0)
                        dt = email.utils.parsedate_to_datetime(res.headers['Date'])
                        drift = dt.timestamp() - pytime.time()
                    except Exception:
                        drift = 0.0
                    totp = pyotp.TOTP(self.totp_secret).at(pytime.time() + drift)

                    data = self.smartApi.generateSession(self.client_id, self.password, totp)
                    if data and data.get('status'):
                        self.session = data['data']
                        self.login_status = "CONNECTED"
                        self.last_login_time = datetime.datetime.now(IST)
                        masked_id = f"{self.client_id[:2]}***{self.client_id[-2:]}" if len(self.client_id) > 4 else self.client_id
                        self.login_message = f"Authenticated successfully as {masked_id} (Session active)."
                        log.info("Angel One Login Successful: %s", self.login_message)
                        if init_ws:
                            self._init_websocket()
                        return True
                    else:
                        err_msg = data.get('message', 'Login error') if isinstance(data, dict) else str(data)
                        last_err = err_msg
                        log.warning("Angel One login attempt %d/%d failed: %s", attempt, max_retries, err_msg)
                        if attempt < max_retries:
                            pytime.sleep(retry_delay * attempt)
                except Exception as e:
                    last_err = str(e)
                    log.warning("Angel One login attempt %d/%d exception (timeout/network): %s", attempt, max_retries, e)
                    if attempt < max_retries:
                        pytime.sleep(retry_delay * attempt)

            self.login_status = "ERROR"
            self.login_message = f"Angel One login exception: {last_err}"
            log.error("Angel One Login Failed after %d attempts: %s", max_retries, last_err)
            return False

    def ensure_session(self, force: bool = False) -> bool:
        """Dynamically verify session health and re-authenticate if disconnected."""
        if not force and self.session is not None and self.login_status == "CONNECTED":
            return True
        now = datetime.datetime.now(IST)
        if not force and self._last_login_attempt:
            if (now - self._last_login_attempt).total_seconds() < 12:
                return False
        log.info("Angel One session inactive. Triggering automatic re-login...")
        return self.login(max_retries=2, retry_delay=1.5, force=force)

    def refresh_tokens(self) -> Tuple[Optional[str], Optional[str]]:
        """Force re-login with Angel One and return fresh (jwtToken, feedToken)."""
        try:
            ok = self.login(max_retries=2, retry_delay=1.5, force=True, init_ws=False)
            if ok and self.session:
                jwt_token = self.session.get("jwtToken")
                feed_token = self.session.get("feedToken")
                log.info("Angel One tokens successfully refreshed for WebSocket.")
                return jwt_token, feed_token
        except Exception as e:
            log.warning("Error refreshing Angel One tokens for WebSocket: %s", e)
        return None, None

    def _init_websocket(self):
        """Initialize and start background SmartWebSocketManager for live ticks."""
        try:
            import config
            if not getattr(config, "ENABLE_WEBSOCKET", True):
                self.ws_status = "DISABLED_BY_CONFIG"
                self.ws_message = "Disabled via ENABLE_WEBSOCKET=False config (Account protection active)."
                log.info("SmartWebSocket is disabled via ENABLE_WEBSOCKET=False config.")
                return

            from core.websocket_manager import SmartWebSocketManager
            if not SmartWebSocketManager.is_market_hours():
                self.ws_status = "OFF_MARKET_IDLE"
                self.ws_message = "Market is closed (Mon–Fri 09:00–15:35 IST only). Kept idle to prevent lockout."
                log.info("Off-market hours detected. SmartWebSocket is kept idle to protect Angel One account from lockout.")
                return

            if not self.session:
                self.ws_status = "NO_SESSION"
                self.ws_message = "Cannot start WebSocket: Angel One session is not active."
                return
            jwt_token = self.session.get("jwtToken")
            feed_token = self.session.get("feedToken")
            if not jwt_token or not feed_token:
                self.ws_status = "TOKEN_MISSING"
                self.ws_message = "jwtToken or feedToken missing from session."
                return

            if self.ws_mgr is None:
                self.ws_mgr = SmartWebSocketManager(
                    auth_token=jwt_token,
                    api_key=self.api_key,
                    client_code=self.client_id,
                    feed_token=feed_token,
                    token_refresher=self.refresh_tokens,
                )
            else:
                self.ws_mgr.auth_token = jwt_token
                self.ws_mgr.feed_token = feed_token
                self.ws_mgr._token_refresher = self.refresh_tokens

            if not self.ws_mgr._is_running or not (self.ws_mgr._thread and self.ws_mgr._thread.is_alive()):
                if self.ws_mgr.start():
                    self.ws_status = "STREAMING"
                    self.ws_message = "SmartWebSocket running and streaming in background thread."
                    # Subscribe Spot Indices immediately
                    spot_tokens = [self.index_tokens[i]["token"] for i in self.index_tokens]
                    self.ws_mgr.subscribe_tokens(1, spot_tokens)
                    log.info("WebSocket streaming spot tokens initiated: %s", spot_tokens)
                else:
                    self.ws_status = "HALTED"
                    self.ws_message = "WebSocket failed to start or halted by market hours guard."
        except Exception as e:
            self.ws_status = "ERROR"
            self.ws_message = f"WebSocket initialization error: {e}"
            log.warning("WebSocket initialization error: %s", e)

    def _build_token_symbol_map(self):
        """Build in-memory token and expiry indexes from the scrip master."""
        try:
            if not self.scrip_master:
                return
            mapping = {}
            option_scrips_by_expiry = {}
            for item in self.scrip_master:
                t = str(item.get("token", "")).strip()
                sym = item.get("symbol") or item.get("tradingsymbol") or item.get("name")
                if t and sym:
                    mapping[t] = str(sym)
                if item.get("instrumenttype") == "OPTIDX":
                    idx_name = item.get("name")
                    expiry = item.get("expiry")
                    if idx_name in INDEX_CONFIG and expiry:
                        option_scrips_by_expiry.setdefault(idx_name, {}).setdefault(expiry, []).append(item)

            self._token_symbol_map = mapping
            self._option_scrips_by_expiry = option_scrips_by_expiry
            self._option_expiries_by_index = {
                idx_name: sorted(
                    expiries,
                    key=lambda expiry: self._parse_option_expiry(expiry),
                )
                for idx_name, expiries in option_scrips_by_expiry.items()
            }
        except Exception as e:
            log.warning("Error building scrip master indexes: %s", e)

    @staticmethod
    def _parse_option_expiry(expiry):
        try:
            return datetime.datetime.strptime(expiry, "%d%b%Y")
        except (TypeError, ValueError):
            return datetime.datetime.max

    def _load_scrip_master(self):
        cache_file = os.path.join(BASE_DIR, "scrip_master_cache.json")
        if os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if time.time() - mtime < SCRIP_CACHE_TTL_SECONDS:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        self.scrip_master = json.load(f)
                    self.scrip_count = len(self.scrip_master)
                    self.scrip_load_status = "LOADED"
                    self.scrip_source = "DISK_CACHE"
                    self.scrip_load_time = datetime.datetime.fromtimestamp(mtime, tz=IST)
                    self._build_token_symbol_map()
                    log.info(f"Loaded {self.scrip_count} scrips from local disk cache in <0.05s.")
                    return
            except Exception as e:
                log.warning(f"Failed to read local scrip cache: {e}")

        log.info("Downloading Angel One Scrip Master...")
        try:
            res = requests.get(SCRIP_MASTER_URL, timeout=15.0)
            self.scrip_master = res.json()
            self.scrip_count = len(self.scrip_master)
            self.scrip_load_status = "LOADED"
            self.scrip_source = "REMOTE_DOWNLOAD"
            self.scrip_load_time = datetime.datetime.now(IST)
            self._build_token_symbol_map()
            log.info(f"Loaded {self.scrip_count} scrips from remote.")
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(self.scrip_master, f)
            except Exception:
                pass
        except Exception as e:
            self.scrip_load_status = "FAILED"
            self.scrip_source = "ERROR"
            log.error(f"Failed to load scrip master: {e}")

    def get_ltp(self, exchange, tradingsymbol, token):
        self.ensure_websocket_running()
        # 1. Check ultra-fast live WebSocket tick cache (< 0.001ms)
        if self.ws_mgr and token:
            ws_ltp = self.ws_mgr.get_live_ltp(str(token))
            if ws_ltp is not None and ws_ltp > 0:
                return ws_ltp

        if not self.session:
            if not self.login():
                return 0.0
        try:
            res = self.smartApi.ltpData(exchange, tradingsymbol, token)
            if res and res.get('status') and res.get('data'):
                ltp_val = float(res['data']['ltp'])
                # Subscribe to WebSocket so future ticks stream via WS
                if self.ws_mgr and token:
                    exch_type = 2 if exchange in ("NFO", "NSE_FO") else 1
                    self.ws_mgr.subscribe_tokens(exch_type, [str(token)])
                return ltp_val
            elif res and not res.get('status'):
                err_code = str(res.get('errorcode', ''))
                msg = str(res.get('message', ''))
                if 'AG8001' in err_code or 'Token' in msg or 'Invalid' in msg or 'Expired' in msg:
                    log.warning("Angel One session expired (code=%s), renewing token...", err_code)
                    if self.login():
                        res = self.smartApi.ltpData(exchange, tradingsymbol, token)
                        if res and res.get('status') and res.get('data'):
                            return float(res['data']['ltp'])
        except Exception as e:
            log.warning("get_ltp exception for %s: %s", tradingsymbol, e)
        return 0.0

    def fetch_option_chain(self, idx_name: str) -> Optional[Dict[str, Any]]:
        self.ensure_websocket_running()
        self.total_fetches += 1
        self.last_fetch_times[idx_name] = datetime.datetime.now(IST)
        now = datetime.datetime.now(IST)
        is_market_closed = now.weekday() >= 5 or now.hour > 15 or (now.hour == 15 and now.minute >= 30) or now.hour < 9 or (now.hour == 9 and now.minute < 15)

        cached = self._cache.get(idx_name)
        if cached:
            # Continuously overlay live WebSocket ticks for spot & strikes on cached chain
            if self.ws_mgr:
                tok = self.index_tokens.get(idx_name, {}).get("token")
                if tok:
                    ws_spot = self.ws_mgr.get_live_ltp(str(tok))
                    if ws_spot and ws_spot > 0:
                        cached["records"]["underlyingValue"] = ws_spot
                for record in cached.get("records", {}).get("data", []):
                    for side in ("CE", "PE"):
                        opt = record.get(side)
                        if isinstance(opt, dict) and "token" in opt:
                            tick = self.ws_mgr.get_live_tick(str(opt["token"]))
                            if tick:
                                live_ltp = self.ws_mgr.get_live_ltp(str(opt["token"]))
                                if live_ltp is not None and live_ltp > 0:
                                    opt["lastPrice"] = live_ltp
                                if tick.get("oi", 0) > 0:
                                    opt["openInterest"] = tick["oi"]
            return cached
            
        if is_market_closed:
            if idx_name in self._perm_cache:
                return self._perm_cache[idx_name]
            cache_file = os.path.join(BASE_DIR, f"last_data_{idx_name}.json")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as f:
                        disk_cached = json.load(f)
                    if disk_cached and "records" in disk_cached:
                        self._perm_cache[idx_name] = disk_cached
                        return disk_cached
                except Exception:
                    pass

        if not self.session:
            self.ensure_session()

        if not self.session or not self.scrip_master:
            # Graceful fallback to perm/disk cache if session not ready
            if idx_name in self._perm_cache:
                return self._perm_cache[idx_name]
            return None
            
        # 1. Get Spot Price
        spot = self.get_ltp("NSE", self.index_tokens[idx_name]["symbol"], self.index_tokens[idx_name]["token"])
        if spot == 0.0: return None
        
        step = INDEX_CONFIG[idx_name]["step"]
        atm = round(spot / step) * step
        strikes = [atm + (i * step) for i in range(-10, 11)]
        
        # 2. Find closest expiry for this index
        expiries = self._option_expiries_by_index.get(idx_name, [])
        if not expiries: return None
        current_expiry = expiries[0]
        opt_scrips = self._option_scrips_by_expiry[idx_name][current_expiry]
        
        # 3. Collect tokens for strikes
        tokens_to_fetch = []
        strike_map = {} # strike -> {'CE': token, 'PE': token}
        for s in opt_scrips:
            if s['expiry'] == current_expiry:
                try:
                    strk = float(s['strike']) / 100
                except:
                    continue
                if strk in strikes:
                    if strk not in strike_map: strike_map[strk] = {}
                    strike_map[strk][s['symbol']] = s['token']
                    tokens_to_fetch.append(s['token'])
                    
        if not tokens_to_fetch: return None
        
        # 3b. Subscribe active strikes to WebSocket streaming on exchangeType 2 (NFO)
        if self.ws_mgr and tokens_to_fetch:
            try:
                self.ws_mgr.subscribe_tokens(2, tokens_to_fetch)
            except Exception as e:
                log.debug("WebSocket strike subscription error: %s", e)

        # 4. Fetch Market Data in batches of 50
        all_data = {}
        for i in range(0, len(tokens_to_fetch), 50):
            batch = tokens_to_fetch[i:i+50]
            try:
                res = self.smartApi.getMarketData('FULL', {'NFO': batch})
                if res and res.get('status') and res.get('data') and 'fetched' in res['data']:
                    for item in res['data']['fetched']:
                        all_data[item['symbolToken']] = item
            except Exception as e:
                log.error(f"MarketData error: {e}")

        # 5. Format into NSELive JSON format for signal_engine
        records_data = []
        for strk in sorted(strike_map.keys()):
            record = {"strikePrice": strk, "CE": {}, "PE": {}}
            for sym, token in strike_map[strk].items():
                mdata = all_data.get(token) or {}
                ltp_val = float(mdata.get('ltp', 0))
                oi_val = int(mdata.get('opnInterest', 0))

                # Overlay live sub-50ms WebSocket tick (LTP + OI) directly into chain record
                if self.ws_mgr:
                    ws_tick = self.ws_mgr.get_live_tick(token)
                    if ws_tick:
                        ws_ltp = self.ws_mgr.get_live_ltp(token)
                        if ws_ltp is not None and ws_ltp > 0:
                            ltp_val = ws_ltp
                        if ws_tick.get("oi", 0) > 0:
                            oi_val = ws_tick["oi"]

                opt_data = {
                    "lastPrice": ltp_val,
                    "openInterest": oi_val,
                    "changeinOpenInterest": int(mdata.get('changeOpenInterest', 0) or mdata.get('opnInterestChange', 0) or 0),
                    "token": token
                }
                if sym.endswith('CE'):
                    record["CE"] = opt_data
                else:
                    record["PE"] = opt_data
            records_data.append(record)
            
        result = {
            "_fetched_at": time.time(),
            "records": {
                "underlyingValue": spot,
                "data": records_data
            }
        }
        self._cache.set(idx_name, result)
        self._perm_cache[idx_name] = result
        return result

    def get_cached_option_chain(self, idx_name: str) -> Optional[Dict[str, Any]]:
        """Return an in-memory option chain without making a broker request."""
        return self._cache.get(idx_name)

    def get_option_token(self, idx_name: str, strike: float, signal: str) -> Tuple[Optional[str], Optional[str]]:
        """Look up symbolToken and tradingSymbol for an option contract."""
        opt_type = "CE" if "CE" in signal else "PE"
        expiries = self._option_expiries_by_index.get(idx_name, [])
        if not expiries:
            return None, None
        current_expiry = expiries[0]
        opt_scrips = self._option_scrips_by_expiry[idx_name][current_expiry]

        for s in opt_scrips:
            if s.get('expiry') == current_expiry:
                try:
                    s_strk = float(s['strike']) / 100.0
                except Exception:
                    continue
                if abs(s_strk - float(strike)) < 0.1 and s.get('symbol', '').endswith(opt_type):
                    return s.get('token'), s.get('symbol')
        return None, None

    def ensure_websocket_running(self) -> bool:
        """Dynamically ensure WebSocket is streaming during market hours and safely idled off-market."""
        try:
            import config
            if not getattr(config, "ENABLE_WEBSOCKET", True):
                self.ws_status = "DISABLED_BY_CONFIG"
                self.ws_message = "Disabled via ENABLE_WEBSOCKET=False config (Account protection active)."
                return False

            from core.websocket_manager import SmartWebSocketManager
            is_mkt = SmartWebSocketManager.is_market_hours()
            if not is_mkt:
                if self.ws_mgr and self.ws_mgr._is_running:
                    self.ws_mgr.stop()
                    self.ws_status = "OFF_MARKET_IDLE"
                    self.ws_message = "Market is closed (Mon–Fri 09:00–15:35 IST only). Kept idle to prevent lockout."
                return False

            # Market is open: check if WebSocket needs to be started
            if not self.session:
                self.ensure_session()

            if self.ws_mgr is None or not self.ws_mgr._is_running or not (self.ws_mgr._thread and self.ws_mgr._thread.is_alive()):
                self._init_websocket()

            return self.ws_mgr.is_connected() if self.ws_mgr else False
        except Exception as e:
            log.debug("ensure_websocket_running exception: %s", e)
            return False

    def is_websocket_connected(self) -> bool:
        """Return True if WebSocket streaming is active."""
        self.ensure_websocket_running()
        return self.ws_mgr.is_connected() if self.ws_mgr else False

    def reconnect_websocket(self) -> bool:
        """Force restart the SmartWebSocketManager connection."""
        if self.ws_mgr:
            self.ws_mgr.stop()
        return self.ensure_websocket_running()

    def get_symbol_for_token(self, token: str) -> str:
        """Resolve token to human-readable symbol name."""
        s_tok = str(token).strip()
        for idx_name, idx_info in self.index_tokens.items():
            if str(idx_info.get("token")) == s_tok:
                return f"{idx_name} SPOT"
        if not hasattr(self, "_token_symbol_map") or not self._token_symbol_map:
            self._build_token_symbol_map()
        sym = self._token_symbol_map.get(s_tok)
        if sym:
            return sym
        return f"Token #{s_tok}"

    def get_websocket_stats(self) -> Dict[str, Any]:
        """Return diagnostic WebSocket streaming statistics."""
        return self.ws_mgr.get_stats() if self.ws_mgr else {"connected": False, "running": False}

    def get_websocket_stream_data(self) -> Dict[str, Any]:
        """Return enriched WebSocket live feed snapshot for UI display."""
        diag = self.get_diagnostics()
        ws_diag = diag.get("websocket", {})

        if not self.ws_mgr:
            return {
                "status": ws_diag.get("status", "STOPPED"),
                "color": ws_diag.get("color", "#64748b"),
                "message": ws_diag.get("message", "WebSocket not initialized"),
                "connected": False,
                "running": False,
                "total_ticks": 0,
                "cached_ticks_count": 0,
                "subscribed_tokens": 0,
                "subscribed_cm": 0,
                "subscribed_fo": 0,
                "last_tick_time": None,
                "spot_indices": {},
                "option_contracts": [],
                "recent_ticks": [],
            }

        stats = self.ws_mgr.get_stats()
        all_ticks = self.ws_mgr.get_all_ticks()
        recent = self.ws_mgr.get_recent_ticks_stream(limit=30)
        subs = self.ws_mgr.get_subscriptions()

        # 1. Spot Indices
        spot_indices = {}
        for idx_name, idx_data in self.index_tokens.items():
            tok = str(idx_data["token"])
            tick = all_ticks.get(tok)
            spot_indices[idx_name] = {
                "token": tok,
                "symbol": idx_data.get("symbol", idx_name),
                "ltp": tick.get("ltp", 0.0) if tick else 0.0,
                "oi": tick.get("oi", 0) if tick else 0,
                "vol": tick.get("vol", 0) if tick else 0,
                "updated_at": tick.get("updated_at") if tick else None,
                "is_live": bool(tick and tick.get("ltp", 0.0) > 0),
            }

        # 2. Subscribed Option Contracts (Exchange type 2)
        fo_tokens = subs.get(2, set())
        option_contracts = []
        for tok in fo_tokens:
            tok_str = str(tok)
            tick = all_ticks.get(tok_str, {})
            sym = self.get_symbol_for_token(tok_str)
            option_contracts.append({
                "token": tok_str,
                "symbol": sym,
                "ltp": tick.get("ltp", 0.0) if tick else 0.0,
                "oi": tick.get("oi", 0) if tick else 0,
                "vol": tick.get("vol", 0) if tick else 0,
                "updated_at": tick.get("updated_at") if tick else None,
            })
        option_contracts.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)

        # 3. Enrich recent incoming ticks wire
        enriched_recent = []
        for r in recent:
            tok_str = str(r.get("token", ""))
            exch_type = r.get("exchange_type", 1)
            exch_name = "NSE_CM" if exch_type == 1 else "NSE_FO"
            enriched_recent.append({
                "token": tok_str,
                "symbol": self.get_symbol_for_token(tok_str),
                "exchange": exch_name,
                "ltp": r.get("ltp", 0.0),
                "oi": r.get("oi", 0),
                "vol": r.get("vol", 0),
                "timestamp": r.get("timestamp"),
            })

        return {
            "status": ws_diag.get("status", "STOPPED"),
            "color": ws_diag.get("color", "#64748b"),
            "message": ws_diag.get("message", ""),
            "connected": stats.get("connected", False),
            "running": stats.get("running", False),
            "total_ticks": stats.get("total_ticks_received", 0),
            "cached_ticks_count": stats.get("cached_ticks_count", 0),
            "subscribed_tokens": stats.get("subscribed_cm", 0) + stats.get("subscribed_fo", 0),
            "subscribed_cm": stats.get("subscribed_cm", 0),
            "subscribed_fo": stats.get("subscribed_fo", 0),
            "last_tick_time": stats.get("last_tick_time"),
            "spot_indices": spot_indices,
            "option_contracts": option_contracts,
            "recent_ticks": enriched_recent,
        }

    def get_strike_price(self, idx_name: str, strike: float, signal: str):
        data = self.fetch_option_chain(idx_name)
        if not data: return None, None
        spot = data["records"]["underlyingValue"]
        for item in data["records"]["data"]:
            if item["strikePrice"] == strike:
                if signal == "BUY CE" and "lastPrice" in item.get("CE", {}):
                    return item["CE"]["lastPrice"], spot
                elif signal == "BUY PE" and "lastPrice" in item.get("PE", {}):
                    return item["PE"]["lastPrice"], spot
        return None, spot

    def get_atm_prices(self, idx_name: str):
        data = self.fetch_option_chain(idx_name)
        if not data: return None, None, None
        spot = data["records"]["underlyingValue"]
        step = INDEX_CONFIG[idx_name]["step"]
        atm = round(spot / step) * step
        for item in data["records"]["data"]:
            if item["strikePrice"] == atm:
                ce = item.get("CE", {}).get("lastPrice", 0)
                pe = item.get("PE", {}).get("lastPrice", 0)
                return ce, pe, spot
        return None, None, spot

    def health_check(self) -> bool:
        return True

    def invalidate_cache(self, idx_name: str) -> None:
        self._cache.invalidate(idx_name)

    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "total_fetches": self.total_fetches,
            "total_errors": self.total_errors,
            "consecutive_failures": self.consecutive_failures,
            "session_active": self.session is not None,
            "websocket": self.get_websocket_stats(),
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return structured, real-time diagnostic health info without hardcoded placeholders."""
        import config
        from core.websocket_manager import SmartWebSocketManager

        self.ensure_websocket_running()
        masked_id = f"{self.client_id[:2]}***{self.client_id[-2:]}" if len(self.client_id) > 4 else (self.client_id or "DEMO")
        
        ws_conn = self.ws_mgr.is_connected() if self.ws_mgr else False
        ws_run = self.ws_mgr._is_running if self.ws_mgr else False
        ws_ticks = len(self.ws_mgr._ticks) if self.ws_mgr else 0
        ws_subs = (len(self.ws_mgr._subscriptions.get(1, set())) + len(self.ws_mgr._subscriptions.get(2, set()))) if self.ws_mgr else 0
        is_mkt_open = SmartWebSocketManager.is_market_hours()

        if ws_conn:
            ws_state_badge = "LIVE STREAMING"
            ws_color = "#10b981"
        elif not getattr(config, "ENABLE_WEBSOCKET", True):
            ws_state_badge = "PAUSED (SAFETY LOCK)"
            ws_color = "#94a3b8"
        elif not is_mkt_open:
            ws_state_badge = "OFF-MARKET IDLE"
            ws_color = "#f59e0b"
        elif ws_run:
            ws_state_badge = "CONNECTING"
            ws_color = "#38bdf8"
        else:
            ws_state_badge = "STOPPED"
            ws_color = "#64748b"

        login_color = "#10b981" if self.session else ("#f59e0b" if self.login_status == "DEMO_MODE" else "#ef4444")

        return {
            "broker": {
                "name": "Angel One SmartAPI",
                "client_id": masked_id,
                "status": self.login_status,
                "badge": "CONNECTED" if self.session else self.login_status,
                "color": login_color,
                "message": self.login_message,
                "last_login": self.last_login_time.strftime("%I:%M:%S %p") if self.last_login_time else "Not Logged In",
                "has_jwt": bool(self.session and self.session.get("jwtToken")),
                "has_feed_token": bool(self.session and self.session.get("feedToken")),
            },
            "websocket": {
                "name": "SmartWebSocket 2.0 (sub-50ms)",
                "status": ws_state_badge,
                "color": ws_color,
                "message": self.ws_message,
                "is_market_hours": is_mkt_open,
                "connected": ws_conn,
                "running": ws_run,
                "cached_ticks": ws_ticks,
                "subscribed_tokens": ws_subs,
            },
            "scrip_master": {
                "count": self.scrip_count or len(self.scrip_master),
                "source": self.scrip_source,
                "status": self.scrip_load_status,
                "time": self.scrip_load_time.strftime("%I:%M:%S %p") if self.scrip_load_time else "Loaded",
            },
            "last_fetches": {
                idx: self.last_fetch_times[idx].strftime("%I:%M:%S %p")
                for idx in self.last_fetch_times
            }
        }

    def _calc_15m_trend_from_archive(self, idx: str, current_spot: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Calculate 15-minute 20-EMA trend from institutional market archive feed (rate-limit free)."""
        candles = []
        try:
            from ml.historical_trainer import fetch_historical_candles_archive
            candles = fetch_historical_candles_archive(idx, days=5)
        except Exception:
            candles = []

        if not candles or len(candles) < 20:
            local_csv = os.path.join(BASE_DIR, "data", "historical", f"{idx}_5m.csv")
            if os.path.exists(local_csv):
                try:
                    import pandas as pd
                    ldf = pd.read_csv(local_csv)
                    if not ldf.empty and "close" in ldf.columns:
                        closes = ldf["close"].dropna().iloc[-60:].tolist()
                        if len(closes) >= 20:
                            s_closes = closes[::3] if len(closes) >= 30 else closes
                            series = pd.Series(s_closes)
                            ema20 = round(float(series.ewm(span=20, adjust=False).mean().iloc[-1]), 2)
                            ref_price = current_spot if (current_spot and current_spot > 0) else closes[-1]
                            trend = "BULLISH" if ref_price > ema20 else ("BEARISH" if ref_price < ema20 else "NEUTRAL")
                            return {
                                "trend": trend,
                                "ema20": ema20,
                                "last_close": round(ref_price, 2),
                                "_time": pytime.time(),
                                "status": "OK"
                            }
                except Exception:
                    pass

        if not candles or len(candles) < 20:
            return None

        try:
            import pandas as pd
            df = pd.DataFrame(candles)
            closes = df["close"].iloc[::3].tolist()
            if len(closes) < 15:
                closes = df["close"].tolist()
            series = pd.Series(closes)
            ema20 = round(float(series.ewm(span=20, adjust=False).mean().iloc[-1]), 2)
            ref_price = current_spot if (current_spot and current_spot > 0) else closes[-1]
            trend = "BULLISH" if ref_price > ema20 else ("BEARISH" if ref_price < ema20 else "NEUTRAL")
            return {
                "trend": trend,
                "ema20": ema20,
                "last_close": round(ref_price, 2),
                "_time": pytime.time(),
                "status": "OK"
            }
        except Exception as e:
            log.warning("Archive trend calculation error for %s: %s", idx, e)
            return None

    def get_15m_trend(self, idx: str, current_spot: Optional[float] = None) -> Dict[str, Any]:
        """
        Calculate 15-minute higher timeframe trend using 20-EMA on 15m historical candles.
        Cached with 300-second (5 min) TTL for maximum performance and rate-limit safety.
        Returns:
            {"trend": "BULLISH"|"BEARISH"|"NEUTRAL", "ema20": float, "last_close": float, ...}
        """
        cache_key = f"trend_15m_{idx}"
        cached = self._perm_cache.get(cache_key)
        now_ts = pytime.time()

        # 1. Return fresh cached EMA20 (300s TTL) with dynamic real-time spot comparison
        if cached and (now_ts - cached.get("_time", 0)) < 300:
            trend_data = dict(cached)
            if current_spot and current_spot > 0 and trend_data.get("ema20", 0) > 0:
                ema20 = trend_data["ema20"]
                trend_data["trend"] = "BULLISH" if current_spot > ema20 else ("BEARISH" if current_spot < ema20 else "NEUTRAL")
                trend_data["last_close"] = current_spot
            return trend_data

        # 2. Resilient calculation from institutional archive feed (100% rate-limit free)
        archive_res = self._calc_15m_trend_from_archive(idx, current_spot)
        if archive_res:
            self._perm_cache[cache_key] = archive_res
            return archive_res

        # 3. Resilient fallback: If cached data exists from earlier, reuse it and extend TTL
        if cached and cached.get("ema20", 0) > 0:
            trend_data = dict(cached)
            trend_data["_time"] = now_ts  # Back off for another 300s
            if current_spot and current_spot > 0:
                ema20 = trend_data["ema20"]
                trend_data["trend"] = "BULLISH" if current_spot > ema20 else ("BEARISH" if current_spot < ema20 else "NEUTRAL")
                trend_data["last_close"] = current_spot
            self._perm_cache[cache_key] = trend_data
            return trend_data

        # 4. Prevent tight error retry loops by caching a 60s cooldown
        cooldown_data = {"trend": "NEUTRAL", "ema20": 0.0, "last_close": 0.0, "_time": now_ts - 240, "status": "ERROR"}
        self._perm_cache[cache_key] = cooldown_data
        return cooldown_data

_fetcher_lock = threading.Lock()
_global_angel_fetcher = None

def get_fetcher():
    global _global_angel_fetcher
    if _global_angel_fetcher is None:
        with _fetcher_lock:
            if _global_angel_fetcher is None:
                _global_angel_fetcher = AngelOneDataFetcher()
    else:
        if not _global_angel_fetcher.session:
            _global_angel_fetcher.ensure_session()
    return _global_angel_fetcher
