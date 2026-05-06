from curl_cffi import requests
import time

def test_fetch():
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    for browser in ["chrome110", "chrome120", "safari15_3", "edge101"]:
        try:
            print(f"\\nTesting {browser}...")
            session = requests.Session(impersonate=browser)
            session.get("https://www.nseindia.com", headers=headers, timeout=10)
            time.sleep(1)
            
            headers_api = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "User-Agent": headers["User-Agent"],
                "Accept-Language": headers["Accept-Language"]
            }
            r2 = session.get(url, headers=headers_api, timeout=10)
            print(f"API status ({browser}):", r2.status_code)
            if r2.status_code == 200:
                data = r2.json()
                if "records" in data:
                    print(f"SUCCESS with {browser}!")
                    return
                else:
                    print(f"Empty JSON with {browser}:", data)
        except Exception as e:
            print(f"Exception with {browser}:", e)

if __name__ == "__main__":
    test_fetch()
