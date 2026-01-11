from datetime import timedelta
from difflib import SequenceMatcher
from market_data import MarketEvent
from logger import logger

class EventMatcher:
    """
    Core logic for determining if a Kalshi event and a Polymarket event
    refer to the EXACT same real-world outcome.
    """
    
    def __init__(self, time_tolerance_minutes: int = 5):
        self.time_tolerance = timedelta(minutes=time_tolerance_minutes)

    def are_equivalent(self, ev_a: MarketEvent, ev_b: MarketEvent) -> bool:
        """
        Determines equivalence based on:
        1. Time (Resolution Time)
        2. Crypto Asset (BTC/ETH) check in title
        3. Semantic Similarity of title
        """
        if ev_a.exchange == ev_b.exchange:
            return False # Cannot arbitrage same exchange

        # 1. Check Resolution Time
        # Kalshi using close_time vs Poly endDate. Allow 5 mins difference.
        if abs((ev_a.resolution_time - ev_b.resolution_time).total_seconds()) > 300:
            logger.debug(f"Time mismatch: {abs(ev_a.resolution_time - ev_b.resolution_time)}. Events: {ev_a.ticker} vs {ev_b.ticker}")
            return False

        # 2. Heuristic for BTC 15m Markets (Kalshi Title: "BTC price up in next 15 mins?", Poly: "Bitcoin Up or Down...")
        t1 = ev_a.title.lower()
        t2 = ev_b.title.lower()
        
        # Check if both are Bitcoin related
        is_btc = ("btc" in t1 or "bitcoin" in t1) and ("btc" in t2 or "bitcoin" in t2)
        
        # Check if 15m related keywords exist
        is_15m = "15" in t1 or "15" in t2 or "up or down" in t1 or "up or down" in t2
        
        if is_btc and is_15m:
            # If timestamps match (checked above) and both are BTC 15m style, we FORCE match
            # because fuzzy match fails on "next 15 mins" vs "Jan 10 6:45PM"
            logger.info(f"MATCH FOUND (15m BTC heuristic): {ev_a.ticker} <-> {ev_b.ticker}")
            return True

        # 3. Asset Check (Basic filter for BTC/ETH mentioned in prompt)
        # Assuming titles like "Bitcoin > $100k"
        assets_a = self._extract_assets(ev_a.title)
        assets_b = self._extract_assets(ev_b.title)
        if not assets_a.intersection(assets_b):
             logger.debug(f"Asset mismatch: {assets_a} vs {assets_b}")
             return False

        # 3. Semantic Similarity (Simple fuzzy match for now, can be improved with NLP)
        similarity = SequenceMatcher(None, ev_a.title.lower(), ev_b.title.lower()).ratio()
        if similarity < 0.6: # Threshold needs tuning
            logger.debug(f"Low similarity ({similarity:.2f}): '{ev_a.title}' vs '{ev_b.title}'")
            return False
            
        # 4. Source Check (harder to normalize, but critical)
        # If sources are explicitly different (e.g. Binance vs Coinbase), FAIL.
        # This is a placeholder for more complex logic.
        if ev_a.source and ev_b.source:
             if not self._sources_compatible(ev_a.source, ev_b.source):
                 return False

        logger.info(f"MATCH FOUND: {ev_a.ticker} <-> {ev_b.ticker} (Sim: {similarity:.2f})")
        return True

    def _extract_assets(self, text: str) -> set:
        text = text.lower()
        assets = set()
        if "bitcoin" in text or "btc" in text:
            assets.add("btc")
        if "ethereum" in text or "eth" in text:
            assets.add("eth")
        return assets
        
    def _sources_compatible(self, source_a: str, source_b: str) -> bool:
        # TODO: Implement a mapping of compatible sources
        # e.g., "Coingecko" == "Coingecko"
        s_a = source_a.lower()
        s_b = source_b.lower()
        return s_a in s_b or s_b in s_a
