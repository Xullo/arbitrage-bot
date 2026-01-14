from dataclasses import dataclass
from typing import Optional, Tuple
from market_data import MarketEvent
from logger import logger
import time

@dataclass
class ArbitrageOpportunity:
    type: str # 'HARD', 'PROB', 'LAG'
    event_kalshi: MarketEvent
    event_poly: MarketEvent
    profit_potential: float
    buy_side: str # 'YES_K_NO_P' or 'NO_K_YES_P'
    timestamp: Optional[float] = None

    # OPT #2: Pre-computed token IDs to avoid lookups in hot path
    poly_token_yes: Optional[str] = None
    poly_token_no: Optional[str] = None

class ArbitrageDetector:
    """
    Scans for arbitrage opportunities between matched events.
    """
    
    
    def __init__(self, fee_kalshi: float = 0.02, fee_poly: float = 0.0, min_profit: float = 0.01, db_manager = None):
        self.fee_kalshi = fee_kalshi # Simplified fee model
        self.fee_poly = fee_poly
        self.min_profit = min_profit
        self.db_manager = db_manager

        # OPT #17: Cache for arbitrage calculations (100ms TTL)
        self._arb_cache = {}  # key: (k_ticker, p_ticker, prices_tuple) -> (result, timestamp)
        self._cache_ttl_ms = 100  # 100ms TTL

    def check_hard_arbitrage(self, k_event: MarketEvent, p_event: MarketEvent, pair_id: int = None) -> Optional[ArbitrageOpportunity]:
        """
        Strategy 1: Hard Arbitrage.
        Target: Buy YES on A and NO on B (or vice versa) if sum(prices) < 1.0 - costs
        """
        # OPT #17: Check cache first (100ms TTL)
        # Create cache key from tickers and prices
        prices_tuple = (
            round(k_event.yes_price, 4),
            round(k_event.no_price, 4),
            round(p_event.yes_price, 4),
            round(p_event.no_price, 4)
        )
        cache_key = (k_event.ticker, p_event.ticker, prices_tuple)

        now_ms = time.time() * 1000
        if cache_key in self._arb_cache:
            cached_result, cached_time_ms = self._arb_cache[cache_key]
            age_ms = now_ms - cached_time_ms

            if age_ms < self._cache_ttl_ms:
                # Cache hit - return cached result
                return cached_result

        # OPT #16: Quick pre-filter to avoid expensive calculations
        # Check if arbitrage is even POSSIBLE before full calc
        min_cost_a = p_event.yes_price + k_event.no_price
        min_cost_b = p_event.no_price + k_event.yes_price
        min_cost = min(min_cost_a, min_cost_b)

        # Conservative estimate: needs at least 2% margin for fees + profit
        if min_cost > 0.98:
            # No room for profit after fees - skip expensive calculation
            # Cache negative result
            self._arb_cache[cache_key] = (None, now_ms)
            return None

        # Fees
        # Poly: Fixed per unit (from config)
        # Kalshi: % of value (from config)
        FEE_POLY = self.fee_poly
        FEE_KALSHI_RATE = self.fee_kalshi

        # Scenario A: Poly YES + Kalshi NO
        # We buy YES on Poly and NO on Kalshi.
        # Note: k_event.no_price is the cost to buy NO? 
        # MarketEvent definition: no_price = 1.0 - yes_price. 
        # Make sure this reflects the ASK price for NO.
        # For simplicity, assuming yes_price and no_price are actionable Asks.
        
        cost_a_poly = p_event.yes_price
        cost_a_kalshi = k_event.no_price
        cost_a_total = cost_a_poly + cost_a_kalshi
        
        fee_a_poly = FEE_POLY
        fee_a_kalshi = cost_a_kalshi * FEE_KALSHI_RATE
        total_fees_a = fee_a_poly + fee_a_kalshi
        
        net_profit_a = 1.0 - cost_a_total - total_fees_a

        # Scenario B: Poly NO + Kalshi YES
        cost_b_poly = p_event.no_price
        cost_b_kalshi = k_event.yes_price
        cost_b_total = cost_b_poly + cost_b_kalshi
        
        fee_b_poly = FEE_POLY
        fee_b_kalshi = cost_b_kalshi * FEE_KALSHI_RATE
        total_fees_b = fee_b_poly + fee_b_kalshi
        
        net_profit_b = 1.0 - cost_b_total - total_fees_b
        
        # Determine Best
        if net_profit_a > net_profit_b:
            best_side = 'A'
            best_profit = net_profit_a
            gross_cost = cost_a_total
            # Log Details for A
            # PolyMarket: Cost {cost_a_poly} | P_YES {p_event.yes_price} + K_NO {k_event.no_price}
            # Kalshi: ... wait, Cost should match?
            # User format: "PolyMarket: Cost 1.220 | P_YES 0.36 + K_NO 0.86" -> This line seems to sum P_YES + K_NO ? 
            # No, user says "PolyMarket: Cost...". This implies the cost IS the sum.
            # But the line below says "Kalshi: Cost...".
            # The user example:
            # PolyMarket: Cost 1.220 | P_YES 0.36 + K_NO 0.86  <-- This line describes Scenario A?
            # Kalshi: Cost 1.090 | P_NO 0.65 + K_YES 0.44      <-- This line describes Scenario B?
            # Ah, the label "PolyMarket" and "Kalshi" in the user example might be confusing or refer to the "Primary" market?
            # Actually, "P_YES... + K_NO" clearly mixes both. 
            # Let's interpret the user's log lines as:
            # Line 1: Scenario A (P_YES + K_NO)
            # Line 2: Scenario B (P_NO + K_YES)
            
            # Re-reading user request:
            # [INFO] [CrossArb] Analysis ...:
            # PolyMarket: Cost 1.220 | P_YES 0.36 + K_NO 0.86  <-- Likely meant "Scenario 1" or labeled by the Poly side?
            # Kalshi: Cost 1.090 | P_NO 0.65 + K_YES 0.44      <-- Likely meant "Scenario 2"
            
            # I will Label them "Scenario P_YES" and "Scenario P_NO" or just follow the user's potentially shorthand labels.
            # I'll use "Option A (P_YES/K_NO)" and "Option B (P_NO/K_YES)" for clarity, or map "PolyMarket" to the side where we buy something on Poly?
            # In Line 1, we buy P_YES. In Line 2, we buy P_NO.
            # So "PolyMarket" label -> We buy Poly YES?
            # And "Kalshi" label -> We buy Kalshi YES? (Line 2 has K_YES).
            # This makes sense. 
            
            # Let's generate the string.
            
            scen_a_str = f"PolyMarket (Buy Yes): Cost {cost_a_total:.3f} | P_YES {p_event.yes_price:.2f} + K_NO {k_event.no_price:.2f}"
            scen_b_str = f"Kalshi (Buy Yes):     Cost {cost_b_total:.3f} | P_NO {p_event.no_price:.2f} + K_YES {k_event.yes_price:.2f}"
            
            # The User example explicitly had "PolyMarket: ..." and "Kalshi: ...".
            # I will use that exact text if possible, assuming "PolyMarket" means P_YES direction and "Kalshi" means K_YES direction.
            
            # (Analysis logging moved to live logic below)
        
        msg = f"[CrossArb] Analysis {p_event.ticker}:\n"
        msg += f"PolyMarket: Cost {cost_a_total:.3f} | P_YES {p_event.yes_price:.2f} + K_NO {k_event.no_price:.2f}\n"
        msg += f"Kalshi:     Cost {cost_b_total:.3f} | P_NO {p_event.no_price:.2f} + K_YES {k_event.yes_price:.2f}\n"
        
        best_profit = max(net_profit_a, net_profit_b)
        is_a_best = (net_profit_a >= net_profit_b)
        
        best_lbl = "A (Poly)" if is_a_best else "B (Kalshi)"
        best_gross = (1.0 - cost_a_total) if is_a_best else (1.0 - cost_b_total)
        
        msg += f"Best: {best_lbl} (Gross {best_gross:.3f} | Net {best_profit:.3f} | Req {self.min_profit:.3f})"
        logger.info(msg)
        
        # Log to DB
        decision = "NO BUY"
        reason = f"Net Profit {best_profit:.3f} < {self.min_profit:.3f}"
        
        if best_profit > self.min_profit:
            decision = f"BUY {best_lbl}"
            reason = f"Net Profit {best_profit:.3f} > {self.min_profit:.3f}"
            
        if self.db_manager and pair_id:
             details = {
                 "fee_rate_poly": FEE_POLY,
                 "fee_rate_kalshi": FEE_KALSHI_RATE,
                 "fees_a": total_fees_a,
                 "fees_b": total_fees_b,
                 "best_side": best_lbl
             }
             self.db_manager.log_opportunity(
                 pair_id, 
                 k_event.yes_price, k_event.no_price, 
                 p_event.yes_price, p_event.no_price,
                 cost_a_total, cost_b_total, 
                 best_profit, decision, reason, details
             )

        if best_profit > self.min_profit:
            logger.info(f"[CrossArb] DECISION: {decision}")

            # OPT #2: Pre-compute Polymarket token IDs to avoid lookup in execution
            poly_token_yes, poly_token_no = self._get_poly_tokens(p_event)

            if is_a_best:
                 # A = P_YES + K_NO -> NO_K_YES_P
                 result = ArbitrageOpportunity(
                     'HARD', k_event, p_event, best_profit, 'NO_K_YES_P',
                     poly_token_yes=poly_token_yes,
                     poly_token_no=poly_token_no
                 )
            else:
                 # B = P_NO + K_YES -> YES_K_NO_P
                 result = ArbitrageOpportunity(
                     'HARD', k_event, p_event, best_profit, 'YES_K_NO_P',
                     poly_token_yes=poly_token_yes,
                     poly_token_no=poly_token_no
                 )

            # OPT #17: Cache positive result
            self._arb_cache[cache_key] = (result, now_ms)
            return result
        else:
            logger.info(f"[CrossArb] DECISION: {decision}")
            # OPT #17: Cache negative result
            self._arb_cache[cache_key] = (None, now_ms)
            return None

    def _get_poly_tokens(self, p_event: MarketEvent) -> Tuple[Optional[str], Optional[str]]:
        """
        OPT #2: Pre-compute YES and NO token IDs from Polymarket event.
        Returns (yes_token, no_token) tuple.
        """
        try:
            token_ids = p_event.metadata.get('clobTokenIds', []) if p_event.metadata else []
            if not token_ids or len(token_ids) < 2:
                logger.warning(f"Missing token IDs for {p_event.ticker}")
                return (None, None)

            # Try to use outcomes metadata to determine correct mapping
            outcomes = p_event.metadata.get('outcomes', []) if p_event.metadata else []
            if outcomes and len(outcomes) >= 2:
                yes_idx = None
                no_idx = None
                for i, outcome in enumerate(outcomes):
                    if outcome.lower() == 'yes':
                        yes_idx = i
                    elif outcome.lower() == 'no':
                        no_idx = i

                if yes_idx is not None and no_idx is not None:
                    return (token_ids[yes_idx], token_ids[no_idx])

            # Fallback: assume [0]=YES, [1]=NO (common convention)
            logger.debug(f"Using fallback token mapping for {p_event.ticker}")
            return (token_ids[0], token_ids[1])

        except Exception as e:
            logger.error(f"Error getting poly tokens: {e}")
            return (None, None)

    def check_probabilistic_arbitrage(self, k_event: MarketEvent, p_event: MarketEvent) -> Optional[ArbitrageOpportunity]:
        """
        Strategy 2: Probabilistic.
        Checks for large spread divergence.
        """
        # Implied probability often approx equals price
        prob_diff = abs(k_event.yes_price - p_event.yes_price)
        
        # If diff > threshold (e.g. 15%), it's an Arb signal
        if prob_diff > 0.15:
            # We buy the "cheaper" probability
            direction = 'YES_K_NO_P' if k_event.yes_price < p_event.yes_price else 'NO_K_YES_P'
            logger.info(f"PROB ARB FOUND: Diff {prob_diff:.2f}. Direction: {direction}")
            return ArbitrageOpportunity('PROB', k_event, p_event, prob_diff, direction)
            
        return None
