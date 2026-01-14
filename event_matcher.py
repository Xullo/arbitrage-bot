from datetime import timedelta
from difflib import SequenceMatcher
from typing import Optional
from market_data import MarketEvent
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
        # Kalshi using close_time vs Poly endDate. Strict 60s tolerance.
        if abs((ev_a.resolution_time - ev_b.resolution_time).total_seconds()) > 60:
            logger.debug(f"Time mismatch: {abs(ev_a.resolution_time - ev_b.resolution_time)}. Events: {ev_a.ticker} vs {ev_b.ticker}")
            return False

        t1 = ev_a.title.lower()
        t2 = ev_b.title.lower()
        
        # 2. Heuristic for Crypto 15m Markets
        # Kalshi: "BTC price up in next 15 mins?"
        # Poly: "Bitcoin Up or Down - ..."
        
        assets_a = self._extract_assets(t1)
        assets_b = self._extract_assets(t2)
        shared_asset = assets_a.intersection(assets_b)
        
        # Check if 15m related keywords exist
        # 2a. Strike Price Validation (CRITICAL FIX)
        # Kalshi: "BTC > 99,750" (Fixed Strike)
        # Poly: "Bitcoin Up or Down" (Delta Strike = Spot)
        
        # Check explicit "Up/Down" type match first
        is_type_updown_a = "up" in t1 and "down" in t1
        is_type_updown_b = "up" in t2 and "down" in t2
        
        if is_type_updown_a and is_type_updown_b:
             # Both are explicitly "Up or Down" markets.
             # Trust the timestamp match. 
             # (Polymarket often omits the strike in the title for these).
             logger.info(f"MATCH FOUND (Up/Down Type Match): {ev_a.ticker} <-> {ev_b.ticker}")
             return True

        s1 = self._extract_strike(t1)
        s2 = self._extract_strike(t2)
        
        # If both have strikes, check equality
        if s1 and s2:
            if abs(s1 - s2) > 10: # $10 tolerance
                logger.debug(f"Strike mismatch: {s1} vs {s2}")
                return False
        
        # If one has strike and other says "Up or Down" (no specific strike mentioned), REJECT.
        # But wait, if we reached here, they AREN'T both Up/Down. 
        # So one is Fixed Strike, one is... something else (maybe Delta).
        if (s1 and not s2) or (s2 and not s1):
            logger.debug(f"Market Type Mismatch (Fixed Strike vs Delta): {t1} ({s1}) vs {t2} ({s2})")
            return False
        
        # 3. Asset Mismatch Check (Generic) - MOVED BEFORE RETURN
        if assets_a and assets_b and not shared_asset:
             logger.debug(f"Asset mismatch: {assets_a} vs {assets_b}")
             return False
            
        # If timestamps match (checked above) and both share an asset (BTC/ETH/SOL) + 15m keywords
        asset_str = next(iter(shared_asset)).upper() if shared_asset else "UNK"
        logger.info(f"MATCH FOUND ({asset_str} 15m heuristic): {ev_a.ticker} <-> {ev_b.ticker}")
        return True

    def _extract_strike(self, title: str) -> Optional[float]:
        try:
            import re
            # Look for patterns like $99,750, 99.75k? No, usually just numbers in Kalshi.
            # Pattern: "above <number>" or "$<number>"
            # Regex for dollar amount with commas
            matches = re.findall(r'(?:above|below|>|<)?\s?\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)', title)
            if matches:
                 # Filter out small numbers implies 15 mins? 
                 # We want large numbers (price). E.g. > 1000.
                 for m in matches:
                     val = float(m.replace(',', ''))
                     if val > 500: # BTC/ETH prices usually > 500
                         return val
        except:
            pass
        return None

        # 4. Source Check (Critical for value parity)
        if ev_a.source and ev_b.source:
             if not self._sources_compatible(ev_a.source, ev_b.source):
                 logger.debug(f"Source mismatch: {ev_a.source} vs {ev_b.source}")
                 return False

        # 5. Semantic Similarity (Simple fuzzy match for now, can be improved with NLP)
        similarity = SequenceMatcher(None, t1, t2).ratio()
        if similarity < 0.6: # Threshold needs tuning
            logger.debug(f"Low similarity ({similarity:.2f}): '{ev_a.title}' vs '{ev_b.title}'")
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
        if "solana" in text or "sol" in text:
            assets.add("sol")
        return assets
        
    def _sources_compatible(self, source_a: str, source_b: str) -> bool:
        """
        Returns True if sources are likely the same.
        """
        s_a = source_a.lower()
        s_b = source_b.lower()
        
        # 1. Direct substrings (e.g. "coingecko" in "https://coingecko.com...")
        if s_a in s_b or s_b in s_a:
            return True
            
        # 2. Common Aliases
        aliases = [
            {"binance", "binance usa", "binance.com"},
            {"coinbase", "coinbase pro"},
            {"coingecko", "gecko"},
            {"nasdaq", "nasdaq.com"},
        ]
        
        for alias_set in aliases:
            if any(a in s_a for a in alias_set) and any(b in s_b for b in alias_set):
                return True
                
        # If both are generic default names, assume compatible for now (risky but needed if extracting fails)
        if ("kalshi" in s_a or "polymarket" in s_a) and ("kalshi" in s_b or "polymarket" in s_b):
             return True

        return False
