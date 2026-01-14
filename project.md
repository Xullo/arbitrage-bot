
# Arbitrage Bot Project Documentation

## Project Overview
This project is a high-frequency arbitrage bot designed to identify and exploit price discrepancies between **Kalshi** and **Polymarket** outcomes. It currently focuses on **15-minute Bitcoin (BTC)** markets, known as "Price Up/Down" (Polymarket) or "BTC > X" (Kalshi).

The bot operates in a "Paper Trading" mode (simulation), fetching live data, matching equivalent markets between exchanges, calculating "Risk-Free" (Hard) arbitrage opportunities, and logging decisions to a local SQLite database.

## Architecture

```mermaid
graph TD
    A[Main Loop (main.py)] --> B{Data Feeds}
    B -->|Fetch| C[KalshiFeed (market_data.py)]
    B -->|Fetch| D[PolymarketFeed (market_data.py)]
    C --> E[EventMatcher (event_matcher.py)]
    D --> E
    E -->|Matched Pairs| F[ArbitrageDetector (arbitrage_engine.py)]
    F -->|Analysis| G[DatabaseManager (database_manager.py)]
    G -->|Async Log| H[(SQLite DB)]
    F -->|Opportunity| I[ExecutionCoordinator (execution.py)]
    I -->|Simulate Order| J[RiskManager (risk_manager.py)]
```

## Key Components

### 1. Orchestrator (`main.py`)
- **Role**: Entry point and main loop.
- **Functionality**:
    - Initializes all components.
    - runs a continuous `while True` loop.
    - Fetches market data in parallel threads (`ThreadPoolExecutor`).
    - Filters markets for specific terms (e.g., "BTC", "Bitcoin").
    - Invokes `EventMatcher` to pair markets.
    - Invokes `ArbitrageDetector` to analyze pairs.
    - Checks orderbook liquidity before execution.
    - Passively sleeps (1s) between ticks.

### 2. Market Data (`market_data.py`)
- **Role**: Data fetching and normalization.
- **Classes**:
    - `MarketEvent` (Dataclass): Standardized market object (price, volume, resolution time, source).
    - `KalshiFeed`: Authenticated API client for Kalshi. Handles `KXBTC` series logic.
    - `PolymarketFeed`: Gamma API client for Polymarket. Handles specialized outcome parsing.

### 3. Event Matcher (`event_matcher.py`)
- **Role**: Determining if two markets represent the exact same real-world event.
- **Logic**:
    - **Time Check**: Resolution time must be within 5-15 minutes (Includes logic to correct 15-min offset discrepancies).
    - **Asset Check**: Fuzzy string matching on titles ("Bitcoin", "BTC").
    - **Source Check**: Ensures the resolution source is compatible (e.g., "CoinDeck" vs "CoinGecko" - treated as equivalent if validated).

### 4. Arbitrage Engine (`arbitrage_engine.py`)
- **Role**: Mathematical core for Opportunity Detection.
- **Logic**:
    - **Hard Arbitrage**: `Cost(A) + Cost(B) < 1.0 - Fees`.
        - *Scenario A*: Buy Poly YES + Buy Kalshi NO.
        - *Scenario B*: Buy Poly NO + Buy Kalshi YES.
    - **Fee Structure**:
        - **Polymarket**: Fixed 0.001 per unit.
        - **Kalshi**: 1% (0.01) of trade value.
    - **Threshold**: Only signals if `Net Profit > min_profit` (default 0.005).

### 5. Database Manager (`database_manager.py`)
- **Role**: High-performance logging.
- **Features**:
    - **SQLite**: Stores data in `arbitrage_bot.db`.
    - **Asynchronous**: Uses a `Queue` and background `Thread` for writes to prevent blocking the main loop.
    - **Schema**:
        - `matched_markets`: Stores linked pairs (Tickers, Titles, and **Raw JSON** dumps for future debugging).
        - `opportunities`: Logs every single tick's analysis (Prices, Costs, Fees, Decision `BUY`/`NO BUY`, Reason).

### 6. Developer Tools (`dev_tools/`)
- Contains verification scripts essential for validating the logic:
    - `verify_week.py`: Historical consistency check (Last week's 15m outcomes).
    - `test_arb_logging.py`: Dry-run for log formats.
    - `test_database.py`: Schema validation.

## Data Workflow
1.  **Fetch**: Pull ~1000 events from Kalshi and ~500 from Polymarket.
2.  **Filter**: Narrow down to "BTC" related assets.
3.  **Match**: Compare time and title. Register new pairs in DB `matched_markets`.
4.  **Analyze**: Calculate implied probabilities and costs.
5.  **Log**: Save snapshot of prices and decision to DB `opportunities`.
6.  **Execute**: If profitable and liquid, `ExecutionCoordinator` simulates the trade (updating simulated bankroll).

## Execution Strategy

### Parallel Order Execution with Strict Validation (execution.py:215-316)

The bot executes orders on **both exchanges simultaneously** with **strict balance and orderbook validation**:

**Key Features**:
1. **Strict Orderbook Price Selection**: ONLY uses real orderbook prices (NO fallbacks)
   - Fetches real-time orderbook data before placing orders
   - Uses best ask prices where liquidity actually exists
   - **ABORTS** if orderbook unavailable or insufficient liquidity
   - Validates exact size availability at the price level

2. **Comprehensive Balance Verification**: Checks balances on BOTH exchanges before execution
   - Polymarket: Enforces $1.00 minimum order size
   - Kalshi: Verifies available balance via API
   - Combined: Ensures total cost is within available funds
   - **ABORTS** if insufficient balance on either exchange

3. **Parallel Execution**: Both Polymarket and Kalshi orders submit concurrently
   - Eliminates risk of one exchange filling while waiting for the other
   - Monitors both fills in parallel with 10-second timeout
   - Automatic unwind if only one side fills

**Code Flow**:
```python
# 1. Fetch Polymarket orderbook (STRICT - abort if unavailable)
poly_book = p_feed.get_orderbook(token_id)
if not poly_book or not poly_book['asks']:
    return False  # ABORT

best_ask = poly_book['asks'][0]
p_price = best_ask['price']
if best_ask['size'] < size:
    return False  # ABORT - insufficient liquidity

# 2. Fetch Kalshi orderbook (STRICT - abort if unavailable)
kalshi_book = k_feed.get_orderbook(ticker)
if not kalshi_book or not kalshi_book[side]:
    return False  # ABORT

best_level = kalshi_book[side][0]
k_price = best_level['price']
if best_level['size'] < size:
    return False  # ABORT - insufficient liquidity

# 3. Verify balances
poly_cost = size * p_price
kalshi_cost = size * k_price

if poly_cost < 1.0:  # Polymarket minimum
    return False  # ABORT

if kalshi_balance < kalshi_cost:
    return False  # ABORT

if total_cost > available_funds:
    return False  # ABORT

# 4. Submit both orders in parallel (only if all checks pass)
with ThreadPoolExecutor(max_workers=2) as executor:
    poly_future = executor.submit(p_feed.place_order, token_id, 'BUY', size, p_price)
    kalshi_future = executor.submit(k_feed.place_order, ticker, side, size, k_price)

# 5. Monitor fills and unwind if imbalanced
```

### Intelligent Unwind Mechanism (execution.py:375-644)

When orders don't fill completely on both sides, the bot automatically unwinds the imbalanced position using the **cheapest available option**:

**Unwind Strategy Evaluation**:
1. **Option 1: Cancel Order** (Cost: $0)
   - Checks if unfilled order is still LIVE/RESTING
   - Attempts to cancel before position is established
   - Most cost-effective if order hasn't filled yet

2. **Option 2: Hedge Position** (Cost: opposite_price * qty + fees)
   - Fetches current orderbook to get best available price
   - Buys opposite side to neutralize exposure
   - Example: If bought YES, sells NO to get flat
   - Chosen if cheaper than aggressive exit

3. **Option 3: Aggressive Exit** (Cost: high slippage + fees)
   - Places limit order at extreme price (0.01 or 0.99)
   - Essentially a market order for immediate execution
   - Fallback option if cancel fails and hedge too expensive

**Cost Comparison Logic**:
```python
# Example: Unwinding 10 units of Polymarket YES position
# Cancel failed, order already filled

# Hedge option: Sell NO @ $0.45 (from orderbook)
hedge_cost = (0.45 * 10) + (0.001 * 10) = $4.51

# Aggressive option: Sell YES @ $0.01
aggressive_cost = (0.01 * 10) + (0.001 * 10) = $0.11

# Choose aggressive (cheaper)
Bot places: SELL 10 YES @ $0.01
```

**Risk Mitigation**:
- Automatically detects partial fills in parallel execution
- Calculates exact imbalance between exchanges
- Executes unwind immediately to minimize market exposure
- Logs all evaluation steps for post-trade analysis

## Sticky Market Strategy (bot.py:179-323)

The bot implements a "focus on one market" approach to avoid constantly switching between opportunities:

**Strategy Overview**:
1. **Market Selection**: Bot subscribes to multiple matched pairs but only actively monitors ONE at a time
2. **Sticky Behavior**: Once a market is chosen as `active_market`, ALL updates for other markets are ignored
3. **Trade Execution**: When a trade completes on the active market, enter 1-minute cooldown
4. **Market Rotation**: After cooldown expires, bot picks a new active market from available pairs

**Market Filtering** (bot.py:105-140):
Markets are filtered out if they meet any of these criteria:
- **Last minute before closing**: < 60 seconds until market closes
  - Prevents trading in the final minute when volatility is extreme
  - Active market is automatically cleared if it enters last minute
- **Extreme probabilities**: YES/NO price >90% or <10% on either exchange
  - Prevents trading in illiquid or one-sided markets

**Cooldown System**:
```python
# After successful trade
self.market_cooldown_until = time.time() + 60  # 1 minute (suitable for 15min markets)
self.active_market = None  # Clear active market

# During cooldown, all orderbook updates are ignored
if time.time() < self.market_cooldown_until:
    return  # Skip processing
```

**Benefits**:
- **Focused execution**: Reduces noise from multiple simultaneous opportunities
- **Risk management**: Prevents overtrading by enforcing mandatory rest periods
- **Better fills**: By focusing on one market, can better understand price action
- **Reduced API calls**: Only processes updates for one market at a time

## Future Considerations (For AI Context)
- **Scaling**: The matcher is O(N*M). As market count grows, this needs optimization (hashing or pre-indexing).
- **Web Interface**: The SQLite DB is ready to serve a frontend dashboard.
- **Order Sizing**: Currently uses fixed size, could be optimized based on available liquidity.

## Utility Scripts

### Safe Wallet Verification

**check_safe_status.py**: Verifica balance on-chain y allowances para la Safe wallet
```bash
python check_safe_status.py
```

Verifica:
- USDC balance on-chain
- USDC allowance para CTF contract
- CTF approvals para exchanges (ERC1155)

**check_clob_balance.py**: Verifica balance y allowance via CLOB API
```bash
python check_clob_balance.py
```

Verifica:
- Balance disponible en CLOB de Polymarket
- Allowance reconocido por CLOB
- Diagnostica problemas de permisos o registro

**Resultado actual**:
- Balance on-chain: $11.00 ✓
- Allowance on-chain: UNLIMITED ✓
- CTF approvals: OK ✓
- **Balance en CLOB: $11.00 ✓**
- **Allowance en CLOB: $0.00 ✗** (PROBLEMA)

## Requirements
- Python 3.9+
- Libraries: `requests`, `cryptography` (for Kalshi RSA), `python-dotenv`.
- Environment Variables: `KALSHI_API_KEY`, `KALSHI_API_SECRET`.
