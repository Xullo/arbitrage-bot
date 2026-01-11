from dataclasses import dataclass
from typing import List

@dataclass
class TradeRecord:
    timestamp: float
    pnl: float
    strategy_type: str

class PerformanceAnalyzer:
    def __init__(self):
        self.trades: List[TradeRecord] = []

    def log_trade(self, pnl: float, strategy: str):
        import time
        self.trades.append(TradeRecord(time.time(), pnl, strategy))

    def get_summary(self):
        if not self.trades:
            return "No trades executed."
        
        total_pnl = sum(t.pnl for t in self.trades)
        wins = len([t for t in self.trades if t.pnl > 0])
        total = len(self.trades)
        win_rate = (wins / total) * 100 if total > 0 else 0
        
        return {
            "Total PnL": total_pnl,
            "Total Trades": total,
            "Win Rate": f"{win_rate:.1f}%"
        }
