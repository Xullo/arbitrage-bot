from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict
from abc import ABC, abstractmethod
import requests
import os
import base64
from logger import logger
import asyncio
import aiohttp

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
    winner: str = None # 'Yes', 'No', or None
    metadata: Dict = None # For storing CLOB IDs, etc.
    
    @property
    def spread(self) -> float:
        return 1.0 - (self.yes_price + self.no_price)

class MarketDataFeed(ABC):
    """Abstract base class for market data feeds."""
    @abstractmethod
    def fetch_events(self, status: str = 'active') -> List[MarketEvent]:
        # status: 'active' or 'closed'
        pass
    @abstractmethod
    def get_orderbook(self, identifier: str) -> Dict:
        pass

class MockMarketDataFeed(MarketDataFeed):
    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
    def fetch_events(self, status: str = 'active') -> List[MarketEvent]:
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
    
    def __init__(self, api_key: str = None, private_key: str = None):
        self.api_key = api_key
        self.private_key = private_key or os.getenv("POLYMARKET_PRIVATE_KEY")
        if not self.private_key:
             logger.warning("PolymarketFeed initialized without Private Key. Trading will fail.")

        # OPT #3: Shared aiohttp session for async requests
        self._aiohttp_session = None

    def fetch_events(self, limit: int = 100, tag_id: int = None, status: str = 'active', validate_tokens: bool = False) -> List[MarketEvent]:
        """
        Fetch events from Gamma API.

        Args:
            validate_tokens: If True, validate tokens via CLOB (slow, ~300ms per market).
                           If False, skip validation and do it later only for matched pairs (FAST).

        OPTIMIZATION: Set validate_tokens=False and validate AFTER matching pairs.
        This reduces startup time from ~60-100s to ~2-3s.
        """
        url = f"{self.BASE_URL}/events"
        params = {
            "limit": limit,
            "closed": "true" if status == 'closed' else "false",
            "order": "endDate:asc"  # Get soonest expiring (most recent 15m markets)
        }
        if tag_id:
            params["tag_id"] = tag_id

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()

            data = resp.json()

            market_events = []
            for item in data:
                markets = item.get('markets', [])
                if not markets:
                    continue

                mk = markets[0]

                # Get token IDs
                clob_ids = eval(mk.get('clobTokenIds', '[]'))
                if not clob_ids or len(clob_ids) < 1:
                    continue

                token_id = clob_ids[0]

                # OPTIMIZATION: Skip validation unless explicitly requested
                if validate_tokens:
                    if not self._validate_token(token_id):
                        logger.debug(f"Skipping market with invalid token: {item.get('title', 'N/A')[:50]}")
                        continue
                
                # Parse prices
                try:
                    outcomes = eval(mk.get('outcomePrices', '["0.5", "0.5"]'))
                    yes_price = float(outcomes[0]) if len(outcomes) > 0 else 0.5
                    no_price = float(outcomes[1]) if len(outcomes) > 1 else 0.5
                except:
                    yes_price = 0.5
                    no_price = 0.5
                
                # Resolution time - CRITICAL FIX
                # The 'endDate' field is WRONG - it's 15 minutes early!
                # Use the timestamp from the slug (e.g., btc-updown-15m-1768341600)
                # This timestamp represents the TRUE closing time
                try:
                    ticker = item.get('slug', '')
                    if 'updown-15m' in ticker or '15m' in ticker:
                        # Extract timestamp from end of slug
                        parts = ticker.split('-')
                        timestamp = int(parts[-1])
                        # TIMEZONE FIX: Use utcfromtimestamp to get UTC time (matching Kalshi)
                        # Unix timestamps are always UTC, so we need UTC conversion
                        res_date = datetime.utcfromtimestamp(timestamp)
                    else:
                        # Fallback to endDate if not a 15m market
                        res_date = datetime.fromisoformat(item.get('endDate', '').replace('Z', '+00:00'))
                        res_date = res_date.replace(tzinfo=None)
                except Exception as e:
                    logger.warning(f"Failed to parse resolution time for {item.get('slug')}: {e}")
                    res_date = datetime.now()
                
                # Outcome names
                outcome_names = mk.get('outcomes') or ['Yes', 'No']
                
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
                    winner=None,
                    metadata={
                        "clobTokenIds": clob_ids,
                        "market_id": mk.get('id'),
                        "outcomes": outcome_names
                    }
                )
                
                market_events.append(me)

            validation_msg = "tokens validated" if validate_tokens else "tokens NOT validated - will validate after matching"
            logger.info(f"Fetched {len(market_events)} Polymarket markets ({validation_msg})")
            return market_events
            
        except Exception as e:
            logger.error(f"Polymarket fetch failed: {e}")
            return []
    
    def _validate_token(self, token_id: str) -> bool:
        """Quick validation to check if token exists in CLOB"""
        try:
            book = self.get_orderbook(token_id)
            # Token valid if it has any bids or asks
            return len(book.get('bids', [])) > 0 or len(book.get('asks', [])) > 0
        except:
            return False

    def fetch_event_by_slug(self, slug: str) -> Optional[MarketEvent]:
        # Fetch specific event by slug
        url = f"{self.BASE_URL}/events"
        params = {"slug": slug}
        
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data: return None
            
            # Re-use parsing logic (simplified duplication for safety)
            item = data[0] if isinstance(data, list) else data
            markets = item.get('markets', [])
            if not markets: return None
            mk = markets[0]
            
            try:
                outcomes = eval(mk.get('outcomePrices', '["0.5", "0.5"]'))
                yes_price = float(outcomes[0]) if len(outcomes) > 0 else 0.0
                no_price = float(outcomes[1]) if len(outcomes) > 1 else 0.0
            except:
                yes_price = 0.5
                no_price = 0.5
                
            # Resolution time - CRITICAL FIX (same as fetch_events)
            try:
                ticker = item.get('slug', '') or slug
                if 'updown-15m' in ticker or '15m' in ticker:
                    # Extract timestamp from end of slug
                    parts = ticker.split('-')
                    timestamp = int(parts[-1])
                    # TIMEZONE FIX: Use utcfromtimestamp to get UTC time (matching Kalshi)
                    res_date = datetime.utcfromtimestamp(timestamp)
                else:
                    # Fallback to endDate if not a 15m market
                    res_date = datetime.fromisoformat(item.get('endDate', '').replace('Z', '+00:00'))
                    res_date = res_date.replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"Failed to parse resolution time for {slug}: {e}")
                res_date = datetime.now()
            
            clob_ids = eval(mk.get('clobTokenIds', '[]'))
            
            winner = None
            # Heuristic for winner if closed (since we fetch strictly by slug, we might fetch old ones)
            # Gamma API usually has 'winner' in market?
            # Or use prices if 1 or 0
            if yes_price >= 0.99: winner = 'Yes'
            elif no_price >= 0.99: winner = 'No'

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
                winner=winner,
                metadata={"clobTokenIds": clob_ids, "market_id": mk.get('id')}
            )
            
            # Source extraction
            desc = item.get('description', '')
            if "Resolution Source" in desc:
                try:
                    parts = desc.split("Resolution Source:")[1].strip().split()[0]
                    me.source = parts
                except:
                    pass
            
            return me
            
        except Exception as e:
            logger.error(f"Polymarket fetch by slug failed: {e}")
            return None

    def get_market(self, ticker: str) -> Optional[MarketEvent]:
        # Alias for sticky market refreshing logic
        return self.fetch_event_by_slug(ticker)

    def get_orderbook(self, token_id: str) -> Dict:
        # Uses CLOB API
        url = f"{self.CLOB_URL}/book"
        params = {"token_id": token_id}
        try:
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            return resp.json() or {}
        except Exception as e:
            logger.error(f"Poly Orderbook check failed: {e}")
            return {}

    # OPT #3: Async methods for parallel HTTP requests
    async def _get_aiohttp_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session with connection pooling"""
        if self._aiohttp_session is None or self._aiohttp_session.closed:
            timeout = aiohttp.ClientTimeout(total=5)
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            self._aiohttp_session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
        return self._aiohttp_session

    async def get_orderbook_async(self, token_id: str) -> Dict:
        """
        OPT #3: Async version of get_orderbook for parallel execution.
        Uses aiohttp with connection pooling for faster requests.
        """
        url = f"{self.CLOB_URL}/book"
        params = {"token_id": token_id}
        try:
            session = await self._get_aiohttp_session()
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                return await resp.json() or {}
        except Exception as e:
            logger.error(f"[ASYNC] Poly Orderbook check failed: {e}")
            return {}

    async def close_async_session(self):
        """Close aiohttp session (cleanup)"""
        if self._aiohttp_session and not self._aiohttp_session.closed:
            await self._aiohttp_session.close()

    def place_order(self, token_id: str, side: str, count: float, price: float) -> Dict:
        """
        Executes a Limit Order on Polymarket via CLOB using EIP-712 Signing.
        Token ID: The specific outcome token (from metadata).
        Side: 'BUY' or 'SELL'.
        Count: Size in units.
        Price: Limit price (0.01 - 0.99).
        """
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY, SELL
            from py_clob_client.constants import POLYGON

            pkey = os.getenv("POLYMARKET_PRIVATE_KEY")
            if not pkey:
                logger.error("Polymarket Private Key missing for Live Execution.")
                return {"error": "Missing Private Key"}

            # Get Safe wallet address from .env
            safe_address = os.getenv("POLYMARKET_SAFE_ADDRESS")
            if not safe_address:
                logger.error("POLYMARKET_SAFE_ADDRESS missing in .env")
                return {"error": "Missing Safe Address"}

            logger.info(f"Poly: Using Safe wallet {safe_address} as funder")

            # Setup Client (Polygon Chain ID with signature_type=2 for Gnosis Safe)
            host = "https://clob.polymarket.com"

            # Get API credentials from .env
            from py_clob_client.clob_types import ApiCreds

            api_key = os.getenv("POLYMARKET_API_KEY")
            api_secret = os.getenv("POLYMARKET_API_SECRET")
            api_pass = os.getenv("POLYMARKET_PASSPHRASE")

            if not all([api_key, api_secret, api_pass]):
                logger.error("Missing CLOB API credentials in .env")
                return {"error": "Missing API credentials"}

            # Initialize with Safe wallet configuration
            logger.info("Poly: Initializing CLOB client for Safe wallet")
            api_creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_pass
            )

            # signature_type=2 for GNOSIS_SAFE
            # funder is the Safe wallet address
            client = ClobClient(
                host=host,
                key=pkey,
                chain_id=POLYGON,
                creds=api_creds,
                signature_type=2,  # POLY_GNOSIS_SAFE
                funder=safe_address
            )
            logger.info(f"Poly: Safe wallet client initialized with signature_type=2")
            
            
            # Create Order
            # Side: BUY/SELL refers to backing the outcome
            order_side = BUY if side.upper() == 'BUY' else SELL
            
            # Create and Sign
            resp = client.create_and_post_order(
                OrderArgs(
                    price=price,
                    size=count,
                    side=order_side,
                    token_id=token_id
                )
            )
            logger.info(f"Poly Order Placed: {resp}")
            return resp
            
        except Exception as e:
            logger.error(f"Polymarket Order Failed: {e}")
            return {"error": str(e)}

    def get_order(self, order_id: str) -> Dict:
        """
        Fetches status for Poly Order.
        """
        try:
            from py_clob_client.client import ClobClient
            pkey = os.getenv("POLYMARKET_PRIVATE_KEY")
            if not pkey: return {"error": "No PK"}
            
            host = "https://clob.polymarket.com"
            chain_id = 137
            client = ClobClient(host, key=pkey, chain_id=chain_id)
            
            return client.get_order(order_id)
        except Exception as e:
            logger.error(f"Polymarket Get Order Failed: {e}")
            return {"error": str(e)}


class KalshiFeed(MarketDataFeed):
    """
    Connects to Kalshi API v2.
    Requires RSA Authentication (Key/Secret).
    """
    # Updated Endpoint per 401 Response
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    
    def __init__(self, key: str, secret: str):
        # key: Key ID (UUID)
        # secret: Path to private key file OR private key string
        self.key = key
        self.secret = secret
        self.load_private_key()

        # OPT #3: Shared aiohttp session for async requests
        self._aiohttp_session = None

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

    def place_order(self, ticker: str, side: str, count: int, price: float) -> Dict:
        """
        Executes a Limit Order on Kalshi.
        """
        path = "/portfolio/orders"
        full_path_for_sign = "/trade-api/v2" + path
        
        price_cents = int(price * 100)
        
        payload = {
            "action": "buy",
            "side": side.lower(),
            "count": int(count), # Explicitly cast to int to avoid 400 Bad Request
            "type": "limit",
            "ticker": ticker,
            "client_order_id": str(int(datetime.now().timestamp() * 1000000))
        }
        
        if side.lower() == 'yes':
            payload["yes_price"] = price_cents
        else:
            payload["no_price"] = price_cents

        headers = self._get_headers("POST", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=5)
            if resp.status_code != 201 and resp.status_code != 200:
                logger.error(f"Kalshi Order Error ({resp.status_code}): {resp.text}")
                return {"error": resp.text}
            return resp.json()
        except Exception as e:
            logger.error(f"Kalshi Order Exception: {e}")
            return {"error": str(e)}

    def get_order(self, order_id: str) -> Dict:
        """
        Fetches order status for verification.
        """
        path = f"/portfolio/orders/{order_id}"
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(f"Get Order Failed ({resp.status_code}): {resp.text}")
                return {"error": resp.text}
        except Exception as e:
            logger.error(f"Get Order Exception: {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> Dict:
        """Cancels an open order by ID."""
        path = f"/portfolio/orders/{order_id}"
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("DELETE", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.delete(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                logger.info(f"Order {order_id} cancelled successfully.")
                return resp.json()
            else:
                logger.warning(f"Cancel Order Failed ({resp.status_code}): {resp.text}")
                return {"error": resp.text}
        except Exception as e:
            logger.error(f"Cancel Order Exception: {e}")
            return {"error": str(e)}

    def get_balance(self) -> Optional[float]:
        """Fetches the available balance in USD cents and converts to dollars."""
        path = "/portfolio/balance"
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # 'balance' is in cents
                balance_cents = data.get('balance', 0)
                return float(balance_cents) / 100.0
            else:
                logger.error(f"Get Balance Failed ({resp.status_code}): {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Get Balance Exception: {e}")
            return None

    # OPT #3: Async methods for parallel HTTP requests
    async def _get_aiohttp_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session with connection pooling"""
        if self._aiohttp_session is None or self._aiohttp_session.closed:
            timeout = aiohttp.ClientTimeout(total=5)
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            self._aiohttp_session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
        return self._aiohttp_session

    async def get_orderbook_async(self, ticker: str) -> Dict:
        """
        OPT #3: Async version of get_orderbook for parallel execution.
        Uses aiohttp with connection pooling and Kalshi authentication.
        """
        path = f"/markets/{ticker}/orderbook"
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        try:
            session = await self._get_aiohttp_session()
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get('orderbook', {})
        except Exception as e:
            logger.error(f"[ASYNC] Kalshi Orderbook check failed: {e}")
            return {}

    async def get_balance_async(self) -> Optional[float]:
        """
        OPT #3: Async version of get_balance for parallel execution.
        Fetches the available balance in USD cents and converts to dollars.
        """
        path = "/portfolio/balance"
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        try:
            session = await self._get_aiohttp_session()
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    balance_cents = data.get('balance', 0)
                    return float(balance_cents) / 100.0
                else:
                    text = await resp.text()
                    logger.error(f"[ASYNC] Get Balance Failed ({resp.status}): {text}")
                    return None
        except Exception as e:
            logger.error(f"[ASYNC] Get Balance Exception: {e}")
            return None

    async def close_async_session(self):
        """Close aiohttp session (cleanup)"""
        if self._aiohttp_session and not self._aiohttp_session.closed:
            await self._aiohttp_session.close()

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

    def fetch_events(self, limit: int = 1000, series_ticker: str = None, status: str = 'active') -> List[MarketEvent]:
        path = "/markets"
        # Correct path for signing: /trade-api/v2/markets
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)

        # Kalshi API filter: 'open', 'closed', 'settled'
        # BUT: Individual markets have 'status': 'active' which doesn't match 'open'
        # Solution: Don't use status filter at all, filter manually by close_time
        params = {"limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker

        # We'll manually filter for tradeable markets (close_time in future) below

        try:
            resp = requests.get(f"{self.BASE_URL}{path}", headers=headers, params=params)
            if resp.status_code != 200:
                logger.error(f"Kalshi Fetch Error ({resp.status_code}): {resp.text}")
                return []
                
            data = resp.json()
            markets = data.get('markets', [])
            logger.info(f"Debug: Kalshi Raw Markets Fetched (all): {len(markets)}")
            
            market_events = []
            for m in markets:
                # Check for Crypto
                # logger.debug(f"Checking title: {m.get('title')}")
                # Keyword filter removed to allow broader market discovery
                pass
                
                yes_bid = m.get('yes_bid', 0)
                yes_ask = m.get('yes_ask', 0)
                
                # TAKER PRICING: We want to BUY at the ASK.
                # If Ask is missing (0), use 0.99 (worst case) to avoid execution errors, 
                # though it will be filtered by arb profitability anyway.
                yes_price = yes_ask if yes_ask > 0 else 0.99
                
                # Normalize cents to dollars
                if yes_price > 1.0: yes_price /= 100.0
                if yes_bid > 1.0: valid_yes_bid = yes_bid / 100.0 
                else: valid_yes_bid = yes_bid
                
                # No Price (Cost to Buy No) = 1.0 - Yes Bid (The price I can sell Yes at)
                # Why? Because buying No is equivalent to Shorting Yes (Selling to the Bid).
                # Cost_No = 1.00 - Price_Sold_Yes
                no_price = 1.0 - valid_yes_bid
                
                # Use close_time (trading deadline) for matching, not expiration_time (settlement)
                # This fixes the mismatch where settlement is days later.
                try:
                    time_str = m.get('close_time') or m.get('expiration_time')
                    res_date = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    res_date = res_date.replace(tzinfo=None)
                except:
                    res_date = datetime.now()

                # CRITICAL FIX: Skip markets where close_time has already passed
                # Kalshi may return markets even after trading has closed (before settlement)
                # TIMEZONE FIX: Use utcnow() since res_date is in UTC
                if status == 'active':
                    time_to_close = (res_date - datetime.utcnow()).total_seconds()
                    if time_to_close < 0:
                        logger.info(f"[FILTER] Skipping CLOSED market: {m.get('ticker')} (closed {-time_to_close:.0f}s ago, close_time={res_date})")
                        continue

                    # Skip markets closing more than 24 hours in the future (only get today's markets)
                    if time_to_close > 86400:  # 24 hours
                        logger.info(f"[FILTER] Skipping FUTURE market: {m.get('ticker')} (closes in {time_to_close/3600:.1f}h)")
                        continue

                    # DEBUG: Log markets that PASS the filter
                    logger.info(f"[FILTER] ACCEPTED market: {m.get('ticker')} (closes in {time_to_close/60:.1f} min at {res_date})")

                # Winner extraction for settled markets
                winner = None
                if status == 'closed' or m.get('result'):
                     result = m.get('result') # 'yes', 'no', 'void'
                     if result == 'yes': winner = 'Yes'
                     elif result == 'no': winner = 'No'

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
                    source=m.get('settlement_source', 'Kalshi'),
                    winner=winner
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
    def get_market(self, ticker: str) -> Optional[MarketEvent]:
        """Fetch a single market by ticker."""
        path = f"/markets/{ticker}"
        full_path_for_sign = "/trade-api/v2" + path
        headers = self._get_headers("GET", full_path_for_sign)
        url = f"{self.BASE_URL}{path}"
        
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            m = data.get('market', {})
            if not m: return None
            
            # Construct MarketEvent (Reusing logic)
            yes_bid = m.get('yes_bid', 0)
            yes_ask = m.get('yes_ask', 0)
            
            # TAKER PRICING
            yes_price = yes_ask if yes_ask > 0 else 0.99
            if yes_price > 1.0: yes_price /= 100.0
            
            if yes_bid > 1.0: valid_yes_bid = yes_bid / 100.0
            else: valid_yes_bid = yes_bid
            no_price = 1.0 - valid_yes_bid

            try:
                time_str = m.get('close_time') or m.get('expiration_time')
                res_date = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                res_date = datetime.now()

            return MarketEvent(
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
        except Exception as e:
            logger.error(f"Kalshi single market fetch failed: {e}")
            return None
