from config_manager import config
from logger import logger

class RiskManager:
    """
    Enforces strict risk limits before any order calculation or execution.
    """
    
    def __init__(self, current_bankroll: float):
        self.bankroll = current_bankroll
        self.daily_pnl = 0.0
        self.current_exposure = 0.0
        self.kill_switch_active = False

    def can_execute(self, trade_amount: float) -> bool:
        if self.kill_switch_active:
            logger.error("RISK REJECT: Kill switch is active.")
            return False

        # 1. Check Max Risk Per Trade
        max_trade_size = self.bankroll * config.risk_config.max_risk_per_trade
        if trade_amount > max_trade_size:
            logger.warning(f"RISK REJECT: Trade size {trade_amount} exceeds limit {max_trade_size}")
            return False

        # 2. Check Daily Loss Limit
        max_daily_loss = self.bankroll * config.risk_config.max_daily_loss
        if self.daily_pnl < -max_daily_loss:
            logger.critical(f"RISK REJECT: Daily loss limit hit ({self.daily_pnl} < -{max_daily_loss})")
            return False

        # 3. Check Net Exposure
        if (self.current_exposure + trade_amount) > (self.bankroll * config.risk_config.max_net_exposure):
            logger.warning("RISK REJECT: Max exposure limit reached.")
            return False

        return True

    def register_trade(self, amount: float):
        self.current_exposure += amount

    def update_pnl(self, pnl: float):
        self.daily_pnl += pnl
        self.bankroll += pnl
        
    def trigger_kill_switch(self, reason: str):
        logger.critical(f"KILL SWITCH TRIGGERED: {reason}")
        self.kill_switch_active = True
