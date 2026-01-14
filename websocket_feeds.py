"""
WebSocket Real-Time Orderbook Feeds for Kalshi and Polymarket

This module provides async WebSocket clients for real-time orderbook updates,
enabling instant arbitrage detection instead of REST polling.
"""

import asyncio
import json
import logging
import os
import time
import hashlib
import base64
from datetime import datetime
from typing import Dict, Callable, Optional, Any
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Shared orderbook state
class OrderbookCache:
    """
    Thread-safe cache for orderbook data with aggressive TTL validation.

    OPTIMIZATION: Prevents stale data trades by enforcing short TTLs:
    - MAX_AGE_MS = 500ms: Data older than this is considered STALE
    - Protects against executing orders on outdated prices
    """

    MAX_AGE_MS = 500  # 500ms TTL - aggressive to prevent stale orders

    def __init__(self):
        self.kalshi_orderbooks: Dict[str, Dict] = {}  # {ticker: {yes: [...], no: [...]}}
        self.poly_orderbooks: Dict[str, Dict] = {}    # {token_id: {asks: [...], bids: [...]}}
        self.last_update: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def update_kalshi(self, ticker: str, side: str, orders: list):
        """Update Kalshi orderbook for a specific ticker and side."""
        async with self._lock:
            if ticker not in self.kalshi_orderbooks:
                self.kalshi_orderbooks[ticker] = {'yes': [], 'no': []}
            self.kalshi_orderbooks[ticker][side] = orders
            self.last_update[f"kalshi:{ticker}"] = time.time()

    async def update_poly(self, token_id: str, asks: list, bids: list):
        """Update Polymarket orderbook for a specific token."""
        async with self._lock:
            self.poly_orderbooks[token_id] = {'asks': asks, 'bids': bids}
            self.last_update[f"poly:{token_id}"] = time.time()

    def get_kalshi(self, ticker: str) -> Optional[Dict]:
        """
        Get cached Kalshi orderbook if fresh (< 500ms old).
        Returns None if data is stale to prevent false trades.
        """
        cache_key = f"kalshi:{ticker}"
        last_update_time = self.last_update.get(cache_key, 0)
        age_ms = (time.time() - last_update_time) * 1000

        if age_ms > self.MAX_AGE_MS:
            logger.debug(f"[CACHE] Kalshi {ticker} data STALE ({age_ms:.0f}ms old)")
            return None

        return self.kalshi_orderbooks.get(ticker)

    def get_poly(self, token_id: str) -> Optional[Dict]:
        """
        Get cached Polymarket orderbook if fresh (< 500ms old).
        Returns None if data is stale to prevent false trades.
        """
        cache_key = f"poly:{token_id}"
        last_update_time = self.last_update.get(cache_key, 0)
        age_ms = (time.time() - last_update_time) * 1000

        if age_ms > self.MAX_AGE_MS:
            logger.debug(f"[CACHE] Poly {token_id[:16]}... data STALE ({age_ms:.0f}ms old)")
            return None

        return self.poly_orderbooks.get(token_id)

    def get_age_ms(self, source: str, identifier: str) -> float:
        """Get age of cached data in milliseconds"""
        cache_key = f"{source}:{identifier}"
        last_update_time = self.last_update.get(cache_key, 0)
        return (time.time() - last_update_time) * 1000 if last_update_time > 0 else float('inf')


class KalshiWebSocket:
    """WebSocket client for Kalshi real-time orderbook updates."""

    WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    
    def __init__(self, cache: OrderbookCache, on_update: Optional[Callable] = None):
        self.cache = cache
        self.on_update = on_update  # Callback when orderbook updates
        self.ws = None
        self.subscribed_tickers: set = set()
        self.running = False
        self._auth_token = None
        
    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for WebSocket connection."""
        import cryptography.hazmat.primitives.serialization as serialization
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend

        api_key = os.getenv("KALSHI_API_KEY")
        key_secret = os.getenv("KALSHI_API_SECRET")

        # Load private key (from string or file)
        if os.path.exists(key_secret):
            with open(key_secret, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
        else:
            # Handle string key
            key_str = key_secret
            if "\\n" in key_str:
                key_str = key_str.replace("\\n", "\n")

            # Try base64 decode if needed
            if not key_str.strip().startswith("-----"):
                try:
                    decoded = base64.b64decode(key_str).decode('utf-8')
                    if "-----BEGIN" in decoded:
                        key_str = decoded
                except:
                    pass

            private_key = serialization.load_pem_private_key(
                key_str.encode() if isinstance(key_str, str) else key_str,
                password=None,
                backend=default_backend()
            )

        # Sign timestamp using PSS padding (Kalshi v2 requirement)
        timestamp = str(int(time.time() * 1000))
        # WebSocket path format: timestamp + method + path (no space between)
        msg = f"{timestamp}GET/trade-api/ws/v2"

        signature = private_key.sign(
            msg.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )

        logger.debug(f"Kalshi WS Auth - Timestamp: {timestamp}, Message: {msg[:50]}...")

        return {
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode('utf-8'),
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }
        
    async def connect(self):
        """Establish WebSocket connection to Kalshi."""
        import websockets
        
        try:
            headers = await self._get_auth_headers()
            # websockets v16+ uses 'additional_headers' instead of 'extra_headers'
            self.ws = await websockets.connect(self.WS_URL, additional_headers=headers)
            self.running = True
            logger.info("Kalshi WebSocket connected.")
            return True
        except Exception as e:
            logger.error(f"Kalshi WebSocket connection failed: {e}")
            return False
    
    async def subscribe(self, tickers: list):
        """Subscribe to orderbook updates for given tickers."""
        if not self.ws:
            return
            
        for ticker in tickers:
            if ticker not in self.subscribed_tickers:
                msg = {
                    "id": int(time.time() * 1000),
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": [ticker]
                    }
                }
                await self.ws.send(json.dumps(msg))
                self.subscribed_tickers.add(ticker)
                logger.info(f"Kalshi: Subscribed to {ticker}")
    
    async def listen(self):
        """Listen for orderbook updates."""
        if not self.ws:
            return
            
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Kalshi: Invalid JSON: {message[:100]}")
        except Exception as e:
            logger.error(f"Kalshi WebSocket error: {e}")
            self.running = False
    
    async def _handle_message(self, data: dict):
        """Process incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "orderbook_snapshot":
            # Initial snapshot of the orderbook
            msg = data.get("msg", {})
            ticker = msg.get("market_ticker")

            if ticker:
                # Parse yes and no orderbooks
                yes_orders = msg.get("yes", [])
                no_orders = msg.get("no", [])

                # Update cache with full orderbook
                await self.cache.update_kalshi(ticker, "yes", yes_orders)
                await self.cache.update_kalshi(ticker, "no", no_orders)

                logger.info(f"Kalshi snapshot: {ticker} - Yes orders: {len(yes_orders)}, No orders: {len(no_orders)}")

                if self.on_update:
                    await self.on_update("kalshi", ticker)

        elif msg_type == "orderbook_delta":
            # Incremental update to orderbook
            msg = data.get("msg", {})
            ticker = msg.get("market_ticker")
            side = msg.get("side", "").lower()
            price = msg.get("price")
            delta = msg.get("delta", 0)

            if ticker and side and price is not None:
                # Update cache (simplified - full impl would merge deltas)
                await self.cache.update_kalshi(ticker, side, [[price, delta]])
                logger.debug(f"Kalshi delta: {ticker} {side} @ {price} Δ{delta}")

                if self.on_update:
                    await self.on_update("kalshi", ticker)

        elif msg_type == "subscribed":
            logger.info(f"Kalshi: Subscription confirmed")

        elif msg_type == "error":
            logger.error(f"Kalshi WS error: {data}")
    
    async def close(self):
        """Close WebSocket connection."""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("Kalshi WebSocket closed.")


class PolymarketWebSocket:
    """WebSocket client for Polymarket real-time orderbook updates."""
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    CLOB_API = "https://clob.polymarket.com"
    
    def __init__(self, cache: OrderbookCache, on_update: Optional[Callable] = None):
        self.cache = cache
        self.on_update = on_update
        self.ws = None
        self.subscribed_tokens: set = set()
        self.validated_tokens: set = set()  # Cache of validated tokens
        self.invalid_tokens: set = set()    # Cache of invalid tokens
        self.running = False
        
    async def connect(self):
        """Establish WebSocket connection to Polymarket."""
        import websockets
        
        try:
            self.ws = await websockets.connect(self.WS_URL)
            self.running = True
            logger.info("Polymarket WebSocket connected.")
            return True
        except Exception as e:
            logger.error(f"Polymarket WebSocket connection failed: {e}")
            return False
    
    def _validate_token_sync(self, token_id: str) -> bool:
        """Synchronously validate if token exists in CLOB (for quick check)."""
        # Check cache first
        if token_id in self.validated_tokens:
            return True
        if token_id in self.invalid_tokens:
            return False
        
        # Validate by checking if orderbook exists
        try:
            import requests
            resp = requests.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
                timeout=2
            )
            
            if resp.status_code == 200:
                book = resp.json()
                has_liquidity = len(book.get('bids', [])) > 0 or len(book.get('asks', [])) > 0
                
                if has_liquidity:
                    self.validated_tokens.add(token_id)
                    return True
                else:
                    logger.warning(f"Token {token_id[:20]}... exists but no liquidity")
                    self.invalid_tokens.add(token_id)
                    return False
            else:
                logger.warning(f"Token {token_id[:20]}... invalid (HTTP {resp.status_code})")
                self.invalid_tokens.add(token_id)
                return False
                
        except Exception as e:
            logger.debug(f"Token validation error for {token_id[:20]}: {e}")
            return False  # Err on side of caution
    
    async def subscribe(self, token_ids: list):
        """Subscribe to orderbook updates for given tokens (validates first)."""
        if not self.ws:
            return

        # Polymarket requires subscribing to all tokens in a single message
        if token_ids:
            # Filter out already subscribed tokens AND validate new ones
            new_tokens = []
            for tid in token_ids:
                if tid not in self.subscribed_tokens:
                    # Validate before subscribing
                    if self._validate_token_sync(tid):
                        new_tokens.append(tid)
                    else:
                        logger.info(f"Skipping invalid token: {tid[:20]}...")

            if new_tokens:
                # Correct Polymarket subscription format
                msg = {
                    "assets_ids": new_tokens,
                    "type": "market"
                }
                await self.ws.send(json.dumps(msg))

                for token_id in new_tokens:
                    self.subscribed_tokens.add(token_id)
                    logger.info(f"Polymarket: Subscribed to VALID token {token_id[:20]}...")
    
    async def listen(self):
        """Listen for orderbook updates."""
        if not self.ws:
            return

        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    logger.debug(f"Polymarket received: {str(data)[:200]}")
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Polymarket: Invalid JSON: {message[:100]}")
                except Exception as e:
                    logger.error(f"Polymarket message handling error: {e}")
                    logger.debug(f"Problematic data: {str(data)[:500]}")
        except Exception as e:
            logger.error(f"Polymarket WebSocket error: {e}")
            self.running = False
    
    async def _handle_message(self, data):
        """Process incoming WebSocket message."""
        # Polymarket can send either a list of messages or a single message
        messages = data if isinstance(data, list) else [data]

        for msg in messages:
            if not isinstance(msg, dict):
                continue

            # Check if this is an orderbook snapshot (has 'bids' and 'asks')
            if 'bids' in msg and 'asks' in msg:
                asset_id = msg.get("asset_id")

                if asset_id:
                    # Double-check token is valid before processing
                    if asset_id not in self.validated_tokens:
                        logger.debug(f"Received data for unvalidated token, skipping: {asset_id[:20]}...")
                        continue
                    
                    asks = msg.get("asks", [])
                    bids = msg.get("bids", [])

                    # Convert to standard format
                    formatted_asks = []
                    for a in asks:
                        if isinstance(a, dict):
                            formatted_asks.append({"price": a.get("price"), "size": a.get("size")})

                    formatted_bids = []
                    for b in bids:
                        if isinstance(b, dict):
                            formatted_bids.append({"price": b.get("price"), "size": b.get("size")})

                    await self.cache.update_poly(asset_id, formatted_asks, formatted_bids)
                    logger.info(f"Polymarket orderbook snapshot: {asset_id[:20]}... asks:{len(formatted_asks)} bids:{len(formatted_bids)}")

                    if self.on_update:
                        await self.on_update("poly", asset_id)

            # Handle price change messages
            elif 'price_changes' in msg:
                price_changes = msg.get("price_changes", [])
                for change in price_changes:
                    asset_id = change.get("asset_id")
                    if asset_id:
                        logger.debug(f"Polymarket price change: {asset_id[:20]}... price={change.get('price')}")
                        # Could trigger callback here if needed
    
    async def close(self):
        """Close WebSocket connection."""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("Polymarket WebSocket closed.")


class WebSocketManager:
    """Manages WebSocket connections and triggers arb detection on updates."""
    
    def __init__(self, arb_callback: Optional[Callable] = None):
        self.cache = OrderbookCache()
        self.arb_callback = arb_callback
        
        self.kalshi_ws = KalshiWebSocket(self.cache, self._on_orderbook_update)
        self.poly_ws = PolymarketWebSocket(self.cache, self._on_orderbook_update)
        
        self.ticker_to_token: Dict[str, str] = {}  # Map Kalshi ticker to Poly token
        
    async def _on_orderbook_update(self, source: str, identifier: str):
        """Called when any orderbook updates. Triggers arb check."""
        if self.arb_callback:
            await self.arb_callback(source, identifier, self.cache)
    
    async def start(self, kalshi_tickers: list, poly_tokens: list, ticker_token_map: dict):
        """Start WebSocket connections and subscriptions."""
        self.ticker_to_token = ticker_token_map
        
        # Connect both
        k_connected = await self.kalshi_ws.connect()
        p_connected = await self.poly_ws.connect()
        
        if not k_connected or not p_connected:
            logger.error("Failed to connect WebSockets. Falling back to REST.")
            return False
        
        # Subscribe
        await self.kalshi_ws.subscribe(kalshi_tickers)
        await self.poly_ws.subscribe(poly_tokens)
        
        # Start listeners in background
        asyncio.create_task(self.kalshi_ws.listen())
        asyncio.create_task(self.poly_ws.listen())
        
        logger.info("WebSocket feeds started.")
        return True
    
    async def stop(self):
        """Stop all WebSocket connections."""
        await self.kalshi_ws.close()
        await self.poly_ws.close()
        logger.info("WebSocket feeds stopped.")


# Standalone test
async def test_websocket():
    """Test WebSocket connections."""
    cache = OrderbookCache()
    
    # Test Kalshi
    ks = KalshiWebSocket(cache)
    if await ks.connect():
        await ks.subscribe(["KXBTC15M-26JAN111700-00"])
        
        # Listen for 5 seconds
        await asyncio.sleep(5)
        await ks.close()
    
    print("Kalshi cache:", cache.kalshi_orderbooks)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(test_websocket())
