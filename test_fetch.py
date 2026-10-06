import requests
import time
import random

def test_fetch():
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        print("Fetching main page to get cookies...")
        r1 = session.get("https://www.nseindia.com", timeout=10)
        print("Main page status:", r1.status_code)
        
        time.sleep(random.uniform(1.0, 2.0))
        
        print("Fetching option chain API...")
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = "https://www.nseindia.com/option-chain"
        
        r2 = session.get(url, headers=headers, timeout=10)
        print("API status:", r2.status_code)
        if r2.status_code == 200:
            data = r2.json()
            if "records" in data:
                print("SUCCESS! Data keys:", data.keys())
            else:
                print("Valid JSON, but no 'records' key:", data)
        else:
            print("Failed. Response:", r2.text[:200])
    except Exception as e:
        print("Exception:", e)

if __name__ == "__main__":
    test_fetch()
