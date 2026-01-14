import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

@dataclass
class RiskConfig:
    max_risk_per_trade: float = 0.90  # 90% of bankroll (Enabled for small account trading)
    max_daily_loss: float = 0.20      # 20% of bankroll
    max_net_exposure: float = 0.50    # 50% of bankroll

@dataclass
class FeeConfig:
    kalshi_maker_rate: float = 0.01   # 1%
    kalshi_taker_rate: float = 0.01   # 1%
    poly_flat_fee: float = 0.001      # Current requested logic
    poly_maker_rate: float = 0.0      # Future proofing
    poly_taker_rate: float = 0.0      # Future proofing

class ConfigManager:
    """
    Central configuration manager.
    Prioritizes SIMULATION MODE by default.
    """
    
    def __init__(self, config_path: str = "config.json"):
        if load_dotenv:
            load_dotenv() # Load .env if present
            
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load_config()
        
        # Enforce defaults if not present
        self.SIMULATION_MODE: bool = self._config.get("SIMULATION_MODE", True)
        self.KALSHI_API_KEY: Optional[str] = os.getenv("KALSHI_API_KEY")
        self.KALSHI_API_SECRET: Optional[str] = os.getenv("KALSHI_API_SECRET")
        self.POLYMARKET_API_KEY: Optional[str] = os.getenv("POLYMARKET_API_KEY")
        
        self.risk_config = RiskConfig(
            max_risk_per_trade=self._config.get("max_risk_per_trade", RiskConfig.max_risk_per_trade),
            max_daily_loss=self._config.get("max_daily_loss", RiskConfig.max_daily_loss),
            max_net_exposure=self._config.get("max_net_exposure", RiskConfig.max_net_exposure)
        )
        
        self.fee_config = FeeConfig(
            kalshi_maker_rate=self._config.get("fee_kalshi", FeeConfig.kalshi_maker_rate),
            poly_flat_fee=self._config.get("fee_poly", FeeConfig.poly_flat_fee)
        )

    def _load_config(self):
        """Loads config from file if exists, otherwise uses defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    self._config = json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}. Using defaults.")
        else:
            print("No config file found. Using defaults (Simulation Mode).")

    def is_simulation(self) -> bool:
        return self.SIMULATION_MODE

    def validate_keys(self) -> bool:
        """Checks if API keys are present (required even for some sim modes if fetching live data)."""
        if not self.KALSHI_API_KEY:
            print("WARNING: KALSHI_API_KEY not found in env.")
        if not self.POLYMARKET_API_KEY:
            print("WARNING: POLYMARKET_API_KEY not found in env.")
        return bool(self.KALSHI_API_KEY and self.POLYMARKET_API_KEY)

# Global instance
config = ConfigManager()
