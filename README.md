# Kalshi-Polymarket Arbitrage Bot

Automated trading bot for detecting and executing arbitrage opportunities between Kalshi and Polymarket prediction markets.

## Overview

This bot monitors 15-minute cryptocurrency markets (BTC, ETH, SOL) on both exchanges and executes trades when price discrepancies guarantee risk-free profit.

### Key Features

- Real-time arbitrage detection via WebSockets
- Risk management with 10% per-trade limits (thread-safe)
- Gnosis Safe wallet support for Polymarket
- SQLite database for trade tracking
- Comprehensive logging system
- Simulation mode for testing
- Automatic balance sync every 30s
- Complete fee tracking in exposure
- Automatic daily metrics reset
- Exposure management with position closing
- Latency optimization (82-91% faster with async architecture)

### Performance

- **Latency**: ~1-2s execution time (reduced from ~11s, 85-95% improvement)
- **Architecture**: Fully async with HTTP parallelization
- **Caching**: Aggressive 500ms TTL for orderbook data
- **Connection Pooling**: Optimized HTTP connections

## Project Structure

```
├── main.py                 # Entry point
├── bot.py                  # Main orchestrator
├── market_data.py          # Kalshi and Polymarket feeds
├── event_matcher.py        # Event matching logic
├── arbitrage_engine.py     # Arbitrage detection
├── execution.py            # Order execution coordinator
├── risk_manager.py         # Risk limits management
├── websocket_feeds.py      # Real-time WebSocket connections
├── database_manager.py     # SQLite database management
├── config_manager.py       # Configuration management
├── start_bot.py            # Quick start script
├── verify_bot_config.py    # Configuration verification
├── verify_risk_limits.py   # Risk limits verification
├── dashboard.py            # Monitoring dashboard (WIP)
├── api_server.py           # API server for dashboard
├── CLAUDE.md               # Detailed technical documentation
├── OPTIMIZATIONS_FUTURE.md # Future optimization roadmap
├── RISK_LIMITS_UPDATE.md   # Risk limits documentation
└── dev_tools/              # Diagnostic and utility scripts (99 files)
```

## Quick Start

### Prerequisites

- Python 3.7+
- Kalshi API credentials
- Polymarket API credentials
- Gnosis Safe wallet on Polygon

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/arbitraje-cruzado.git
cd arbitraje-cruzado
```

2. Create a virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Create `.env` file with your credentials:
```env
# Kalshi
KALSHI_API_KEY=your_key_here
KALSHI_API_SECRET=path_to_kalshi.key
KALSHI_API_BASE=https://trading-api.kalshi.com/trade-api/v2

# Polymarket
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_API_URL=https://gamma-api.polymarket.com

# CLOB API (for trading)
POLYMARKET_API_KEY=your_key
POLYMARKET_API_SECRET=your_secret
POLYMARKET_PASSPHRASE=your_passphrase

# Builder API (for relayer and Safe)
POLYMARKET_BUILDER_API_KEY=your_key
POLYMARKET_BUILDER_API_SECRET=your_secret
POLYMARKET_BUILDER_PASSPHRASE=your_passphrase

# Wallets
POLYMARKET_PROXY_ADDRESS=0x...
POLYMARKET_SAFE_ADDRESS=0x...
```

4. Create `config.json`:
```json
{
  "SIMULATION_MODE": true,
  "max_risk_per_trade": 0.10,
  "max_daily_loss": 0.95,
  "max_net_exposure": 1.00,
  "fee_kalshi": 0.01,
  "fee_poly": 0.001
}
```

### Running the Bot

**Start in simulation mode:**
```bash
python start_bot.py
```

**Verify configuration:**
```bash
python verify_bot_config.py
python verify_risk_limits.py
```

**Run in production** (after testing):
```bash
# Set SIMULATION_MODE to false in config.json
python main.py
```

## Risk Management

### Current Limits

- **Max per trade**: 10% of total balance (both legs combined)
- **Max daily loss**: 95% of balance
- **Max net exposure**: 100% of balance
- **Cooldown**: 60 seconds between trades
- **Filters**: No trading in last minute, no extreme probabilities (>90% or <10%)

### Safety Features

- Thread-safe operations with locking
- Automatic balance synchronization every 30s
- Fee tracking included in exposure calculations
- Daily automatic reset of metrics at midnight
- Position closing to reduce exposure
- Kill switch for emergency stops

## Architecture

### Async Execution Flow

```
WebSocket Update (0ms)
    ↓
Arbitrage Detection (5-10ms)
    ↓
Execution (ASYNC) (150-400ms)
    ├─> Cache-first strategy
    ├─> Parallel HTTP fetch
    └─> Connection pooling
    ↓
Order Placement (PARALLEL) (~200ms)
    ↓
Fill Monitoring (Optimized) (~500ms-1s)
```

### Optimizations

- **Opt #3**: HTTP parallelization with aiohttp (200-400ms saved)
- **Opt #4**: Aggressive caching with 500ms TTL (150-250ms saved)
- **Opt #7**: Connection pooling (50-150ms saved)
- **Opt #8**: Smart balance checking (100-200ms saved)
- **Opt #13**: Async DB writes (50-100ms saved)
- **Opt #14**: Background market discovery (200-300ms saved)
- **Opt #16**: Quick pre-filter (3-5ms saved)
- **Opt #17**: Cached calculations (2-3ms saved)

See [OPTIMIZATIONS_FUTURE.md](OPTIMIZATIONS_FUTURE.md) for upcoming improvements.

## Documentation

- **[CLAUDE.md](CLAUDE.md)**: Comprehensive technical documentation
  - Detailed architecture explanation
  - All classes, methods, and data structures
  - Async execution flow
  - Optimization details
  - Complete changelog

- **[OPTIMIZATIONS_FUTURE.md](OPTIMIZATIONS_FUTURE.md)**: Future optimization roadmap
  - 4 additional optimizations planned
  - Potential to reduce latency to <1s

- **[RISK_LIMITS_UPDATE.md](RISK_LIMITS_UPDATE.md)**: Risk management guide
  - Limit calculations
  - Safety features
  - Exposure tracking

## Testing

The bot includes extensive diagnostic tools in [dev_tools/](dev_tools/):

- Market discovery and matching verification
- Balance and wallet status checks
- Order placement and fill monitoring
- Database inspection tools
- WebSocket connection testing

## Dashboard (Work in Progress)

A web dashboard for monitoring is under development:

```bash
# Start the API server
python api_server.py

# Start the dashboard (in separate terminal)
cd dashboard
npm install
npm run dev
```

## Version History

### v2.6.1 - 2026-01-13 (Market Discovery Fix)
- Fixed excessive market discovery polling
- Reduced API calls by 97%
- Single bot instance stays alive

### v2.6 - 2026-01-13 (Opt #13, #14, #16, #17)
- Async DB writes
- Background market discovery
- Quick pre-filter
- Cached calculations
- Total latency: 0.6-1.6s

### v2.5 - 2026-01-13 (Async Architecture)
- Full async/await implementation
- HTTP parallelization with aiohttp
- Aggressive caching
- Connection pooling
- Smart balance checking

### v2.0 - 2026-01-13 (Critical Fixes)
- Balance tracking fix
- Background balance sync
- Exposure management
- Fee tracking
- Thread safety
- Daily auto-reset

### v1.0 - 2026-01-12 (Initial Release)
- Basic arbitrage bot
- Kalshi and Polymarket support
- WebSocket feeds
- Risk management
- Gnosis Safe integration

## Contributing

This is a personal project. Feel free to fork and adapt for your own use.

## License

MIT License - See LICENSE file for details

## Disclaimer

**IMPORTANT**: This bot is for educational purposes only. Trading involves risk of loss. Use at your own risk. The authors are not responsible for any financial losses incurred from using this software.

Always test thoroughly in simulation mode before running with real funds.

## Contact

For questions or issues, please open an issue on GitHub.

---

**Last Updated**: 2026-01-14
**Version**: 2.6.1
**Status**: Production-Ready (with testing recommended)
