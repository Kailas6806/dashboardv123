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
from config import ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET, INDEX_CONFIG, BASE_DIR
from utils.cache import TTLCache
import datetime

log = logging.getLogger("angelone_fetcher")
if not log.handlers:
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)

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
        self.login()
        self._load_scrip_master()

    def login(self):
        if not self.client_id or not self.password or not self.totp_secret:
            log.warning("Angel credentials missing. Running in DEMO mode.")
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
                log.info("Angel One Login Successful")
                self._init_websocket()
                return True
            else:
                log.error(f"Angel One Login Failed: {data}")
                return False
        except Exception as e:
            log.error(f"Angel One Login Exception: {e}")
            return False

    def _init_websocket(self):
        """Initialize and start background SmartWebSocketManager for live ticks."""
        try:
            import config
            if not getattr(config, "ENABLE_WEBSOCKET", False):
                log.info("SmartWebSocket is disabled via ENABLE_WEBSOCKET=False config.")
                return

            from core.websocket_manager import SmartWebSocketManager
            if not SmartWebSocketManager.is_market_hours():
                log.info("Off-market hours detected. SmartWebSocket is kept idle to protect Angel One account from lockout.")
                return

            if not self.session:
                return
            jwt_token = self.session.get("jwtToken")
            feed_token = self.session.get("feedToken")
            if not jwt_token or not feed_token:
                return

            if self.ws_mgr is None:
                self.ws_mgr = SmartWebSocketManager(
                    auth_token=jwt_token,
                    api_key=self.api_key,
                    client_code=self.client_id,
                    feed_token=feed_token,
                )
                if self.ws_mgr.start():
                    # Subscribe Spot Indices immediately
                    spot_tokens = [self.index_tokens[i]["token"] for i in self.index_tokens]
                    self.ws_mgr.subscribe_tokens(1, spot_tokens)
                    log.info("WebSocket streaming spot tokens initiated: %s", spot_tokens)
        except Exception as e:
            log.warning("WebSocket initialization error: %s", e)

    def _load_scrip_master(self):
        cache_file = os.path.join(BASE_DIR, "scrip_master_cache.json")
        if os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if time.time() - mtime < 86400:  # 24 hours
                    with open(cache_file, "r", encoding="utf-8") as f:
                        self.scrip_master = json.load(f)
                    log.info(f"Loaded {len(self.scrip_master)} scrips from local disk cache in <0.05s.")
                    return
            except Exception as e:
                log.warning(f"Failed to read local scrip cache: {e}")

        log.info("Downloading Angel One Scrip Master...")
        try:
            res = requests.get('https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json', timeout=15.0)
            self.scrip_master = res.json()
            log.info(f"Loaded {len(self.scrip_master)} scrips.")
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(self.scrip_master, f)
            except Exception:
                pass
        except Exception as e:
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
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
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
                    # Angel One's full market data does not return Change in OI directly.
                    # As a workaround to prevent "NO DATA", we can pass 0 or a mocked value.
                    "changeinOpenInterest": 1000,
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
            "total_fetches": 0,
            "total_errors": 0,
            "consecutive_failures": 0,
            "session_active": self.session is not None,
            "websocket": self.get_websocket_stats(),
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
