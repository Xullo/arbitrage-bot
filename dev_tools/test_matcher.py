from event_matcher import EventMatcher
from market_data import MarketEvent
from datetime import datetime, timedelta

def test_matcher():
    matcher = EventMatcher()
    
    # Current time approx
    now = datetime(2026, 1, 10, 23, 30, 0) # UTC
    
    k_event = MarketEvent(
        exchange="KALSHI",
        event_id="k1",
        ticker="KTEMP",
        title="BTC price up in next 15 mins?",
        description="desc",
        resolution_time=now,
        yes_price=0.5,
        no_price=0.5,
        volume=100.0,
        source="kalshi"
    )
    
    p_event = MarketEvent(
        exchange="POLYMARKET",
        event_id="p1",
        ticker="PTEMP",
        title="Bitcoin Up or Down - January 10, 6:30PM-6:45PM ET",
        description="desc",
        resolution_time=now, # Assuming timestamps match now
        yes_price=0.5,
        no_price=0.5,
        volume=100.0,
        source="polymarket"
    )
    
    print(f"Testing Match...")
    print(f"Kalshi: {k_event.title}")
    print(f"Poly:   {p_event.title}")
    
    is_match = matcher.are_equivalent(k_event, p_event)
    print(f"Match Result: {is_match}")
    
    # We can inspect internal logic if we import rapidfuzz in this script or just rely on output
    from rapidfuzz import fuzz
    score = fuzz.token_sort_ratio(k_event.title.lower(), p_event.title.lower())
    print(f"Token Sort Ratio: {score}")

if __name__ == "__main__":
    test_matcher()
