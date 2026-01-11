import time
from datetime import datetime, timedelta
from market_data import MarketEvent, KalshiFeed, PolymarketFeed
from event_matcher import EventMatcher
from arbitrage_engine import ArbitrageDetector
from risk_manager import RiskManager
from execution import ExecutionCoordinator
from config_manager import config
from logger import logger

def main():
    logger.info("Starting Arbitrage Bot in PAPER TRADING MODE (Live Data, Sim Execution)...")
    
    # 1. Initialize Components
    config.validate_keys()
    
    risk = RiskManager(current_bankroll=2000.0) 
    detector = ArbitrageDetector(fee_kalshi=0.02, fee_poly=0.0) # Approx fees
    matcher = EventMatcher()
    executor = ExecutionCoordinator(risk)
    
    # Initialize Feeds
    try:
        kalshi_feed = KalshiFeed(config.KALSHI_API_KEY, config.KALSHI_API_SECRET)
        poly_feed = PolymarketFeed()
    except Exception as e:
        logger.critical(f"Failed to initialize feeds: {e}")
        return

    logger.info("Feeds initialized. Starting polling loop...")
    
    # 2. Main Loop
    while True:
        try:
            logger.info("--- Starting Tick ---")
            
            # Parallel Data Fetching
            import concurrent.futures
            
            def fetch_kalshi_data():
                # Fetch Generic + BTC Daily + BTC 15m
                k_gen = kalshi_feed.fetch_events(limit=1000)
                k_btc_d = kalshi_feed.fetch_events(limit=100, series_ticker="KXBTCD")
                k_btc_15 = kalshi_feed.fetch_events(limit=100, series_ticker="KXBTC15M")
                
                all_kalshi = {e.event_id: e for e in k_gen + k_btc_d + k_btc_15}.values()
                events = list(all_kalshi)
                k_15_count = len([e for e in events if "KXBTC15M" in e.ticker])
                logger.info(f"Fetched {len(events)} Kalshi events (incl. {len(k_btc_d)} daily BTC, {k_15_count} 15m BTC).")
                return events

            def fetch_poly_data():
                poly_main = poly_feed.fetch_events(limit=500)
                # Fetch specifically the "15M" markets (Tag 102467)
                poly_15m = poly_feed.fetch_events(limit=100, tag_id=102467)
                
                all_poly = {e.event_id: e for e in poly_main + poly_15m}.values()
                events = list(all_poly)
                logger.info(f"Fetched {len(events)} Polymarket events (incl. {len(poly_15m)} 15m markets).")
                return events

            with concurrent.futures.ThreadPoolExecutor() as tp_executor:
                logger.info("Fetching Market Data in Parallel...")
                future_k = tp_executor.submit(fetch_kalshi_data)
                future_p = tp_executor.submit(fetch_poly_data)
                
                kalshi_events = future_k.result()
                p_events = future_p.result()
            
            # Match Categories
            # Optimization: Pre-filter by common terms to avoid O(N*M) full checks
            # 1100 * 600 = 660,000 checks. If specific logic is slow, this hangs.
            
            kalshi_btc = [e for e in kalshi_events if "Bitcoin" in e.title or "BTC" in e.title]
            poly_btc = [e for e in p_events if "Bitcoin" in e.title or "BTC" in e.title or "Up or Down" in e.title] # Polymarket 15m title often "BTC Up or Down..." or just "Up or Down"
            
            logger.info(f"Optimization: Checking {len(kalshi_btc)} Kalshi BTC events vs {len(poly_btc)} Poly BTC events.")
            
            matched_pairs = []
            for ke in kalshi_btc:
                for pe in poly_btc:
                    if matcher.are_equivalent(ke, pe):
                        matched_pairs.append((ke, pe))
            
            logger.info(f"Found {len(matched_pairs)} matched event pairs.")
            
            # Check for Arb
            for ke, pe in matched_pairs:
                logger.info(f"Analyzing Pair: {ke.ticker} <-> {pe.ticker}")
                
                # Hard Arb
                opp = detector.check_hard_arbitrage(ke, pe)
                if opp:
                    # NEW: Verify Orderbook Liquidity before "execution"
                    try:
                        logger.info(f"Verifying Liquidity for {opp.type}...")
                        
                        # Kalshi Check
                        k_ob = kalshi_feed.get_orderbook(ke.ticker)
                        # Poly Check (Naive token selection for now, just checking we can fetch)
                        # Need to pick identifying token. Using first available.
                        p_token = pe.metadata.get('clobTokenIds', [])[0] if pe.metadata and pe.metadata.get('clobTokenIds') else None
                        p_ob = poly_feed.get_orderbook(p_token) if p_token else {}
                        
                        k_depth = len(k_ob.get('yes') or []) + len(k_ob.get('no') or []) if k_ob else 0
                        p_depth = len(p_ob.get('bids') or []) + len(p_ob.get('asks') or []) if p_ob else 0
                        
                        if k_depth > 0 and p_depth > 0:
                            logger.info(f"Liquidity Check PASSED. Kalshi Depth: {k_depth}, Poly Depth: {p_depth}")
                            # Now execute
                            try:
                                executor.execute_strategy(opp)
                            except Exception as exec_err:
                                logger.error(f"Execution Error: {exec_err}")
                        else:
                            logger.warning(f"Liquidity Check FAILED. Orderbooks empty or fetch failed. K:{k_depth} P:{p_depth}")
                    except Exception as e:
                        logger.error(f"Liquidity verification error: {e}")
                    
                    continue # Execute one per pair max
                    
                # Prob Arb
                opp_prob = detector.check_probabilistic_arbitrage(ke, pe)
                if opp_prob:
                    # Same check for Prob Arb? Or skip for now. 
                    # User said "hazme una simulación" implying generally.
                    # Let's add simple check here too or just pass.
                    executor.execute_strategy(opp_prob)
            
            logger.info("Tick complete. Sleeping 1s...")
            time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
            break
        except Exception as e:
            logger.error(f"Runtime error: {e}")
            time.sleep(60) # Sleep on error too

    # Verify Risk Manager Interaction
    logger.info(f"End of run. Bankroll: ${risk.bankroll:.2f}")

if __name__ == "__main__":
    main()
