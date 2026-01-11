from market_data import KalshiFeed, PolymarketFeed
from config_manager import config
import time
import requests

def debug_print_markets():
    config.validate_keys()
    
    print("Initializing Feeds...")
    try:
        kf = KalshiFeed(config.KALSHI_API_KEY, config.KALSHI_API_SECRET)
        pf = PolymarketFeed()
    except Exception as e:
        print(f"Auth Error: {e}")
        return

    print("\n--- Fetching Kalshi (Limit 1000 + KXBTCD + KXBTC15M) ---")
    k_events = kf.fetch_events(limit=1000)
    k_btc_daily = kf.fetch_events(limit=100, series_ticker="KXBTCD")
    k_btc_15m = kf.fetch_events(limit=100, series_ticker="KXBTC15M")
    
    # Merge
    all_kalshi = {e.event_id: e for e in k_events + k_btc_daily + k_btc_15m}.values()
    k_events = list(all_kalshi)
    
    print(f"Fetched {len(k_events)} Kalshi events total.")
    
    print("\n--- Fetching Polymarket (Limit 500 + Tag 102127) ---")
    p_events = pf.fetch_events(limit=500)
    p_15m = pf.fetch_events(limit=100, tag_id=102127)
    
    all_poly = {e.event_id: e for e in p_events + p_15m}.values()
    p_events = list(all_poly)
    
    # Filter for BTC
    k_btc = [e for e in k_events if "Bitcoin" in e.title or "BTC" in e.title]
    p_btc = [e for e in p_events if "Bitcoin" in e.title or "BTC" in e.title or "Up or Down" in e.title]
    
    print(f"\n=== Kalshi BTC Markets ({len(k_btc)}) ===")
    for e in k_btc:
        # e is MarketEvent. We need to fetch raw if we want to see raw fields, 
        # but MarketEvent only has resolution_time.
        # Wait, I mapped resolution_time to expiration_time in market_data.py.
        # I need to modify this script to print the raw json or simpler: 
        # Just use the mapped value I have, but I suspect it's wrong.
        pass

    # Better: Inspect RAW Kalshi data again for one event.
    print("\n--- Inspecting Raw Kalshi Data (First 3) ---")
    raw_k = kf.fetch_events(limit=5) 
    # fetch_events in MarketData returns market_events objects.
    # I need to access the raw dictionary.
    # I will hit the API directly in this script to see raw.
    
    headers = kf._get_headers("GET", "/trade-api/v2/markets")
    params = {"limit": 10, "status": "open", "series_ticker": "KXBTCD"}
    resp = requests.get(f"{kf.BASE_URL}/markets", headers=headers, params=params)
    data = resp.json().get('markets', [])
    for m in data[:3]:
        print(f"Title: {m.get('title')}")
        print(f"Close: {m.get('close_time')}")
        print(f"Expire: {m.get('expiration_time')}")
        print(f"Ticker: {m.get('ticker')}")
        
    print(f"\n=== Polymarket BTC Markets ({len(p_btc)}) ===")
    for e in p_btc:
        print(f"[{e.resolution_time}] {e.title}")

    if not k_btc and not p_btc:
        print("\nNo Bitcoin markets found in the top list. Try increasing limit or checking API filters.")

if __name__ == "__main__":
    debug_print_markets()
