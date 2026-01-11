from market_data import KalshiFeed
from config_manager import config
import requests
import json

def verify_series():
    config.validate_keys()
    kf = KalshiFeed(config.KALSHI_API_KEY, config.KALSHI_API_SECRET)
    
    # We need to target the /markets endpoint with specific series_ticker
    base_url = kf.BASE_URL
    path = "/trade-api/v2/markets"
    
    tickers_to_check = ["KXBTCD", "KXBTC15M", "KXBTC"]
    
    for ticker in tickers_to_check:
        print(f"\n--- Checking Series: {ticker} ---")
        # Generate headers for this specific request if needed, or just use generic restricted headers
        # Signing usually requires method + path (excluding base)
        # However, query params are usually NOT part of the sig path in some implementations, 
        # but in Kalshi v2 RSA, the path usually implies the resource. 
        # Let's rely on kf._get_headers returning valid headers for the base path or specific path.
        # It seems kf._get_headers takes (method, path).
        
        # NOTE: If we use requests.get, we need to manually sign the full path including params? 
        # Usually params are not part of the path for signing in many APIs, but let's see.
        # Safest bet: Use the path without params for signing, as is common.
        
        headers = kf._get_headers("GET", "/trade-api/v2/markets")
        
        params = {
            "limit": 100,
            "status": "open",
            "series_ticker": ticker
        }
        
        url = f"{base_url}/markets"
        try:
            resp = requests.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            markets = data.get("markets", [])
            print(f"Found {len(markets)} markets.")
            for m in markets:
                print(f" - [{m.get('close_time')}] {m.get('title')} (Yes Bid: {m.get('yes_bid')})")
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            if 'resp' in locals():
                print(resp.text)

if __name__ == "__main__":
    verify_series()
