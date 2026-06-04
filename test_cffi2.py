from curl_cffi import requests

def test():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br'
    }
    
    s = requests.Session(impersonate="chrome120")
    
    print("Getting OC page...")
    r1 = s.get('https://www.nseindia.com/option-chain', headers=headers, timeout=10)
    print("Main status:", r1.status_code)
    print("Cookies:", s.cookies.get_dict())
    
    print("Getting API...")
    headers['Referer'] = 'https://www.nseindia.com/option-chain'
    headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
    r2 = s.get('https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY', headers=headers, timeout=10)
    print("API status:", r2.status_code)
    try:
        data = r2.json()
        print("Keys:", data.keys())
        if 'records' in data:
            print("SUCCESS! Spot:", data['records']['underlyingValue'])
        else:
            print("Empty JSON:", data)
    except Exception as e:
        print("Failed JSON:", r2.text[:100])

test()
