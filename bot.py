
import asyncio
import logging
import dataclasses
import os
import time
from datetime import datetime
from typing import Optional, List, Dict

# Local Modules
from config_manager import config
from market_data import KalshiFeed, PolymarketFeed, MarketEvent
from event_matcher import EventMatcher
from arbitrage_engine import ArbitrageDetector
from risk_manager import RiskManager
from execution import ExecutionCoordinator
from database_manager import DatabaseManager
from websocket_feeds import WebSocketManager, OrderbookCache

logger = logging.getLogger("ArbitrageBot")

class ArbitrageBot:
    def __init__(self):
        self.running = False
        self.config = config
        self.execution_history = {} # Key: "type:kid:pid" -> timestamp
        self.locked_pairs = []
        # WebSocket mode disabled - REST polling is more reliable for orderbook data
        # WebSockets don't push orderbook updates frequently enough
        self.use_websockets = False  # Flag to enable/disable WebSocket mode

        # Trade cooldown to prevent over-trading
        self.market_cooldown_until = 0  # Timestamp when cooldown ends
        self.TRADE_COOLDOWN = 60  # 1 minute = 60 seconds (suitable for 15min markets)

    def initialize(self):
        logger.info("Initializing Arbitrage Bot...")

        # Validate Config
        self.config.validate_keys()

        # Initialize Sub-Components
        self.db_manager = DatabaseManager()
        # User has ~$4 on Kalshi. Assuming matching $4 on Poly => $8 Total.
        self.risk = RiskManager(current_bankroll=8.0)

        # Inject Fees from Config
        self.detector = ArbitrageDetector(
            fee_kalshi=self.config.fee_config.kalshi_taker_rate,
            fee_poly=self.config.fee_config.poly_flat_fee,
            db_manager=self.db_manager
        )

        # Initialize Feeds first
        try:
            self.kalshi_feed = KalshiFeed(self.config.KALSHI_API_KEY, self.config.KALSHI_API_SECRET)
            self.poly_feed = PolymarketFeed(
                api_key=os.getenv("POLYMARKET_API_KEY"),
                private_key=os.getenv("POLYMARKET_PRIVATE_KEY")
            )

            # Connect Risk Manager to Live Feed
            self.risk.set_feed(self.kalshi_feed)

            logger.info("Feeds initialized successfully.")
        except Exception as e:
            logger.critical(f"Failed to initialize feeds: {e}")
            raise e

        self.matcher = EventMatcher()

        # Initialize WebSocket Manager (creates orderbook_cache)
        self.ws_manager = WebSocketManager(arb_callback=self.on_orderbook_update)

        # Inject Feeds + OrderbookCache into Executor for Live Trading
        # OPTIMIZATION: Cache enables fast lookups and avoids unnecessary HTTP fetches
        self.executor = ExecutionCoordinator(
            self.risk,
            self.kalshi_feed,
            self.poly_feed,
            orderbook_cache=self.ws_manager.cache
        )

    async def fetch_kalshi_data(self):
        """Fetch Kalshi markets (async wrapper for sync API)"""
        loop = asyncio.get_event_loop()
        k_btc_15 = await loop.run_in_executor(None, self.kalshi_feed.fetch_events, 100, "KXBTC15M")
        k_eth_15 = await loop.run_in_executor(None, self.kalshi_feed.fetch_events, 100, "KXETH15M")
        k_sol_15 = await loop.run_in_executor(None, self.kalshi_feed.fetch_events, 100, "KXSOL15M")

        all_kalshi = {e.event_id: e for e in k_btc_15 + k_eth_15 + k_sol_15}.values()
        events = list(all_kalshi)

        counts = {
            "BTC15": len([e for e in events if "KXBTC15M" in e.ticker]),
            "ETH15": len([e for e in events if "KXETH15M" in e.ticker]),
            "SOL15": len([e for e in events if "KXSOL15M" in e.ticker])
        }
        logger.info(f"Fetched {len(events)} Kalshi events (Stats: {counts}).")
        return events

    async def fetch_poly_data(self):
        """Fetch Polymarket markets (async wrapper for sync API)"""
        loop = asyncio.get_event_loop()

        # OPTIMIZATION: Only fetch 20 most recent markets instead of 100
        # Since we only need 3-5 active markets (BTC, ETH, SOL every 15min),
        # fetching 20 gives us enough buffer while being much faster
        #
        # Also skip token validation (validate_tokens=False) - we'll validate
        # AFTER matching pairs, which is 10x faster
        poly_15m = await loop.run_in_executor(
            None,
            self.poly_feed.fetch_events,
            20,       # limit - only get 20 most recent (vs 100)
            102467,   # tag_id (15min markets)
            'active', # status
            False     # validate_tokens=False (FAST MODE)
        )

        logger.info(f"Fetched {len(poly_15m)} Polymarket 15m markets.")
        return poly_15m

    def filter_market_for_monitoring(self, ke: MarketEvent, pe: MarketEvent) -> bool:
        """
        Light filter for market discovery - only filter out CLOSED markets.
        We want to monitor CURRENT markets (even if they close soon).

        15-minute markets: We should trade on the market closing within the NEXT 15 minutes.
        Example at 22:42 UTC:
        - 22:45 market (closes in 3 min) = ACTIVE, trade this!
        - 23:00 market (closes in 18 min) = FUTURE, monitor but don't prioritize
        - 22:30 market (closed 12 min ago) = CLOSED, filter out
        """
        now = datetime.now()

        # Check time to close
        time_to_close_k = (ke.resolution_time - now).total_seconds()
        time_to_close_p = (pe.resolution_time - now).total_seconds()

        # Filter out ONLY markets that are already CLOSED (negative time)
        # DO NOT filter markets closing soon - those are the active ones we want!
        if time_to_close_k < 0 or time_to_close_p < 0:
            logger.debug(f"Filtered {ke.ticker}: Market already closed (K:{time_to_close_k:.0f}s, P:{time_to_close_p:.0f}s)")
            return False

        # DO NOT filter by extreme probabilities here - we want to monitor ALL markets
        # Probability filtering happens at execution time in check_can_trade()

        return True

    def check_can_trade(self, ke: MarketEvent, pe: MarketEvent) -> bool:
        """
        Check if we can actually TRADE this market pair (called before execution).
        This is where we check for extreme probabilities.
        """
        # Check for extreme probabilities - no point trading if no arb opportunity
        # Kalshi
        if ke.yes_price > 0.90 or ke.yes_price < 0.10:
            logger.debug(f"Cannot trade {ke.ticker}: Extreme Kalshi probability (YES: {ke.yes_price:.2%})")
            return False

        if ke.no_price > 0.90 or ke.no_price < 0.10:
            logger.debug(f"Cannot trade {ke.ticker}: Extreme Kalshi probability (NO: {ke.no_price:.2%})")
            return False

        # Polymarket
        if pe.yes_price > 0.90 or pe.yes_price < 0.10:
            logger.debug(f"Cannot trade {pe.ticker}: Extreme Poly probability (YES: {pe.yes_price:.2%})")
            return False

        if pe.no_price > 0.90 or pe.no_price < 0.10:
            logger.debug(f"Cannot trade {pe.ticker}: Extreme Poly probability (NO: {pe.no_price:.2%})")
            return False

        return True

    async def discover_markets(self):
        """Initial market discovery and matching"""
        logger.info("Discovering markets...")

        # Fetch both exchanges in parallel
        kalshi_events, poly_events = await asyncio.gather(
            self.fetch_kalshi_data(),
            self.fetch_poly_data()
        )

        # Filter candidates
        keywords = ["Bitcoin", "BTC", "Ethereum", "ETH", "Solana", "SOL"]

        k_candidates = [
            e for e in kalshi_events
            if any(k in e.title for k in keywords) or "KXBTC" in e.ticker or "KXETH" in e.ticker or "KXSOL" in e.ticker
        ]

        p_candidates = [
            e for e in poly_events
            if any(k in e.title for k in keywords) and ("Up or Down" in e.title)
        ]

        logger.info(f"Matching {len(k_candidates)} Kalshi vs {len(p_candidates)} Poly events.")

        # Match pairs and filter (only filter closed/closing markets, NOT extreme probabilities)
        matched_pairs = []
        for ke in k_candidates:
            for pe in p_candidates:
                if self.matcher.are_equivalent(ke, pe):
                    # Apply light filters (only time-based, not probability-based)
                    if self.filter_market_for_monitoring(ke, pe):
                        matched_pairs.append((ke, pe))

        logger.info(f"Found {len(matched_pairs)} matched pairs for monitoring (probability filtering at execution time).")

        # OPTIMIZATION: Validate Polymarket tokens AFTER matching (not before)
        # This way we only validate ~10-30 tokens instead of 200
        logger.info(f"Validating tokens for {len(matched_pairs)} matched pairs...")
        validated_pairs = []

        loop = asyncio.get_event_loop()
        for ke, pe in matched_pairs:
            # Get token ID from metadata
            clob_ids = pe.metadata.get('clobTokenIds', []) if pe.metadata else []
            if not clob_ids:
                logger.debug(f"Skipping {pe.ticker}: No CLOB tokens")
                continue

            token_id = clob_ids[0]

            # Validate token exists in CLOB (this is the only validation we need)
            is_valid = await loop.run_in_executor(None, self.poly_feed._validate_token, token_id)

            if is_valid:
                validated_pairs.append((ke, pe))
            else:
                logger.debug(f"Skipping {pe.ticker}: Invalid token {token_id}")

        logger.info(f"Found {len(validated_pairs)} pairs with valid tokens (filtered {len(matched_pairs) - len(validated_pairs)} invalid)")
        return validated_pairs

    async def on_orderbook_update(self, source: str, identifier: str, cache: OrderbookCache):
        """
        Callback triggered when WebSocket receives orderbook update.
        This is where real-time arbitrage detection happens.

        PARALLEL MONITORING: Check ALL markets for arbitrage opportunities.
        """
        logger.debug(f"Orderbook update from {source}: {identifier}")

        # Check if we're in cooldown period after a trade
        now = time.time()
        if now < self.market_cooldown_until:
            remaining = int(self.market_cooldown_until - now)
            logger.debug(f"In cooldown: {remaining}s remaining")
            return

        # Check ALL market pairs for arbitrage (parallel monitoring)
        for ke, pe in self.locked_pairs:
            # Check if market is already CLOSED - skip if so
            time_to_close = (ke.resolution_time - datetime.now()).total_seconds()
            if time_to_close < 0:
                logger.debug(f"Skipping {ke.ticker}: Market already closed ({time_to_close:.0f}s)")
                continue

            # We WANT to trade on markets closing soon - those are the ACTIVE ones!
            # Don't skip markets just because they're about to close.

            # Check arbitrage for this pair
            await self.check_arbitrage_live(ke, pe, cache)

    async def check_arbitrage_live(self, ke: MarketEvent, pe: MarketEvent, cache: OrderbookCache):
        """Check for arbitrage using live WebSocket orderbook data"""
        try:
            # Get live orderbooks from cache
            k_ob = cache.get_kalshi(ke.ticker)

            p_token = pe.metadata.get('clobTokenIds', [])[0] if pe.metadata and pe.metadata.get('clobTokenIds') else None
            p_ob = cache.get_poly(p_token) if p_token else None

            if not k_ob or not p_ob:
                logger.debug(f"Missing orderbook data for {ke.ticker}")
                return

            # Update MarketEvent with live prices from orderbooks
            # Kalshi: get best ask prices
            k_yes_asks = k_ob.get('yes', [])
            k_no_asks = k_ob.get('no', [])

            if k_yes_asks and k_yes_asks[0]:
                ke.yes_price = float(k_yes_asks[0][0]) / 100.0  # Convert cents to dollars
            if k_no_asks and k_no_asks[0]:
                ke.no_price = float(k_no_asks[0][0]) / 100.0

            # Polymarket: get best ask price
            p_asks = p_ob.get('asks', [])
            if p_asks and p_asks[0]:
                pe.yes_price = float(p_asks[0].get('price', 0))
                pe.no_price = 1.0 - pe.yes_price

            # OPT #13: Skip DB write in hot path, pass None as pair_id
            # DB logging will happen async if arbitrage is detected
            pair_id = None

            # Check for hard arbitrage
            opp = self.detector.check_hard_arbitrage(ke, pe, pair_id)

            if opp:
                # Check if we CAN trade this market (probability filter)
                can_trade = self.check_can_trade(ke, pe)

                if can_trade:
                    logger.info(f"ARBITRAGE DETECTED (WebSocket): {ke.ticker} <-> {pe.ticker}")
                    await self.execute_arbitrage(opp, ke, pe)
                else:
                    # Log rejected opportunity to database for dashboard visibility
                    rejection_reason = self._get_rejection_reason(ke, pe)
                    logger.debug(f"Market {ke.ticker} rejected: {rejection_reason}")
                    asyncio.create_task(self._log_rejected_opportunity(opp, ke, pe, rejection_reason))

        except Exception as e:
            logger.error(f"Error in live arbitrage check: {e}")

    async def rediscover_and_subscribe(self):
        """
        OPTIMIZATION: Rediscover markets ONLY after trade completion.
        Markets last 15 minutes, so periodic discovery is unnecessary.
        """
        try:
            logger.info("Rediscovering markets...")
            new_matched = await self.discover_markets()

            if not new_matched:
                logger.warning("No new markets found in rediscovery")
                return

            # Subscribe to any new pairs
            new_tickers = []
            new_tokens = []

            for ke, pe in new_matched:
                if (ke, pe) not in self.locked_pairs:
                    new_tickers.append(ke.ticker)
                    tokens = pe.metadata.get('clobTokenIds', []) if pe.metadata else []
                    new_tokens.extend(tokens)
                    self.locked_pairs.append((ke, pe))

            if new_tickers or new_tokens:
                logger.info(f"Subscribing to {len(new_tickers)} new Kalshi markets and {len(new_tokens)} new Poly tokens")
                if self.use_websockets and hasattr(self, 'ws_manager'):
                    # OPT #14: Fire-and-forget subscriptions (don't block)
                    if new_tickers:
                        asyncio.create_task(self.ws_manager.kalshi_ws.subscribe(new_tickers))
                    if new_tokens:
                        asyncio.create_task(self.ws_manager.poly_ws.subscribe(new_tokens))
                    logger.info("[OPT #14] Subscriptions initiated in background")
            else:
                logger.info("No new markets to subscribe to")

        except Exception as e:
            logger.error(f"Error in market rediscovery: {e}")

    def _get_rejection_reason(self, ke: MarketEvent, pe: MarketEvent) -> str:
        """Determine why a market was rejected for trading"""
        reasons = []

        # Check Kalshi probabilities
        if ke.yes_price > 0.90:
            reasons.append(f"Kalshi YES too high ({ke.yes_price:.1%})")
        if ke.yes_price < 0.10:
            reasons.append(f"Kalshi YES too low ({ke.yes_price:.1%})")
        if ke.no_price > 0.90:
            reasons.append(f"Kalshi NO too high ({ke.no_price:.1%})")
        if ke.no_price < 0.10:
            reasons.append(f"Kalshi NO too low ({ke.no_price:.1%})")

        # Check Polymarket probabilities
        if pe.yes_price > 0.90:
            reasons.append(f"Poly YES too high ({pe.yes_price:.1%})")
        if pe.yes_price < 0.10:
            reasons.append(f"Poly YES too low ({pe.yes_price:.1%})")
        if pe.no_price > 0.90:
            reasons.append(f"Poly NO too high ({pe.no_price:.1%})")
        if pe.no_price < 0.10:
            reasons.append(f"Poly NO too low ({pe.no_price:.1%})")

        return "; ".join(reasons) if reasons else "Unknown"

    async def _log_rejected_opportunity(self, opp, ke: MarketEvent, pe: MarketEvent, reason: str):
        """Log rejected arbitrage opportunity to database (async)"""
        try:
            # Use log_opportunity method (async via queue)
            details = {
                'type': opp.type,
                'buy_side': opp.buy_side,
                'kalshi_ticker': ke.ticker,
                'poly_ticker': pe.ticker,
                'timestamp': datetime.now().isoformat()
            }

            self.db_manager.log_opportunity(
                pair_id=None,  # No pair_id for rejected opportunities
                k_yes=ke.yes_price,
                k_no=ke.no_price,
                p_yes=pe.yes_price,
                p_no=pe.no_price,
                cost_a=ke.yes_price + pe.no_price,  # Example cost calculation
                cost_b=ke.no_price + pe.yes_price,
                profit=opp.profit_potential,
                decision="REJECTED",
                reason=reason,
                details=details
            )
            logger.debug(f"[DASHBOARD] Logged rejected opportunity: {ke.ticker} (reason: {reason})")
        except Exception as e:
            logger.error(f"Error logging rejected opportunity: {e}")

    async def _async_register_market_pair(self, ke: MarketEvent, pe: MarketEvent):
        """
        OPT #13: Async DB write for market pair registration.
        Fire-and-forget task to avoid blocking execution path.
        """
        try:
            k_dict = dataclasses.asdict(ke)
            p_dict = dataclasses.asdict(pe)

            # Run sync DB write in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,  # Use default ThreadPoolExecutor
                self.db_manager.register_market_pair,
                ke.ticker,
                pe.ticker,
                ke.title,
                ke.resolution_time,
                ke.event_id,
                pe.event_id,
                pe.title,
                k_dict,
                p_dict
            )
            logger.debug(f"[OPT #13] Async DB write completed for {ke.ticker}")
        except Exception as e:
            logger.error(f"[OPT #13] Error in async DB write: {e}")

    async def execute_arbitrage(self, opp, ke: MarketEvent, pe: MarketEvent):
        """Execute arbitrage opportunity"""
        # Deduplication check
        cache_key = f"{opp.type}:{ke.event_id}:{pe.event_id}"
        now = time.time()

        last_exec = self.execution_history.get(cache_key, 0)
        cooldown = 15  # 15 seconds

        if (now - last_exec) < cooldown:
            logger.info(f"Skipping Re-Execution for {cache_key} (Cooldown Active)")
            return

        try:
            # Execute async (executor.execute_strategy is now async)
            executed = await self.executor.execute_strategy(opp)

            # Set cooldown for 1 minute AFTER ANY TRADE (success, fail, or simulation)
            self.market_cooldown_until = time.time() + self.TRADE_COOLDOWN
            self.execution_history[cache_key] = time.time()

            if executed is True:  # Only stop if trade was actually executed (not False or None)
                logger.info(f"TRADE SUCCESSFULLY EXECUTED on {ke.ticker}!")

                # OPT #13: Register market pair AFTER trade (async, non-blocking)
                # Fire-and-forget DB write to avoid blocking execution
                asyncio.create_task(self._async_register_market_pair(ke, pe))

                # OPTIMIZATION: Rediscover markets ONLY after trade completes
                # Markets last 15 minutes, so we only need new markets after executing a trade
                logger.info("Trade completed - discovering new markets...")
                await self.rediscover_and_subscribe()
                logger.info(f"Market cooldown active for {self.TRADE_COOLDOWN} seconds")

                # Continue monitoring (don't stop bot)
                logger.info("Continuing to monitor ALL markets after cooldown...")
            else:
                # executed is False or None - trade was aborted
                logger.info(f"Trade aborted (status: {executed}). Market cooldown active for {self.TRADE_COOLDOWN} seconds")
        except Exception as e:
            logger.error(f"Execution error: {e}")
            # Set cooldown even on error to prevent rapid retries
            self.market_cooldown_until = time.time() + self.TRADE_COOLDOWN

    async def run_websocket_mode(self):
        """Main loop using WebSocket feeds"""
        logger.info("Starting WebSocket mode...")

        # Market discovery with retry loop (markets last 15 minutes)
        matched_pairs = None
        while self.running and not matched_pairs:
            matched_pairs = await self.discover_markets()

            if not matched_pairs:
                # Markets last 15 minutes - no need to check every 10s
                # Check every 5 minutes instead
                logger.warning("No matched pairs found. Retrying in 5 minutes (markets last 15min)...")
                await asyncio.sleep(300)  # 5 minutes

        if not self.running:
            return  # Bot stopped during discovery

        self.locked_pairs = matched_pairs

        # Extract tickers and tokens for subscription
        kalshi_tickers = [ke.ticker for ke, _ in matched_pairs]
        poly_tokens = []
        ticker_token_map = {}

        for ke, pe in matched_pairs:
            tokens = pe.metadata.get('clobTokenIds', []) if pe.metadata else []
            poly_tokens.extend(tokens)
            for token in tokens:
                ticker_token_map[ke.ticker] = token

        logger.info(f"Subscribing to {len(kalshi_tickers)} Kalshi tickers and {len(poly_tokens)} Poly tokens...")

        # Start WebSocket connections
        success = await self.ws_manager.start(kalshi_tickers, poly_tokens, ticker_token_map)

        if not success:
            logger.error("WebSocket connection failed. Falling back to REST mode.")
            self.use_websockets = False
            return

        logger.info("WebSocket feeds active. Listening for arbitrage opportunities...")

        # OPTIMIZATION: NO periodic rediscovery - markets last 15 minutes
        # Rediscovery only happens after trade completion (triggered by execute_arbitrage)
        # This reduces unnecessary API calls and latency

        # Keep running until stopped
        while self.running:
            try:
                # Just keep the loop alive and let WebSocket callbacks handle everything
                await asyncio.sleep(300)  # Sleep 5 minutes, just to keep loop responsive

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in WebSocket loop: {e}")
                await asyncio.sleep(5)

    async def run_rest_mode(self):
        """Fallback: REST polling mode (original implementation)"""
        logger.info("Running in REST polling mode...")

        while self.running:
            try:
                await self.tick_rest()

                # Dynamic polling interval
                if self.locked_pairs:
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Runtime error in REST loop: {e}")
                await asyncio.sleep(5)

    async def tick_rest(self):
        """Single tick of REST polling (converted to async)"""
        logger.info("--- Starting REST Tick ---")

        matched_pairs_with_id = []

        # Refresh locked pairs or discover new ones
        if self.locked_pairs:
            logger.info(f"Targeting {len(self.locked_pairs)} Locked Pairs...")

            refreshed_locked = []
            loop = asyncio.get_event_loop()

            for k_ev, p_ev in self.locked_pairs:
                try:
                    k_fresh = await loop.run_in_executor(None, self.kalshi_feed.get_market, k_ev.event_id)
                    p_fresh = await loop.run_in_executor(None, self.poly_feed.get_market, p_ev.event_id)

                    if k_fresh and p_fresh:
                        now = datetime.now()
                        if k_fresh.resolution_time > now and p_fresh.resolution_time > now:
                            refreshed_locked.append((k_fresh, p_fresh))
                        else:
                            logger.info(f"Market Expired: {k_fresh.ticker}")
                except Exception as e:
                    logger.error(f"Refresh failed for {k_ev.ticker}: {e}")

            if refreshed_locked:
                self.locked_pairs = refreshed_locked
                for ke, pe in self.locked_pairs:
                    # OPT #13: Skip DB write in REST mode hot path
                    # Will be written async if arbitrage is detected
                    pair_id = None
                    matched_pairs_with_id.append((ke, pe, pair_id))
            else:
                logger.info("All locked markets closed. Resuming search.")
                self.locked_pairs = []

        if not self.locked_pairs:
            matched_pairs = await self.discover_markets()
            self.locked_pairs = matched_pairs

            for ke, pe in matched_pairs:
                # OPT #13: Skip DB write in REST mode hot path
                # Will be written async if arbitrage is detected
                pair_id = None
                matched_pairs_with_id.append((ke, pe, pair_id))

        # Check arbitrage for each pair
        for ke, pe, pair_id in matched_pairs_with_id:
            opp = self.detector.check_hard_arbitrage(ke, pe, pair_id)
            if opp:
                await self.execute_arbitrage(opp, ke, pe)

    async def run_async(self):
        """Main async run loop"""
        self.running = True
        logger.info("Bot started in ASYNC mode.")

        # FIX #2: Start background balance sync task
        balance_sync_task = asyncio.create_task(self.risk.start_background_sync())
        logger.info("[BACKGROUND SYNC] Task started")

        try:
            if self.use_websockets:
                await self.run_websocket_mode()
            else:
                await self.run_rest_mode()
        except KeyboardInterrupt:
            logger.info("Stopping bot (KeyboardInterrupt)...")
        finally:
            # Cancel background task
            self.risk.stop()
            balance_sync_task.cancel()
            try:
                await balance_sync_task
            except asyncio.CancelledError:
                pass

            await self.stop()

    def run(self):
        """Entry point: start the async event loop"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")

    async def stop(self):
        """Stop the bot and cleanup"""
        logger.info("Stopping bot...")
        self.running = False

        # Close WebSocket connections
        if hasattr(self, 'ws_manager'):
            await self.ws_manager.stop()

        # OPT #3: Close aiohttp sessions in feeds
        if hasattr(self, 'execution_coordinator'):
            try:
                await self.execution_coordinator.close_async_sessions()
            except Exception as e:
                logger.error(f"Error closing async sessions: {e}")

        # Close database
        if hasattr(self, 'db_manager'):
            self.db_manager.close()

        logger.info("Bot stopped.")
