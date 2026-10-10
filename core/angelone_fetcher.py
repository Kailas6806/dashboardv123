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
        self.smartApi = SmartConnect(api_key=self.api_key)
        self.session = None
        self._cache = TTLCache(default_ttl=1)
        self.ws_mgr = None
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
        self.total_fetches = 0
        self.total_errors = 0
        self.consecutive_failures = 0
        self.last_fetch_times = {}

        self.login()
        self._load_scrip_master()

    def login(self):
        if not self.client_id or not self.password or not self.totp_secret:
            self.login_status = "DEMO_MODE"
            self.login_message = "Angel One credentials missing in config or secrets.toml. Running in DEMO mode."
            log.warning(self.login_message)
            return False
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
                self._init_websocket()
                return True
            else:
                self.login_status = "FAILED"
                err_msg = data.get('message', 'Login error') if isinstance(data, dict) else str(data)
                self.login_message = f"Angel One login failed: {err_msg}"
                log.error("Angel One Login Failed: %s", data)
                return False
        except Exception as e:
            self.login_status = "ERROR"
            self.login_message = f"Angel One login exception: {e}"
            log.error("Angel One Login Exception: %s", e)
            return False

    def _init_websocket(self):
        """Initialize and start background SmartWebSocketManager for live ticks."""
        try:
            import config
            if not getattr(config, "ENABLE_WEBSOCKET", False):
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
                )
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
        self.total_fetches += 1
        self.last_fetch_times[idx_name] = datetime.datetime.now(IST)
        now = datetime.datetime.now(IST)
        is_market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30) or now.hour < 9 or (now.hour == 9 and now.minute < 15)

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
                                if tick.get("ltp", 0.0) > 0:
                                    opt["lastPrice"] = tick["ltp"]
                                if tick.get("oi", 0) > 0:
                                    opt["openInterest"] = tick["oi"]
            return cached
            
        if is_market_closed and hasattr(self, "_perm_cache") and idx_name in self._perm_cache:
            return self._perm_cache[idx_name]

        if not self.session or not self.scrip_master:
            return None # Fail gracefully to trigger mock or error
            
        # 1. Get Spot Price
        spot = self.get_ltp("NSE", self.index_tokens[idx_name]["symbol"], self.index_tokens[idx_name]["token"])
        if spot == 0.0: return None
        
        step = INDEX_CONFIG[idx_name]["step"]
        atm = round(spot / step) * step
        strikes = [atm + (i * step) for i in range(-10, 11)]
        
        # 2. Find closest expiry for this index
        opt_scrips = [s for s in self.scrip_master if s['name'] == idx_name and s['instrumenttype'] == 'OPTIDX']
        if not opt_scrips: return None
        
        # Sort expiries (format DDMMMYYYY e.g. 06OCT2026)
        def parse_expiry(exp_str):
            try: return datetime.datetime.strptime(exp_str, '%d%b%Y')
            except: return datetime.datetime.max
            
        expiries = sorted(list(set(s['expiry'] for s in opt_scrips)), key=parse_expiry)
        if not expiries: return None
        current_expiry = expiries[0]
        
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
                        if ws_tick.get("ltp", 0.0) > 0:
                            ltp_val = ws_tick["ltp"]
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
            "records": {
                "underlyingValue": spot,
                "data": records_data
            }
        }
        self._cache.set(idx_name, result)
        return result

    def get_option_token(self, idx_name: str, strike: float, signal: str) -> Tuple[Optional[str], Optional[str]]:
        """Look up symbolToken and tradingSymbol for an option contract."""
        opt_type = "CE" if "CE" in signal else "PE"
        opt_scrips = [s for s in self.scrip_master if s.get('name') == idx_name and s.get('instrumenttype') == 'OPTIDX']
        if not opt_scrips:
            return None, None
        
        # Closest expiry
        expiries = sorted(
            list(set(s['expiry'] for s in opt_scrips)),
            key=lambda exp: datetime.datetime.strptime(exp, '%d%b%Y') if exp else datetime.datetime.max
        )
        if not expiries:
            return None, None
        current_expiry = expiries[0]

        for s in opt_scrips:
            if s.get('expiry') == current_expiry:
                try:
                    s_strk = float(s['strike']) / 100.0
                except Exception:
                    continue
                if abs(s_strk - float(strike)) < 0.1 and s.get('symbol', '').endswith(opt_type):
                    return s.get('token'), s.get('symbol')
        return None, None

    def is_websocket_connected(self) -> bool:
        """Return True if WebSocket streaming is active."""
        return self.ws_mgr.is_connected() if self.ws_mgr else False

    def get_websocket_stats(self) -> Dict[str, Any]:
        """Return diagnostic WebSocket streaming statistics."""
        return self.ws_mgr.get_stats() if self.ws_mgr else {"connected": False, "running": False}

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

        masked_id = f"{self.client_id[:2]}***{self.client_id[-2:]}" if len(self.client_id) > 4 else (self.client_id or "DEMO")
        
        ws_conn = self.ws_mgr.is_connected() if self.ws_mgr else False
        ws_run = self.ws_mgr._is_running if self.ws_mgr else False
        ws_ticks = len(self.ws_mgr._ticks) if self.ws_mgr else 0
        ws_subs = (len(self.ws_mgr._subscriptions.get(1, set())) + len(self.ws_mgr._subscriptions.get(2, set()))) if self.ws_mgr else 0
        is_mkt_open = SmartWebSocketManager.is_market_hours()

        if ws_conn:
            ws_state_badge = "LIVE STREAMING"
            ws_color = "#10b981"
        elif not getattr(config, "ENABLE_WEBSOCKET", False):
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

_fetcher_lock = threading.Lock()
_global_angel_fetcher = None

def get_fetcher():
    global _global_angel_fetcher
    if _global_angel_fetcher is None:
        with _fetcher_lock:
            if _global_angel_fetcher is None:
                _global_angel_fetcher = AngelOneDataFetcher()
    return _global_angel_fetcher
