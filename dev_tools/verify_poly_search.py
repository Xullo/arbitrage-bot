import requests

def verify_poly_search():
    base_url = "https://gamma-api.polymarket.com/events"
    
    # Try 'q', 'query', 'slug'
    print("--- Testing 'q' param with BTC ---")
    params = {"limit": 50, "closed": "false", "q": "BTC"}
    try:
        resp = requests.get(base_url, params=params)
        data = resp.json()
        print(f"Found {len(data)} events with q='Bitcoin'")
        for e in data[:5]:
            print(f" - {e.get('title')}")
    except Exception as e:
        print(e)

    # Try filtering by tag? (Need to know tag ID for Bitcoin)
    # But text search is best if supported.
    
    # If q doesn't work, maybe we need to filter locally from a larger fetch?
    # But pagination is better.

if __name__ == "__main__":
    verify_poly_search()
