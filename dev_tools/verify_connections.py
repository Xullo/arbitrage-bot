from config_manager import config
from market_data import KalshiFeed, PolymarketFeed
from logger import logger
import sys

def test_connections():
    print("\n=== TESTING API CONNECTIONS ===\n")

    # 1. Test Polymarket (Public)
    print("-> Testing Polymarket (Gamma API)...")
    try:
        poly = PolymarketFeed()
        events = poly.fetch_events(limit=5)
        print(f"✅ Polymarket Success! Fetched {len(events)} events.")
        for e in events[:2]:
            print(f"   - {e.title} ({e.ticker}) Price: {e.yes_price:.2f}")
    except Exception as e:
        print(f"❌ Polymarket Failed: {e}")

    print("\n--------------------------------\n")

    # 2. Test Kalshi (Auth Required)
    print("-> Testing Kalshi API v2 (RSA Auth)...")
    
    k_key = config.KALSHI_API_KEY
    k_secret = config.KALSHI_API_SECRET
    
    if not k_key or not k_secret:
        print(f"❌ Kalshi Skipped: Missing API keys in .env")
        print(f"   Key present: {bool(k_key)}")
        print(f"   Secret present: {bool(k_secret)}")
    else:
        try:
            kalshi = KalshiFeed(key=k_key, secret=k_secret)
            # KalshiFeed instantiates private key in init, but fetch_events tests the actual auth
            events = kalshi.fetch_events(limit=5)
            
            if events:
                print(f"✅ Kalshi Success! Fetched {len(events)} events.")
                for e in events[:2]:
                    print(f"   - {e.title} ({e.ticker}) Price: {e.yes_price:.2f}")
            else:
                print("⚠️ Kalshi connected but returned 0 events (or error logged). Check logs.")
                
        except Exception as e:
             print(f"❌ Kalshi Failed: {e}")

if __name__ == "__main__":
    test_connections()
