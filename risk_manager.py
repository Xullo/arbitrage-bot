from config_manager import config
from logger import logger
from datetime import datetime, date
import threading
import asyncio
import time

class RiskManager:
    """
    Enforces strict risk limits before any order calculation or execution.

    IMPORTANT: Thread-safe implementation with automatic daily reset.
    """

    def __init__(self, current_bankroll: float):
        # Thread safety
        self.lock = threading.Lock()

        # The current_bankroll parameter is a fallback only.
        # Real balance will be synced from API via sync_real_balance()
        self.bankroll = current_bankroll
        self.kill_switch_active = False
        self.shutdown = False  # For background task control

        # Load Risk State from DB
        from database_manager import DatabaseManager
        self.db = DatabaseManager()
        state = self.db.load_risk_state()

        # Inject Feed Reference for Real Checks
        self.feed = None

        self.daily_pnl = state.get("daily_pnl", 0.0)
        self.current_exposure = state.get("current_exposure", 0.0)

        # Track last reset date for automatic daily reset
        self.last_reset_date = datetime.now().date()

        # OPT #8: Track last balance sync time to skip unnecessary checks
        self.last_balance_sync_time = 0.0

        # FIX #1: REMOVED INCORRECT LINE
        # OLD (INCORRECT): self.bankroll += self.daily_pnl
        # REASON: current_bankroll is stale/hardcoded. Real balance comes from sync_real_balance()
        # The daily_pnl is for tracking only, not for adjusting the bankroll at init.
        # sync_real_balance() will set the correct balance from API.

    def set_feed(self, feed):
        self.feed = feed
        # Update Bankroll from API immediately if possible
        self.sync_real_balance()
        
    def sync_real_balance(self):
         """Synchronizes bankroll with real API balance. Fallback to current if sync fails."""
         if self.feed:
             try:
                 bal = self.feed.get_balance()
                 if bal is not None:
                     with self.lock:
                         logger.info(f"RiskManager: Synced Real Balance: ${bal:.2f}")
                         self.bankroll = bal
                         # OPT #8: Track sync time to enable skipping balance checks
                         self.last_balance_sync_time = time.time()
                 else:
                     logger.warning("Balance sync returned None, keeping current balance")
             except Exception as e:
                 logger.error(f"Failed to sync risk balance: {e}. Using cached balance: ${self.bankroll:.2f}")

    def get_max_trade_dollar_amount(self) -> float:
        """
        Returns the max allowed risk per trade in USD.
        This is for TOTAL cost (both legs combined), not per leg.
        With 10% limit and $10.99 balance = $1.10 max total trade.
        """
        calc_risk = self.bankroll * config.risk_config.max_risk_per_trade
        return calc_risk

    def check_daily_reset(self):
        """
        FIX #6: Automatic daily reset at midnight.
        Checks if date has changed and resets daily metrics.
        Call this at the start of any risk check.
        """
        today = datetime.now().date()
        if today > self.last_reset_date:
            with self.lock:
                logger.info(f"[DAILY RESET] New day detected. Previous PnL: ${self.daily_pnl:.2f}, Exposure: ${self.current_exposure:.2f}")
                self.daily_pnl = 0.0
                self.current_exposure = 0.0
                self.last_reset_date = today
                self.db.save_risk_state(0.0, 0.0)
                logger.info("[DAILY RESET] Metrics reset to zero for new trading day")

    def can_execute(self, trade_amount: float) -> bool:
        """
        FIX #5: Thread-safe risk checking.
        FIX #6: Automatic daily reset before check.
        """
        # Check for daily reset first
        self.check_daily_reset()

        with self.lock:
            if self.kill_switch_active:
                logger.error("RISK REJECT: Kill switch is active.")
                return False

            # 1. Check Max Risk Per Trade
            max_trade_size = self.bankroll * config.risk_config.max_risk_per_trade
            if trade_amount > max_trade_size:
                logger.warning(f"RISK REJECT: Trade size ${trade_amount:.2f} exceeds limit ${max_trade_size:.2f}")
                return False

            # 2. Check Daily Loss Limit
            max_daily_loss = self.bankroll * config.risk_config.max_daily_loss
            if self.daily_pnl < -max_daily_loss:
                logger.critical(f"RISK REJECT: Daily loss limit hit ({self.daily_pnl:.2f} < -{max_daily_loss:.2f})")
                self.trigger_kill_switch("Daily Loss Limit Hit")
                return False

            # 3. Check Net Exposure
            max_exposure = self.bankroll * config.risk_config.max_net_exposure
            if (self.current_exposure + trade_amount) > max_exposure:
                logger.warning(f"RISK REJECT: Max exposure limit reached (Current: ${self.current_exposure:.2f} + Trade: ${trade_amount:.2f} = ${self.current_exposure + trade_amount:.2f} > Limit: ${max_exposure:.2f})")
                return False

            return True

    def register_trade(self, amount: float):
        """
        FIX #5: Thread-safe trade registration.
        FIX #4: Now accepts total cost INCLUDING fees.
        """
        with self.lock:
            self.current_exposure += amount
            logger.info(f"[RISK] Trade registered: ${amount:.2f}. Total exposure: ${self.current_exposure:.2f}")
            self.db.save_risk_state(self.daily_pnl, self.current_exposure)

    def close_position(self, amount: float):
        """
        FIX #3: Reduce exposure when positions close (e.g., market settlement).
        Call this when a market resolves or position is unwound.
        """
        with self.lock:
            self.current_exposure = max(0, self.current_exposure - amount)
            logger.info(f"[RISK] Position closed: ${amount:.2f}. Remaining exposure: ${self.current_exposure:.2f}")
            self.db.save_risk_state(self.daily_pnl, self.current_exposure)

    def update_pnl(self, pnl: float):
        """FIX #5: Thread-safe PnL update."""
        with self.lock:
            self.daily_pnl += pnl
            self.bankroll += pnl
            logger.info(f"[RISK] PnL updated: {'+' if pnl >= 0 else ''}{pnl:.2f}. Daily PnL: ${self.daily_pnl:.2f}, Bankroll: ${self.bankroll:.2f}")
            self.db.save_risk_state(self.daily_pnl, self.current_exposure)

    def trigger_kill_switch(self, reason: str):
        """Emergency stop mechanism."""
        with self.lock:
            self.kill_switch_active = True
            logger.critical(f"[KILL SWITCH ACTIVATED] Reason: {reason}")

    async def start_background_sync(self):
        """
        FIX #2: Background balance synchronization.
        Syncs balance from API every 30 seconds to prevent drift.
        Run this as a background task from bot.py.
        """
        logger.info("[BACKGROUND SYNC] Starting balance sync task (every 30s)")
        while not self.shutdown:
            try:
                await asyncio.sleep(30)
                if not self.shutdown:
                    self.sync_real_balance()
            except asyncio.CancelledError:
                logger.info("[BACKGROUND SYNC] Task cancelled")
                break
            except Exception as e:
                logger.error(f"[BACKGROUND SYNC] Error: {e}")

    def stop(self):
        """Signal shutdown to background tasks."""
        self.shutdown = True
        logger.info("[RISK MANAGER] Shutdown signal sent")
