import requests
from datetime import datetime

def find_expiring_soon():
    base_url = "https://gamma-api.polymarket.com/events"
    
    print("--- Fetching Events Sorting by endDate:asc (Expiring Soon) ---")
    
    params = {
        "limit": 50,
        "closed": "false",
        "order": "endDate:asc"
    }
    
    try:
        resp = requests.get(base_url, params=params)
        data = resp.json()
        print(f"Fetched {len(data)} events.")
        for e in data:
            title = e.get('title', '')
            end_date = e.get('endDate')
            # Filter for likely candidates
            if "Bitcoin" in title or "BTC" in title or "ETH" in title or "Price" in title:
                print(f" [EXP: {end_date}] {title} (ID: {e.get('id')})")
            else:
                # Print a few others just to see
                pass
                # print(f" [EXP: {end_date}] {title}")
                
    except Exception as e:
        print(e)

if __name__ == "__main__":
    find_expiring_soon()
