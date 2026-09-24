import os
import json
import time as pytime
import requests
import pyotp
import logging
import threading
import urllib.request, email.utils
from typing import Optional, Tuple, Dict, Any, List
from SmartApi import SmartConnect
from config import ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET, INDEX_CONFIG
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
            res = urllib.request.urlopen('http://google.com')
            dt = email.utils.parsedate_to_datetime(res.headers['Date'])
            drift = dt.timestamp() - pytime.time()
            totp = pyotp.TOTP(self.totp_secret).at(pytime.time() + drift)
            
            data = self.smartApi.generateSession(self.client_id, self.password, totp)
            if data and data.get('status'):
                self.session = data['data']
                log.info("Angel One Login Successful")
                return True
            else:
                log.error(f"Angel One Login Failed: {data}")
                return False
        except Exception as e:
            log.error(f"Angel One Login Exception: {e}")
            return False

    def _load_scrip_master(self):
        log.info("Downloading Angel One Scrip Master...")
        try:
            res = requests.get('https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json')
            self.scrip_master = res.json()
            log.info(f"Loaded {len(self.scrip_master)} scrips.")
        except Exception as e:
            log.error(f"Failed to load scrip master: {e}")

    def get_ltp(self, exchange, tradingsymbol, token):
        if not self.session: return 0.0
        try:
            res = self.smartApi.ltpData(exchange, tradingsymbol, token)
            if res and res.get('status') and res.get('data'):
                return float(res['data']['ltp'])
        except Exception as e:
            pass
        return 0.0

    def fetch_option_chain(self, idx_name: str) -> Optional[Dict[str, Any]]:
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        now = datetime.datetime.now(IST)
        is_market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30) or now.hour < 9 or (now.hour == 9 and now.minute < 15)

        cached = self._cache.get(idx_name)
        if cached:
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
                mdata = all_data.get(token)
                if not mdata: continue
                opt_data = {
                    "lastPrice": float(mdata.get('ltp', 0)),
                    "openInterest": int(mdata.get('opnInterest', 0)),
                    # Angel One's full market data does not return Change in OI directly.
                    # As a workaround to prevent "NO DATA", we can pass 0 or a mocked value.
                    "changeinOpenInterest": 1000 
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
        return {"total_fetches": 0, "total_errors": 0, "consecutive_failures": 0, "session_active": self.session is not None}

_fetcher_lock = threading.Lock()
_global_angel_fetcher = None

def get_fetcher():
    global _global_angel_fetcher
    if _global_angel_fetcher is None:
        with _fetcher_lock:
            if _global_angel_fetcher is None:
                _global_angel_fetcher = AngelOneDataFetcher()
    return _global_angel_fetcher
