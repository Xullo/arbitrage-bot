import requests
import json

def print_event_details(e):
    print(json.dumps(e, indent=2))

if __name__ == "__main__":
    base_url = "https://gamma-api.polymarket.com/events"
    
    print(f"\n--- 1. Inspecting Known 15m Event ---")
    slug = "btc-updown-15m-1768087800"
    try:
        resp = requests.get(base_url, params={"slug": slug})
        data = resp.json()
        if isinstance(data, list) and data:
             print_event_details(data[0])
        elif isinstance(data, dict):
             print_event_details(data)
    except Exception as e:
        print(f"Error fetching slug: {e}")

    print(f"\n--- 2. Testing Tag 102127 (Up or Down) ---")
    params = {
        "limit": 50,
        "closed": "false",
        "tag_id": 102127, # Up or Down (Hidden Key!)
        "order": "endDate:asc"
    }
    try:
        resp = requests.get(base_url, params=params)
        data = resp.json()
        print(f"Fetched {len(data)} 'Up or Down' events.")
        for e in data:
            print(f" MATCH: {e.get('title')} (ID: {e.get('id')})")
    except Exception as e:
        print(e)
