import random
import time
from dataclasses import dataclass
from logger import logger

@dataclass
class ExecutionResult:
    success: bool
    filled_price: float
    fees: float
    message: str

class Simulator:
    """
    Simulates real-world execution conditions:
    - Random latency
    - Slippage probability
    - Partial fills (simplified)
    """
    
    def __init__(self, avg_latency_ms: int = 200, slippage_prob: float = 0.1):
        self.avg_latency_ms = avg_latency_ms
        self.slippage_prob = slippage_prob
        
    def execute_order(self, ticker: str, side: str, price: float, amount: float) -> ExecutionResult:
        logger.debug(f"[SIM] Executing {side} on {ticker} @ {price}")
        
        # 1. Simulate Latency
        latency = random.gauss(self.avg_latency_ms, 50) / 1000.0  # ms to seconds
        if latency < 0: latency = 0.01
        time.sleep(latency)
        
        # 2. Simulate Market Move / Failure (Slippage)
        if random.random() < self.slippage_prob:
            # Order fails or price moves against us
            logger.warning(f"[SIM] Slippage/Failure for {ticker}")
            return ExecutionResult(False, 0.0, 0.0, "Slippage/Market Moved")
            
        # 3. Simulate Fill
        # In this simplified model, we assume fill at asked price if no slippage
        # In a real backtester, we'd match against the next tick
        
        return ExecutionResult(True, price, 0.0, "Filled")

    def simulate_pnl_impact(self, profit_potential: float) -> float:
        # Occasionally reduce profit to simulate imperfect hedging
        if random.random() < 0.2:
            return profit_potential * 0.9
        return profit_potential
