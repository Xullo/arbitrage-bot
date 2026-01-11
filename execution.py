from config_manager import config
from risk_manager import RiskManager
from simulator import Simulator
from logger import logger
from arbitrage_engine import ArbitrageOpportunity

class ExecutionCoordinator:
    """
    Routes orders to Simulator or Real Exchange APIs based on configuration.
    """
    
    def __init__(self, risk_manager: RiskManager):
        self.risk = risk_manager
        self.simulator = Simulator()
        
    def execute_strategy(self, opp: ArbitrageOpportunity):
        # 1. Check Risk
        # For simplicity, assuming fixed bet size of $100 for now
        trade_size = 100.0 
        
        if not self.risk.can_execute(trade_size):
            return

        logger.info(f"Attempting execution for {opp.type} Arb...")

        if config.is_simulation():
            self._execute_sim(opp, trade_size)
        else:
            self._execute_real(opp, trade_size)

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
        else:
            logger.error("Execution FAILED in SIM (Leg failure).")
            # In real life, we'd need to unwind the successful leg here.

    def _execute_real(self, opp: ArbitrageOpportunity, size: float):
        logger.critical("REAL TRADING NOT YET IMPLEMENTED. SAFETY BLOCK.")
        # Raise fatal error or safety stop
