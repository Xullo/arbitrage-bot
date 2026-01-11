from dataclasses import dataclass
from typing import Optional, Tuple
from market_data import MarketEvent
from logger import logger

@dataclass
class ArbitrageOpportunity:
    type: str # 'HARD', 'PROB', 'LAG'
    event_kalshi: MarketEvent
    event_poly: MarketEvent
    profit_potential: float
    buy_side: str # 'YES_K_NO_P' or 'NO_K_YES_P'
    timestamp: Optional[float] = None

class ArbitrageDetector:
    """
    Scans for arbitrage opportunities between matched events.
    """
    
    def __init__(self, fee_kalshi: float = 0.02, fee_poly: float = 0.0, min_profit: float = 0.01):
        self.fee_kalshi = fee_kalshi # Simplified fee model
        self.fee_poly = fee_poly
        self.min_profit = min_profit

    def check_hard_arbitrage(self, k_event: MarketEvent, p_event: MarketEvent) -> Optional[ArbitrageOpportunity]:
        """
        Strategy 1: Hard Arbitrage.
        Target: Buy YES on A and NO on B (or vice versa) if sum(prices) < 1.0 - costs
        """
        
        # Scenario 1: Buy YES on Kalshi, Buy NO on Polymarket
        # 'YES' outcome corresponds to Event happening. 'NO' on Poly means Event NOT happening.
        # Wait, if we buy YES on Kalshi (Outcome=True) and NO on Poly (Outcome=False), we cover both sides IF outcomes are binary.
        # Total Cost = Price(Yes_K) + Price(No_P)
        # Payout = 1.0 (Ignoring fees for a moment)
        
        cost_1 = k_event.yes_price + p_event.no_price
        
        # Scenario 2: Buy NO on Kalshi, Buy YES on Polymarket
        cost_2 = k_event.no_price + p_event.yes_price
        
        # Total fees approx
        total_fees = self.fee_kalshi + self.fee_poly
        
        if cost_1 < (1.0 - total_fees - self.min_profit):
            profit = 1.0 - cost_1 - total_fees
            logger.info(f"HARD ARB FOUND: Buy YES(K) + NO(P). Profit: {profit:.3f}")
            return ArbitrageOpportunity('HARD', k_event, p_event, profit, 'YES_K_NO_P')
            
        if cost_2 < (1.0 - total_fees - self.min_profit):
            profit = 1.0 - cost_2 - total_fees
            logger.info(f"HARD ARB FOUND: Buy NO(K) + YES(P). Profit: {profit:.3f}")
            return ArbitrageOpportunity('HARD', k_event, p_event, profit, 'NO_K_YES_P')
            
        return None

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
