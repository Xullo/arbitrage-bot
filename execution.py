from config_manager import config
from risk_manager import RiskManager
from simulator import Simulator
from logger import logger
from arbitrage_engine import ArbitrageOpportunity
import asyncio
import time

class ExecutionCoordinator:
    """
    Routes orders to Simulator or Real Exchange APIs based on configuration.
    """
    
    def __init__(self, risk_manager: RiskManager, kalshi_feed=None, poly_feed=None, orderbook_cache=None):
        self.risk = risk_manager
        self.simulator = Simulator()
        self.k_feed = kalshi_feed
        self.p_feed = poly_feed
        # OPTIMIZATION: Use WebSocket cache to avoid unnecessary HTTP fetches
        self.orderbook_cache = orderbook_cache
        
    async def execute_strategy(self, opp: ArbitrageOpportunity):
        # 1. Calculate Risk-Based Size
        # Use dynamic sizing: (Bankroll * Max_Risk%) / Price
        # We need roughly equal exposure on both legs? 
        # Or base on Leg 1 price?
        # Leg 1 is Kalshi.
        # k_price + p_price approx 1.0 (Arb).
        # So we can just target a "Notional Value" per trade.
        
        entry_price = opp.event_kalshi.no_price if opp.buy_side == 'NO_K_YES_P' else opp.event_kalshi.yes_price
        # Wait, need intended buy price. 
        # Check logic below: k_side decided later.
        # Let's verify 'opp.buy_side' string meaning.
        # If 'YES_K_NO_P': We buy YES Kalshi. Price = yes_price.
        # If 'NO_K_YES_P': We buy NO Kalshi. Price = no_price.
        
        target_k_price = opp.event_kalshi.yes_price if 'YES_K' in opp.buy_side else opp.event_kalshi.no_price
        
        # Determine Poly Price (Approximate, relying on Opportunity data)
        # If YES_K_NO_P -> We Buy Poly NO.
        # If NO_K_YES_P -> We Buy Poly YES.
        target_p_price = opp.event_poly.no_price if 'NO_P' in opp.buy_side else opp.event_poly.yes_price
        
        # Max Risk Dollars for TOTAL trade (both legs combined)
        max_usd_risk_total = self.risk.get_max_trade_dollar_amount()

        # Calculate Contracts (Floor to int)
        if target_k_price <= 0.01: target_k_price = 0.01
        if target_p_price <= 0.01: target_p_price = 0.01

        # The constraint is: TOTAL cost (both legs) cannot exceed max_usd_risk_total
        # count_size * (target_k_price + target_p_price) <= max_usd_risk_total
        total_price_per_contract = target_k_price + target_p_price
        count_size = int(max_usd_risk_total / total_price_per_contract) if total_price_per_contract > 0 else 0
        
        # POLYMARKET MIN ORDER ENFORCEMENT
        # Polymarket requires order value >= $1.00
        # If count_size * target_p_price < 1.0, the order will fail.
        # Check if we need to bump size up.
        
        poly_value = count_size * target_p_price
        if poly_value < 1.0:
            import math
            min_required = math.ceil(1.0 / target_p_price)
            
            # Check if adopting 'min_required' fits within max allowed total risk
            cost_k_req = min_required * target_k_price
            cost_p_req = min_required * target_p_price
            total_cost_req = cost_k_req + cost_p_req

            if total_cost_req <= max_usd_risk_total:
                 count_size = min_required
                 logger.info(f"Bumped Size to {count_size} to satisfy Poly Min Order ($1). Total Cost: ${total_cost_req:.2f} (K: ${cost_k_req:.2f}, P: ${cost_p_req:.2f})")
            else:
                 # Skip bumping - let natural size through and hope Poly accepts it
                 # Or skip entirely if we can't afford even 1 contract
                 logger.info(f"Cannot bump to meet Poly $1 min (Total: ${total_cost_req:.2f} > limit ${max_usd_risk_total:.2f}). Trying natural size: {count_size}")
                 if count_size < 1:
                     logger.warning(f"Skipping: Cannot afford even 1 contract. Max total risk: ${max_usd_risk_total:.2f}")
                     return

        # Explicit Enforcement Log
        if count_size < 1:
            logger.warning(f"Low Bankroll Enforced: Max Total ${max_usd_risk_total:.2f}. K_Price {target_k_price:.2f}, P_Price {target_p_price:.2f} (Total: {total_price_per_contract:.2f}). Skipping.")
            return

        # Check bankroll availability (Checking BOTH legs combined for proper risk management)
        cost_estimate_k = count_size * target_k_price
        cost_estimate_p = count_size * target_p_price
        total_cost = cost_estimate_k + cost_estimate_p
        
        if not self.risk.can_execute(total_cost):
            return

        trade_size = float(count_size)
        logger.info(f"Dynamic Sizing: Max Total ${max_usd_risk_total:.2f}. Prices: K=${target_k_price:.2f}, P=${target_p_price:.2f} => {count_size} Contracts. (Total Cost: ${total_cost:.2f} = K:${cost_estimate_k:.2f} + P:${cost_estimate_p:.2f})")

        logger.info(f"Attempting execution for {opp.type} Arb...")

        if config.is_simulation():
            self._execute_sim(opp, trade_size)
        else:
            await self._execute_real(opp, trade_size)

        return True

    # OPT #3: Async helper to parallelize HTTP requests
    async def _fetch_orderbooks_and_balance_async(self, k_ticker: str, p_token: str):
        """
        OPT #3: Fetch orderbooks and balance in parallel using asyncio.gather.
        Returns: (poly_book, kalshi_book, kalshi_balance)

        Expected savings: 200-400ms (reduces ~600ms sequential to ~300ms parallel)
        """
        start_time = time.time()
        try:
            # Execute all 3 HTTP requests in parallel
            poly_book, kalshi_book, kalshi_balance = await asyncio.gather(
                self.p_feed.get_orderbook_async(p_token),
                self.k_feed.get_orderbook_async(k_ticker),
                self.k_feed.get_balance_async(),
                return_exceptions=True  # Don't fail all if one fails
            )

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"[OPT #3] Parallel fetch completed in {elapsed_ms:.0f}ms")

            # Handle exceptions in individual results
            if isinstance(poly_book, Exception):
                logger.error(f"[OPT #3] Poly orderbook fetch failed: {poly_book}")
                poly_book = {}
            if isinstance(kalshi_book, Exception):
                logger.error(f"[OPT #3] Kalshi orderbook fetch failed: {kalshi_book}")
                kalshi_book = {}
            if isinstance(kalshi_balance, Exception):
                logger.error(f"[OPT #3] Kalshi balance fetch failed: {kalshi_balance}")
                kalshi_balance = None

            return poly_book, kalshi_book, kalshi_balance

        except Exception as e:
            logger.error(f"[OPT #3] Parallel fetch failed: {e}")
            # Fallback to None/empty dicts
            return {}, {}, None

    def _execute_sim(self, opp: ArbitrageOpportunity, size: float):
        # Execute Leg A
        res_a = self.simulator.execute_order(opp.event_kalshi.ticker, "BUY", opp.event_kalshi.yes_price, size)
        
        # Execute Leg B
        res_b = self.simulator.execute_order(opp.event_poly.ticker, "BUY", opp.event_poly.no_price, size)
        
        if res_a.success and res_b.success:
            logger.info("Strategies SUCCESSFULLY executed in SIM.")
            realized_pnl = self.simulator.simulate_pnl_impact(opp.profit_potential * size)
            self.risk.update_pnl(realized_pnl)
            logger.info(f"Realized PnL: ${realized_pnl:.2f}")

            # Persist Opportunity/Trade to DB
            try:
                # We need details
                self.risk.db.log_opportunity(
                     pair_id=1,  # Placeholder - ideally should be matched_market_id
                     k_yes=opp.event_kalshi.yes_price,
                     k_no=opp.event_kalshi.no_price,
                     p_yes=opp.event_poly.yes_price,
                     p_no=opp.event_poly.no_price,
                     cost_a=opp.event_poly.yes_price + opp.event_kalshi.no_price,
                     cost_b=opp.event_poly.no_price + opp.event_kalshi.yes_price,
                     profit=opp.profit_potential,
                     decision="ACCEPTED",
                     reason=f"Size: {size}, PnL: ${realized_pnl:.2f}",
                     details={
                         "pnl": realized_pnl,
                         "size": size,
                         "kalshi_ticker": opp.event_kalshi.ticker,
                         "poly_ticker": opp.event_poly.ticker,
                         "buy_side": opp.buy_side,
                         "type": opp.type
                     }
                )
                logger.info(f"Opportunity logged to database")
            except Exception as e:
                logger.error(f"Failed to log opportunity to DB: {e}")

        else:
            logger.error("Execution FAILED in SIM (Leg failure).")
            # In real life, we'd need to unwind the successful leg here.

    async def _execute_real(self, opp: ArbitrageOpportunity, size: float):
        """
        ATOMIC EXECUTION LOGIC (ASYNC)
        1. Execute Leg 1 (Kalshi) -> Wait for confirmation.
        2. Execute Leg 2 (Poly) -> If fail, Retry or Unwind.
        """
        # Determine Legs based on Opportunity Type
        # Hard Arb: Buy YES Kalshi, Buy NO Poly (or vice versa)
        # We start with Kalshi (Usually lower liquidity/slower)

        # Extract params
        k_ticker = opp.event_kalshi.ticker

        # OPT #2: Use pre-computed tokens if available, fallback to old method
        if opp.poly_token_yes and opp.poly_token_no:
            # Fast path: tokens already computed
            p_token_yes = opp.poly_token_yes
            p_token_no = opp.poly_token_no
        else:
            # Slow path: compute now (fallback)
            logger.warning(f"Tokens not pre-computed for {opp.event_poly.ticker}, using fallback")
            p_token_id = opp.event_poly.metadata.get('clobTokenIds', []) if opp.event_poly.metadata else []
            if len(p_token_id) >= 2:
                p_token_yes, p_token_no = p_token_id[0], p_token_id[1]
            else:
                logger.error("Cannot determine Poly tokens")
                return False
        
        # Identify Kalshi Side and Price
        # If opportunity is "Buy A (Yes K + No P)" -> Kalshi Side is YES
        # If opportunity is "Buy B (No K + Yes P)" -> Kalshi Side is NO
        # Wait, previous logic in engine:
        # Scenario A: Poly YES + Kalshi NO. Decision "BUY A".
        # Scenario B: Poly NO + Kalshi YES. Decision "BUY B".
        # PLEASE NOTE: Engines 'A' usually referred to the combo.
        # Let's re-read engine decision string logic or standard.
        # Engine: "BUY A" if Net Profit > Min.
        # A = Poly YES + Kalshi NO.
        # B = Poly NO + Kalshi YES.
        
        k_side = 'no' if opp.buy_side == 'A' else 'yes'
        # For Kalshi "NO" (Buy No), we pay the 'no_price'.
        k_price = opp.event_kalshi.no_price if k_side == 'no' else opp.event_kalshi.yes_price
        
        # Identify Poly Side and Token
        p_side = 'BUY' # Always buying outcomes
        # Token ID: 0=Long/Yes? 1=Short/No? 
        # Needs robust mapping. Assuming standard [0]=Yes/Long, [1]=No/Short if unrelated to negation?
        # Actually Poly API `clobTokenIds` usually ["token_for_outcome_0", "token_for_outcome_1"].
        # If Binary: 1 = YES, 0 = NO? Or 0=NO, 1=YES?
        # LOGIC: Engine returns:
        # 'NO_K_YES_P' (Scenario A) -> Buy Kalshi NO, Buy Poly YES.
        # 'YES_K_NO_P' (Scenario B) -> Buy Kalshi YES, Buy Poly NO.
        
        if opp.buy_side == 'NO_K_YES_P':
             k_side = 'no'
             k_price = opp.event_kalshi.no_price
             # Poly YES -> Use pre-computed YES token (OPT #2)
             p_token_target = p_token_yes
             p_price = opp.event_poly.yes_price

        elif opp.buy_side == 'YES_K_NO_P':
             k_side = 'yes'
             k_price = opp.event_kalshi.yes_price
             # Poly NO -> Use pre-computed NO token (OPT #2)
             p_token_target = p_token_no
             p_price = opp.event_poly.no_price
        else:
             logger.error(f"Unknown Buy Side: {opp.buy_side}. Aborting.")
             return False

        # Validate token
        if not p_token_target:
            logger.error(f"Invalid Poly token for {opp.buy_side}")
            return False

        # CLAMP PRICES: Kalshi rejects 0.
        if k_price < 0.01:
             logger.info(f"Clamping K_Price {k_price} to 0.01")
             k_price = 0.01

        logger.info(f"EXECUTING REAL: Kalshi {k_side.upper()} @ {k_price} | Poly {opp.buy_side} @ {p_price}")

        if not self.k_feed or not self.p_feed:
            logger.error("EXECUTION ABORTED: Feeds not injected for Real Trading.")
            return False

        # --- STRICT ORDERBOOK PRICE SELECTION ---
        # CRITICAL: Only use orderbook prices, no fallback to theoretical prices
        # This ensures we only execute when real liquidity exists

        # OPTIMIZATION: Try cache first (if fresh < 500ms, avoid HTTP fetch entirely)
        poly_book = None
        kalshi_book = None
        kalshi_balance = None
        used_cache = False

        if self.orderbook_cache:
            # Try to get fresh data from WebSocket cache (TTL = 500ms)
            poly_book = self.orderbook_cache.get_poly(p_token_target)
            kalshi_book = self.orderbook_cache.get_kalshi(k_ticker)

            if poly_book and kalshi_book:
                used_cache = True
                logger.info("[CACHE] Using fresh WebSocket orderbook data (< 500ms old)")

                # OPT #8: Skip balance check if background sync is recent (< 10s)
                balance_age_s = time.time() - self.risk.last_balance_sync_time
                if balance_age_s < 10.0:
                    kalshi_balance = self.risk.bankroll  # Use cached from background sync
                    logger.info(f"[OPT #8] Skipping balance check (synced {balance_age_s:.1f}s ago)")
                else:
                    # Balance stale, fetch it async
                    try:
                        kalshi_balance = await asyncio.create_task(self.k_feed.get_balance_async())
                    except Exception:
                        kalshi_balance = self.k_feed.get_balance()

        # If cache miss or stale, fetch fresh data
        if not used_cache or not poly_book or not kalshi_book:
            logger.info("[CACHE] Cache miss or stale - fetching fresh orderbooks...")
            # OPT #3: Fetch orderbooks and balance IN PARALLEL (200-400ms savings)
            try:
                poly_book, kalshi_book, kalshi_balance = await self._fetch_orderbooks_and_balance_async(k_ticker, p_token_target)
            except Exception as e:
                logger.error(f"[OPT #3] Async fetch failed, falling back to sync: {e}")
                # Fallback to sequential sync calls
                poly_book = self.p_feed.get_orderbook(p_token_target)
                kalshi_book = self.k_feed.get_orderbook(k_ticker)
                kalshi_balance = self.k_feed.get_balance()

        # Fetch Polymarket orderbook (validation of parallel result)
        if not poly_book or 'asks' not in poly_book or not poly_book['asks']:
            logger.error(f"ABORT: No Polymarket orderbook data available for token {p_token_target[:16]}...")
            return False

        best_ask_poly = poly_book['asks'][0]
        p_price_orderbook = float(best_ask_poly.get('price', 0))
        p_size_available = float(best_ask_poly.get('size', 0))

        if p_size_available < size:
            logger.error(f"ABORT: Insufficient Poly liquidity ({p_size_available} < {size})")
            return False

        if p_price_orderbook == 0:
            logger.error(f"ABORT: Invalid Poly orderbook price")
            return False

        logger.info(f"Poly orderbook: Best ask ${p_price_orderbook:.3f} (available: {p_size_available})")

        # Validate Kalshi orderbook (from parallel result)
        if not kalshi_book or k_side not in kalshi_book:
            logger.error(f"ABORT: No Kalshi orderbook data for {k_ticker} side {k_side}")
            return False

        side_book = kalshi_book[k_side]
        if not side_book or not isinstance(side_book, list) or len(side_book) == 0:
            logger.error(f"ABORT: Empty Kalshi {k_side} orderbook")
            return False

        best_level_kalshi = side_book[0]
        if not isinstance(best_level_kalshi, dict):
            logger.error(f"ABORT: Invalid Kalshi orderbook format")
            return False

        k_price_orderbook = float(best_level_kalshi.get('price', 0))
        k_size_available = int(best_level_kalshi.get('size', 0))

        if k_size_available < size:
            logger.error(f"ABORT: Insufficient Kalshi liquidity ({k_size_available} < {size})")
            return False

        if k_price_orderbook == 0 or k_price_orderbook < 0.01:
            logger.error(f"ABORT: Invalid Kalshi orderbook price {k_price_orderbook}")
            return False

        logger.info(f"Kalshi orderbook: Best {k_side} ask ${k_price_orderbook:.3f} (available: {k_size_available})")

        # Use orderbook prices (no fallback)
        p_price = p_price_orderbook
        k_price = k_price_orderbook

        # --- BALANCE VERIFICATION ---
        # Check actual available balance on both exchanges
        poly_cost = size * p_price
        kalshi_cost = size * k_price

        # Polymarket minimum: $1.00
        if poly_cost < 1.0:
            logger.error(f"ABORT: Poly order ${poly_cost:.2f} below $1.00 minimum")
            return False

        # Check Kalshi balance (already fetched in parallel)
        if kalshi_balance is None:
            logger.warning("Could not fetch Kalshi balance, proceeding with caution")
        elif kalshi_balance < kalshi_cost:
            logger.error(f"ABORT: Insufficient Kalshi balance (${kalshi_balance:.2f} < ${kalshi_cost:.2f})")
            return False
        else:
            logger.info(f"Kalshi balance check: ${kalshi_balance:.2f} >= ${kalshi_cost:.2f} ✓")

        # Check Polymarket balance (from risk manager which tracks combined balance)
        # Use conservative check: ensure we have enough for BOTH legs
        total_cost = poly_cost + kalshi_cost
        if not self.risk.can_execute(total_cost):
            logger.error(f"ABORT: Insufficient total balance for combined order (${total_cost:.2f})")
            return False

        logger.info(f"Balance verification passed: Poly ${poly_cost:.2f}, Kalshi ${kalshi_cost:.2f}, Total ${total_cost:.2f}")

        try:
            # --- PARALLEL STRATEGY: BOTH EXCHANGES AT ONCE ---
            # Execute both legs simultaneously using market-available prices
            logger.info(f"EXECUTING PARALLEL: Poly {p_side} @ {p_price} | Kalshi {k_side.upper()} @ {k_price}")

            # Use best available prices from orderbook (where liquidity exists)
            # Instead of limit orders at theoretical prices, use aggressive market orders
            import concurrent.futures

            # --- STEP 1: PLACE BOTH ORDERS IN PARALLEL ---
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                logger.info(f"REAL: Placing PARALLEL Orders (Poly: {p_side} @ {p_price}, Kalshi: {k_side} @ {k_price}, Size: {size})...")

                # Submit both orders concurrently
                poly_future = executor.submit(self.p_feed.place_order, token_id=p_token_target, side=p_side, count=size, price=p_price)
                kalshi_future = executor.submit(self.k_feed.place_order, ticker=k_ticker, side=k_side, count=size, price=k_price)

                # Wait for both to complete
                p_resp = poly_future.result()
                k_resp = kalshi_future.result()
            
            # --- STEP 2: CHECK BOTH RESPONSES ---
            p_success = "error" not in p_resp and p_resp.get("orderID")
            k_success = "error" not in k_resp and k_resp.get("order")

            if not p_success:
                logger.error(f"REAL: Poly Order Failed: {p_resp}")
            if not k_success:
                logger.error(f"REAL: Kalshi Order Failed: {k_resp}")

            if not p_success and not k_success:
                logger.error("REAL: BOTH orders failed. Aborting.")
                return False

            p_order_id = p_resp.get("orderID") if p_success else None
            k_order_id = k_resp.get("order", {}).get("order_id") if k_success else None

            logger.info(f"REAL: Orders Posted - Poly: {p_order_id}, Kalshi: {k_order_id}")

            # --- STEP 3: MONITOR BOTH FILLS IN PARALLEL ---
            # OPT #1: Optimized fill monitoring loop (exits early when filled)
            p_filled = 0.0
            k_filled = 0

            # Monitor for 10 seconds max with exponential backoff
            wait_times = [0.1, 0.2, 0.3, 0.5, 1, 1, 2, 2, 3, 3]  # Total: ~13s max
            for attempt, wait_time in enumerate(wait_times):
                # OPT #1: Check BEFORE sleep to exit immediately if filled
                if p_filled >= size and k_filled >= size:
                    logger.info(f"REAL: BOTH orders FULLY FILLED after {attempt} checks!")
                    break

                # Check Polymarket fill
                if p_order_id and p_filled < size:
                    try:
                        p_status_data = self.p_feed.get_order(p_order_id)
                        if "error" not in p_status_data:
                            size_matched = float(p_status_data.get("size_matched", 0.0))
                            if size_matched > p_filled:
                                p_filled = size_matched
                                logger.info(f"REAL: Poly Fill Update: {p_filled}/{size}")
                    except Exception as e:
                        logger.warning(f"Poly status check failed: {e}")

                # Check Kalshi fill
                if k_order_id and k_filled < size:
                    try:
                        order_data = self.k_feed.get_order(k_order_id)
                        if "error" not in order_data:
                            o = order_data.get("order", {})
                            current_fill = o.get("filled_count", 0)
                            if current_fill > k_filled:
                                k_filled = current_fill
                                logger.info(f"REAL: Kalshi Fill Update: {k_filled}/{size}")
                    except Exception as e:
                        logger.warning(f"Kalshi status check failed: {e}")

                # Check again after fetching (early exit optimization)
                if p_filled >= size and k_filled >= size:
                    logger.info(f"REAL: BOTH orders FULLY FILLED after {attempt+1} checks!")
                    break

                # Sleep before next check (unless it's the last iteration)
                if attempt < len(wait_times) - 1:
                    time.sleep(wait_time)

            # --- STEP 4: FINAL ANALYSIS ---
            logger.info(f"REAL: Final Fill Status - Poly: {p_filled}/{size}, Kalshi: {k_filled}/{size}")

            if p_filled >= size and k_filled >= size:
                logger.info(f"ARBITRAGE SUCCESS: Fully Executed {size} units on both sides.")

                # FIX #4: Include fees in exposure tracking
                k_cost = size * k_price
                p_cost = size * p_price
                k_fee = k_cost * 0.01  # Kalshi 1% taker fee
                p_fee = size * 0.001   # Polymarket $0.001 per contract flat fee

                total_cost_with_fees = k_cost + p_cost + k_fee + p_fee

                logger.info(f"[FEES] Kalshi: ${k_cost:.2f} + ${k_fee:.4f} fee | Poly: ${p_cost:.2f} + ${p_fee:.4f} fee | Total: ${total_cost_with_fees:.2f}")

                self.risk.register_trade(total_cost_with_fees)
                return True
            elif p_filled > 0 or k_filled > 0:
                # Partial fill scenario - need to unwind the imbalance
                logger.warning(f"REAL: Partial Fill Scenario - Poly: {p_filled}/{size}, Kalshi: {k_filled}/{size}")

                if k_filled > 0 and p_filled > 0:
                    # Both partially filled - register what executed (with fees)
                    filled_amount = min(k_filled, p_filled)

                    # FIX #4: Calculate fees for partial fill
                    k_cost_partial = filled_amount * k_price
                    p_cost_partial = filled_amount * p_price
                    k_fee_partial = k_cost_partial * 0.01
                    p_fee_partial = filled_amount * 0.001
                    total_cost_partial = k_cost_partial + p_cost_partial + k_fee_partial + p_fee_partial

                    logger.info(f"[PARTIAL FILL] Registering {filled_amount} contracts: ${total_cost_partial:.2f} (including fees)")
                    self.risk.register_trade(total_cost_partial)

                # Unwind imbalanced positions
                if p_filled > k_filled:
                    # Polymarket filled more - need to unwind excess Poly position
                    unmatched = p_filled - k_filled
                    logger.critical(f"UNWIND: Unwinding {unmatched} excess Poly units.")
                    unwind_side = 'SELL' if p_side == 'BUY' else 'BUY'
                    self._unwind_poly(p_token_target, unwind_side, unmatched, order_id=p_order_id)

                elif k_filled > p_filled:
                    # Kalshi filled more - need to unwind excess Kalshi position
                    unmatched = k_filled - p_filled
                    logger.critical(f"UNWIND: Unwinding {unmatched} excess Kalshi units.")
                    self._unwind_kalshi(k_ticker, k_side, unmatched, order_id=k_order_id)

                return False

        except KeyboardInterrupt:
            logger.critical("INTERRUPT DETECTED DURING PARALLEL EXECUTION!")
            raise 
            
        except Exception as e:
            logger.critical(f"CRITICAL PARALLEL EXECUTION ERROR: {e}")
            return False

    def _unwind_poly(self, token_id, side, qty, order_id=None):
        """
        Intelligent Polymarket unwind mechanism.
        Evaluates multiple exit strategies and chooses the cheapest option:
        1. Cancel pending order (if still open, cost = $0)
        2. Buy opposite side to hedge (cost = opposite_price * qty + fees)
        3. Sell at market (aggressive limit, cost = slippage + fees)
        """
        try:
            logger.critical(f"UNWIND POLY: Evaluating exit strategies for {qty} units (token: {token_id[:16]}...)")

            # --- OPTION 1: CANCEL ORDER (cheapest if still pending) ---
            if order_id:
                try:
                    # Check order status
                    order_status = self.p_feed.get_order(order_id)
                    if "error" not in order_status:
                        status = order_status.get('status', '').upper()
                        size_matched = float(order_status.get('size_matched', 0))
                        size_remaining = qty - size_matched

                        if status in ['LIVE', 'PENDING'] and size_remaining > 0:
                            logger.info(f"UNWIND POLY: Order {order_id[:16]}... is {status}, attempting cancel...")

                            # Cancel via py_clob_client
                            from py_clob_client.client import ClobClient
                            from py_clob_client.constants import POLYGON
                            from py_clob_client.clob_types import ApiCreds

                            pkey = os.getenv("POLYMARKET_PRIVATE_KEY")
                            safe_address = os.getenv("POLYMARKET_SAFE_ADDRESS")

                            api_creds = ApiCreds(
                                api_key=os.getenv("POLYMARKET_API_KEY"),
                                api_secret=os.getenv("POLYMARKET_API_SECRET"),
                                api_passphrase=os.getenv("POLYMARKET_PASSPHRASE")
                            )

                            client = ClobClient(
                                host="https://clob.polymarket.com",
                                chain_id=POLYGON,
                                key=pkey,
                                creds=api_creds,
                                signature_type=2,
                                funder=safe_address
                            )

                            cancel_resp = client.cancel(order_id)

                            if cancel_resp.get('success'):
                                logger.info(f"UNWIND POLY: Successfully cancelled {size_remaining} units (cost: $0)")
                                return True
                            else:
                                logger.warning(f"UNWIND POLY: Cancel failed: {cancel_resp.get('errorMsg', 'Unknown')}")
                        else:
                            logger.info(f"UNWIND POLY: Order already {status}, cannot cancel")
                except Exception as e:
                    logger.warning(f"UNWIND POLY: Cancel attempt failed: {e}")

            # --- OPTION 2 & 3: COMPARE COSTS ---
            # Fetch current orderbook to evaluate costs
            orderbook = self.p_feed.get_orderbook(token_id)

            # Cost to buy opposite side (hedge to flat)
            opposite_cost = None
            if orderbook:
                if side == 'SELL':
                    # We're short, need to BUY to hedge
                    if 'asks' in orderbook and orderbook['asks']:
                        best_ask = orderbook['asks'][0]
                        opposite_price = float(best_ask.get('price', 0.99))
                        opposite_size = float(best_ask.get('size', 0))

                        if opposite_size >= qty:
                            # Poly fees: 0.001 per unit
                            opposite_cost = (opposite_price * qty) + (0.001 * qty)
                            logger.info(f"UNWIND POLY: Hedge option - BUY {qty} @ ${opposite_price:.3f} = ${opposite_cost:.2f}")
                        else:
                            logger.warning(f"UNWIND POLY: Insufficient liquidity to hedge ({opposite_size} < {qty})")
                else:
                    # We're long, need to SELL to hedge
                    if 'bids' in orderbook and orderbook['bids']:
                        best_bid = orderbook['bids'][0]
                        opposite_price = float(best_bid.get('price', 0.01))
                        opposite_size = float(best_bid.get('size', 0))

                        if opposite_size >= qty:
                            # Revenue from selling - fees
                            opposite_cost = -(opposite_price * qty) + (0.001 * qty)  # Negative = we receive money
                            logger.info(f"UNWIND POLY: Hedge option - SELL {qty} @ ${opposite_price:.3f} = ${-opposite_cost:.2f} revenue")
                        else:
                            logger.warning(f"UNWIND POLY: Insufficient liquidity to hedge ({opposite_size} < {qty})")

            # Cost to place aggressive limit (essentially market order)
            aggressive_price = 0.01 if side == 'SELL' else 0.99
            aggressive_cost = (aggressive_price * qty) + (0.001 * qty) if side == 'BUY' else -(aggressive_price * qty) + (0.001 * qty)

            logger.info(f"UNWIND POLY: Aggressive limit - {side} {qty} @ ${aggressive_price:.2f} = ${abs(aggressive_cost):.2f}")

            # --- CHOOSE CHEAPEST OPTION ---
            if opposite_cost is not None:
                # Compare absolute costs
                if abs(opposite_cost) < abs(aggressive_cost):
                    # Hedge is cheaper
                    hedge_side = 'BUY' if side == 'SELL' else 'SELL'
                    hedge_price = opposite_price
                    logger.critical(f"UNWIND POLY: HEDGING - {hedge_side} {qty} @ ${hedge_price:.3f} (saves ${abs(aggressive_cost - opposite_cost):.2f})")

                    resp = self.p_feed.place_order(
                        token_id=token_id,
                        side=hedge_side,
                        count=qty,
                        price=hedge_price
                    )

                    if "error" not in resp:
                        logger.info(f"UNWIND POLY: Hedge order placed successfully: {resp.get('orderID', 'N/A')}")
                        return True
                    else:
                        logger.error(f"UNWIND POLY: Hedge order failed: {resp}")
                        # Fall through to aggressive limit

            # Default: Aggressive limit
            logger.critical(f"UNWIND POLY: AGGRESSIVE LIMIT - {side} {qty} @ ${aggressive_price:.2f}")
            resp = self.p_feed.place_order(
                token_id=token_id,
                side=side,
                count=qty,
                price=aggressive_price
            )

            if "error" not in resp:
                logger.info(f"UNWIND POLY: Aggressive order placed: {resp.get('orderID', 'N/A')}")
                return True
            else:
                logger.error(f"UNWIND POLY: Aggressive order failed: {resp}")
                return False

        except Exception as e:
            logger.error(f"FAILED TO UNWIND POLY: {e}")
            import traceback
            traceback.print_exc()
            return False

        except KeyboardInterrupt:
            logger.critical("INTERRUPT DETECTED DURING ATOMIC EXECUTION!")
            if 'filled_qty' in locals() and filled_qty > 0:
                logger.critical(f"EMERGENCY UNWIND: Attempting to close {filled_qty} Kalshi Contracts...")
                self._unwind_kalshi(k_ticker, k_side, filled_qty)
            else:
                logger.critical("Interrupt before fill confirmation. Check account manually.")
            raise # Re-raise to stop bot
            
        except Exception as e:
            logger.critical(f"CRITICAL EXECUTION ERROR: {e}")
            if 'filled_qty' in locals() and filled_qty > 0:
                 logger.critical(f"ERROR UNWIND: Attempting to close {filled_qty} Kalshi Contracts...")
                 self._unwind_kalshi(k_ticker, k_side, filled_qty)

    def _unwind_kalshi(self, ticker, original_side, qty, order_id=None):
        """
        Intelligent Kalshi unwind mechanism.
        Evaluates multiple exit strategies and chooses the cheapest option:
        1. Cancel pending order (if still open, cost = $0)
        2. Buy opposite side to hedge (cost = opposite_price * qty + fees)
        3. Place aggressive limit (essentially market, cost = slippage + fees)
        """
        try:
            logger.critical(f"UNWIND KALSHI: Evaluating exit strategies for {qty} units (ticker: {ticker})")

            # --- OPTION 1: CANCEL ORDER (cheapest if still pending) ---
            if order_id:
                try:
                    # Check order status
                    order_status = self.k_feed.get_order(order_id)
                    if "error" not in order_status:
                        order = order_status.get('order', {})
                        status = order.get('status', '').upper()
                        filled_count = order.get('filled_count', 0)
                        remaining_count = qty - filled_count

                        if status in ['RESTING', 'PENDING'] and remaining_count > 0:
                            logger.info(f"UNWIND KALSHI: Order {order_id} is {status}, attempting cancel...")

                            cancel_resp = self.k_feed.cancel_order(order_id)

                            if "error" not in cancel_resp:
                                logger.info(f"UNWIND KALSHI: Successfully cancelled {remaining_count} units (cost: $0)")
                                return True
                            else:
                                logger.warning(f"UNWIND KALSHI: Cancel failed: {cancel_resp.get('error', 'Unknown')}")
                        else:
                            logger.info(f"UNWIND KALSHI: Order already {status}, cannot cancel")
                except Exception as e:
                    logger.warning(f"UNWIND KALSHI: Cancel attempt failed: {e}")

            # --- OPTION 2 & 3: COMPARE COSTS ---
            # Fetch current orderbook to evaluate costs
            orderbook = self.k_feed.get_orderbook(ticker)

            # Determine unwind side (opposite of original position)
            unwind_side = 'yes' if original_side == 'no' else 'no'

            # Cost to buy opposite side (hedge to flat)
            opposite_cost = None
            if orderbook and unwind_side in orderbook:
                side_book = orderbook[unwind_side]
                if side_book and isinstance(side_book, list) and len(side_book) > 0:
                    best_level = side_book[0]
                    if isinstance(best_level, dict):
                        opposite_price = float(best_level.get('price', 0.99))
                        opposite_size = int(best_level.get('size', 0))

                        if opposite_size >= qty:
                            # Kalshi fees: 1% of trade value
                            trade_value = opposite_price * qty
                            kalshi_fee = trade_value * 0.01
                            opposite_cost = trade_value + kalshi_fee
                            logger.info(f"UNWIND KALSHI: Hedge option - {unwind_side.upper()} {qty} @ ${opposite_price:.3f} = ${opposite_cost:.2f}")
                        else:
                            logger.warning(f"UNWIND KALSHI: Insufficient liquidity to hedge ({opposite_size} < {qty})")

            # Cost to place aggressive limit (essentially market order)
            aggressive_price = 0.99
            aggressive_value = aggressive_price * qty
            aggressive_fee = aggressive_value * 0.01
            aggressive_cost = aggressive_value + aggressive_fee

            logger.info(f"UNWIND KALSHI: Aggressive limit - {unwind_side.upper()} {qty} @ ${aggressive_price:.2f} = ${aggressive_cost:.2f}")

            # --- CHOOSE CHEAPEST OPTION ---
            if opposite_cost is not None and opposite_cost < aggressive_cost:
                # Hedge at orderbook price is cheaper
                logger.critical(f"UNWIND KALSHI: HEDGING - {unwind_side.upper()} {qty} @ ${opposite_price:.3f} (saves ${aggressive_cost - opposite_cost:.2f})")

                resp = self.k_feed.place_order(
                    ticker=ticker,
                    side=unwind_side,
                    count=qty,
                    price=opposite_price
                )

                if "error" not in resp:
                    logger.info(f"UNWIND KALSHI: Hedge order placed successfully: {resp.get('order', {}).get('order_id', 'N/A')}")
                    return True
                else:
                    logger.error(f"UNWIND KALSHI: Hedge order failed: {resp}")
                    # Fall through to aggressive limit

            # Default: Aggressive limit
            logger.critical(f"UNWIND KALSHI: AGGRESSIVE LIMIT - {unwind_side.upper()} {qty} @ ${aggressive_price:.2f}")
            resp = self.k_feed.place_order(
                ticker=ticker,
                side=unwind_side,
                count=qty,
                price=aggressive_price
            )

            if "error" not in resp:
                logger.info(f"UNWIND KALSHI: Aggressive order placed: {resp.get('order', {}).get('order_id', 'N/A')}")
                return True
            else:
                logger.error(f"UNWIND KALSHI: Aggressive order failed: {resp}")
                return False

        except Exception as e:
            logger.error(f"FAILED TO UNWIND KALSHI: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_poly_token(self, token_ids: list, event, target_outcome: str) -> str:
        """
        Robustly identify the correct Polymarket token for YES or NO outcome.
        Falls back to index-based selection if metadata unavailable.
        """
        # Polymarket clobTokenIds order varies. Try to use outcomes metadata if available.
        # 'outcomes' from API is usually like ['Yes', 'No'] or ['No', 'Yes']
        outcomes = event.metadata.get('outcomes') if event.metadata else None
        
        if outcomes and len(outcomes) >= 2 and len(token_ids) >= 2:
            try:
                # Find index of target outcome
                for i, outcome in enumerate(outcomes):
                    if outcome.lower() == target_outcome.lower():
                        return token_ids[i]
            except Exception:
                pass
        
        # Fallback: Assume [0]=YES, [1]=NO (common convention)
        logger.warning(f"Using fallback token index for {target_outcome}")
        if target_outcome.upper() == 'YES':
            return token_ids[0] if len(token_ids) > 0 else None
        else:
            return token_ids[1] if len(token_ids) > 1 else None

    # OPT #3: Cleanup method for async sessions
    async def close_async_sessions(self):
        """
        OPT #3: Close aiohttp sessions in both feeds for cleanup.
        Should be called when bot stops.
        """
        try:
            if self.p_feed:
                await self.p_feed.close_async_session()
                logger.info("[OPT #3] Closed Polymarket async session")
        except Exception as e:
            logger.error(f"[OPT #3] Error closing Poly session: {e}")

        try:
            if self.k_feed:
                await self.k_feed.close_async_session()
                logger.info("[OPT #3] Closed Kalshi async session")
        except Exception as e:
            logger.error(f"[OPT #3] Error closing Kalshi session: {e}")

