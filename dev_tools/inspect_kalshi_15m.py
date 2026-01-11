from market_data import KalshiFeed
from config_manager import config
import requests
import json
from datetime import datetime

def inspect_kalshi_15m():
    config.validate_keys()
    kf = KalshiFeed(config.KALSHI_API_KEY, config.KALSHI_API_SECRET)
    
    print("--- Inspecting Kalshi KXBTC15M Series ---")
    
    # Authenticate manually to use raw requests if needed, 
    # but kf.fetch_events uses the wrapper.
    # Let's use the wrapper first but modify it to allow custom params? 
    # No, let's use raw requests for max control.
    
    path = "/trade-api/v2/markets"
    headers = kf._get_headers("GET", path)
    
    # Fetch WITHOUT status="open" first to see everything
    params = {
        "limit": 50,
        "series_ticker": "KXBTC15M"
    }
    
    url = f"{kf.BASE_URL}/markets"
    print(f"Requesting: {url} with params {params}")
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        markets = data.get('markets', [])
        print(f"Fetched {len(markets)} markets.")
        
        for m in markets:
            print(f"\nTitle: {m.get('title')}")
            print(f"Ticker: {m.get('ticker')}")
            print(f"Status: {m.get('status')}")
            print(f"Open: {m.get('open_time')}")
            print(f"Close: {m.get('close_time')}")
            print(f"Expire: {m.get('expiration_time')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_kalshi_15m()
