from market_data import KalshiFeed
from config_manager import config
import requests

def find_series():
    config.validate_keys()
    kf = KalshiFeed(config.KALSHI_API_KEY, config.KALSHI_API_SECRET)
    
    # Authenticate to get headers
    path = "/series"
    # full_path_for_sign = "/trade-api/v2" + path
    # headers = kf._get_headers("GET", full_path_for_sign) # Series endpoint might be public or authed
    
    # Actually, try public first, or use the authenticated method
    # market_data.py doesn't expose _get_headers easily for external scripts without copy-paste
    # Let's just use the verified method from KalshiFeed but adapt it via inheritance or just copy the logic
    
    # Quicker: modify KalshiFeed to have a public method or just hack it here
    # Accessing private method for debug is fine in python
    full_path = "/trade-api/v2/series"
    headers = kf._get_headers("GET", full_path)
    
    print("Fetching Series list...")
    url = f"{kf.BASE_URL}/series"
    resp = requests.get(url, headers=headers)
    
    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return

    data = resp.json()
    series_list = data.get('series', [])
    print(f"Total Series Found: {len(series_list)}")
    
    print("\n--- Hourly Series Search ---")
    for s in series_list:
        title = s.get('title', '')
        ticker = s.get('ticker', '')
        if 'Hour' in title or 'hour' in title:
            print(f"Found: {title} (Ticker: {ticker})")
            
    print("\n--- Price Series Search ---")
    for s in series_list:
        title = s.get('title', '')
        ticker = s.get('ticker', '')
        if ('Price' in title or 'price' in title) and ('Bitcoin' in title or 'BTC' in title):
            print(f"Found: {title} (Ticker: {ticker})")
    print("\n--- Top 20 Series (Debug) ---")
    for s in series_list[:20]:
        print(f"{s.get('title')} ({s.get('ticker')})")

if __name__ == "__main__":
    find_series()
