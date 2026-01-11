from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict
from abc import ABC, abstractmethod
import requests
import os
import base64
from logger import logger

@dataclass
class MarketEvent:
    exchange: str  # 'KALSHI' or 'POLYMARKET'
    event_id: str
    ticker: str
    title: str
    description: str
    resolution_time: datetime
    yes_price: float
    no_price: float
    volume: float
    source: str  # e.g. "CoinGecko", "CoinDesk" (important for matching)
    metadata: Dict = None # For storing CLOB IDs, etc.
    
    @property
    def spread(self) -> float:
        return 1.0 - (self.yes_price + self.no_price)

class MarketDataFeed(ABC):
    """Abstract base class for market data feeds."""
    @abstractmethod
    def fetch_events(self) -> List[MarketEvent]:
        pass
    @abstractmethod
    def get_orderbook(self, identifier: str) -> Dict:
        pass

class MockMarketDataFeed(MarketDataFeed):
    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
    def fetch_events(self) -> List[MarketEvent]:
        return []
    def get_orderbook(self, identifier: str) -> Dict:
        return {"bids": [], "asks": []}

class PolymarketFeed(MarketDataFeed):
    """
    Connects to Polymarket Gamma API.
    Docs: https://docs.polymarket.com/
    """
    BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"

    def fetch_events(self, limit: int = 1000, tag_id: int = None) -> List[MarketEvent]:
        # Fetch generic events, trying to filter for Crypto if possible or just get top volume
        url = f"{self.BASE_URL}/events"
        params = {
            "limit": limit,
            "closed": "false",
            "order": "volume:desc" # Get high volume events
        }
        if tag_id:
            params["tag_id"] = tag_id
            params["order"] = "endDate:asc" # For specific tags (likely expiring soon/active), default sort by urgency
        
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            
            data = resp.json()
            
            market_events = []
            for item in data:
                # Polymarket events have "markets" inside them. 
                # usually one market per event for simple Yes/No, but can be multiple.
                markets = item.get('markets', [])
                if not markets: continue
                
                # We focus on the primary binary market for now
                mk = markets[0] 
                
                # Parse prices (mocking middle of NBBO or using reference price if available)
                # Gamma API usually gives 'outcomePrices' or requires CLOB for deep books.
                # Assuming 'outcomePrices' is present in simplified view
                # Actually, Gamma API returns simplified 'markets' list.
                
                # Parse Outcome Prices from list string e.g. ["0.55", "0.45"]
                try:
                    outcomes = eval(mk.get('outcomePrices', '["0.5", "0.5"]'))
                    yes_price = float(outcomes[0]) if len(outcomes) > 0 else 0.0
                    no_price = float(outcomes[1]) if len(outcomes) > 1 else 0.0
                except:
                    yes_price = 0.5
                    no_price = 0.5
                
                try:
                   res_date = datetime.fromisoformat(item.get('endDate', '').replace('Z', '+00:00'))
                   # Naive approach to timezones for now, ensure UTC
                   res_date = res_date.replace(tzinfo=None) # Simplify to naive for matching logic 
                except:
                   res_date = datetime.now()

                # Extract CLOB Token ID for YES outcome (usually index 0 or 1, check outcomes)
                # mk['clobTokenIds'] is typically ["token_no", "token_yes"] ??? 
                # Actually typically ["token_id_outcome_0", "token_id_outcome_1"]
                # For binary: 0 is usually 'Yes' or 'No'? Poly usually No/Yes or Yes/No?
                # Usually outcomes are ["Yes", "No"] or similar. 
                # Let's assume index 0 corresponds to outcome[0].
                clob_ids = eval(mk.get('clobTokenIds', '[]'))
                yes_token_id = clob_ids[0] if len(clob_ids) > 0 else None
                # Actually, standard is 0=Long/Yes? It varies. But we store ALL.
                
                me = MarketEvent(
                    exchange="POLYMARKET",
                    event_id=item.get('id'),
                    ticker=item.get('slug', 'N/A'),
                    title=item.get('title'),
                    description=item.get('description', ''),
                    resolution_time=res_date,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=float(item.get('volume', 0)),
                    source="Polymarket",
                    metadata={"clobTokenIds": clob_ids, "market_id": mk.get('id')}
                )
                market_events.append(me)
                
            return market_events
            
        except Exception as e:
            logger.error(f"Polymarket fetch failed: {e}")
            return []

    def get_orderbook(self, token_id: str) -> Dict:
        # Uses CLOB API
        url = f"{self.CLOB_URL}/book"
        params = {"token_id": token_id}
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            return resp.json() or {}
        except Exception as e:
            logger.error(f"Poly Orderbook check failed: {e}")
            return {}


class KalshiFeed(MarketDataFeed):
    """
    Connects to Kalshi API v2.
    Requires RSA Authentication (Key/Secret).
    """
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    
    def __init__(self, key: str, secret: str):
        # key: Key ID (UUID)
        # secret: Path to private key file OR private key string
        self.key = key
        self.secret = secret
        self.load_private_key()

    def load_private_key(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.backends import default_backend
            
            # Check if secret is a path or the key itself
            if os.path.exists(self.secret):
                with open(self.secret, "rb") as key_file:
                    self.private_key = serialization.load_pem_private_key(
                        key_file.read(),
                        password=None,
                        backend=default_backend()
                    )
            else:
                # Assume it's the key string (PEM format)
                key_str = self.secret
                logger.info(f"Debug: Loaded Secret length: {len(key_str)}")
                logger.info(f"Debug: Secret preview: {key_str[:30]}...")

                # Check if it looks like base64 (common fix for .env multiline issues)
                # If it doesn't start with '-----', try decoding
                if not key_str.strip().startswith("-----"):
                    try:
                        decoded = base64.b64decode(key_str).decode('utf-8')
                        if "-----BEGIN" in decoded:
                            key_str = decoded
                    except:
                        pass # Not base64, assume raw string

                # Handle .env/string formatting where newlines are escaped
                if "\\n" in key_str:
                    key_str = key_str.replace("\\n", "\n")
                
                self.private_key = serialization.load_pem_private_key(
                    key_str.encode() if isinstance(key_str, str) else key_str,
                    password=None,
                    backend=default_backend()
                )
        except Exception as e:
            logger.error(f"Failed to load Kalshi Private Key: {e}")
            self.private_key = None

    def _get_headers(self, method: str, path: str) -> Dict:
        import time
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        if not self.private_key: return {}
        
        timestamp = str(int(time.time() * 1000))
        msg = timestamp + method + path # Simple concatenation for v2
        
        signature = self.private_key.sign(
            msg.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        sig_b64 = base64.b64encode(signature).decode('utf-8')
        
        return {
            "KALSHI-ACCESS-KEY": self.key,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

    def fetch_events(self, limit: int = 50, series_ticker: str = None) -> List[MarketEvent]:
        path = "/markets"
        # Correct path for signing: /trade-api/v2/markets
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        
        params = {"limit": limit, "status": "open"}
        if series_ticker:
            params["series_ticker"] = series_ticker

        try:
            resp = requests.get(f"{self.BASE_URL}{path}", headers=headers, params=params)
            if resp.status_code != 200:
                logger.error(f"Kalshi Fetch Error ({resp.status_code}): {resp.text}")
                return []
                
            data = resp.json()
            markets = data.get('markets', [])
            logger.info(f"Debug: Kalshi Raw Markets Fetched: {len(markets)}")
            
            market_events = []
            for m in markets:
                # Check for Crypto
                # logger.debug(f"Checking title: {m.get('title')}")
                # Keyword filter removed to allow broader market discovery
                pass
                
                yes_bid = m.get('yes_bid', 0)
                yes_ask = m.get('yes_ask', 0)
                yes_price = (yes_bid + yes_ask) / 2 if (yes_bid and yes_ask) else 0.5
                
                # Normalize cents to dollars (Kalshi API often returns 1-99 for cents)
                if yes_price > 1.0:
                    yes_price = yes_price / 100.0
                
                # Use close_time (trading deadline) for matching, not expiration_time (settlement)
                # This fixes the mismatch where settlement is days later.
                try:
                    time_str = m.get('close_time') or m.get('expiration_time')
                    res_date = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    res_date = res_date.replace(tzinfo=None)
                except:
                    res_date = datetime.now()

                me = MarketEvent(
                    exchange="KALSHI",
                    event_id=m.get('ticker'),
                    ticker=m.get('ticker'),
                    title=m.get('title'),
                    description=m.get('subtitle', ''),
                    resolution_time=res_date,
                    yes_price=yes_price,
                    no_price=1.0 - yes_price,
                    volume=float(m.get('volume', 0)),
                    source=m.get('settlement_source', 'Kalshi')
                )
                market_events.append(me)
            return market_events
        except Exception as e:
            logger.error(f"Kalshi fetch failed: {e}")
            return []
            
    def get_orderbook(self, ticker: str) -> Dict:
        path = f"/markets/{ticker}/orderbook"
        # Correct path for signing: /trade-api/v2/markets/{ticker}/orderbook
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json().get('orderbook') or {}
        except Exception as e:
            logger.error(f"Kalshi Orderbook check failed: {e}")
            return {}
