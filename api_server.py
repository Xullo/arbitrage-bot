"""
Flask API Server for Arbitrage Bot Dashboard
Exposes real-time bot data via REST endpoints
"""

from flask import Flask, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime, timedelta
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for React dashboard

DB_PATH = os.path.join(os.path.dirname(__file__), 'arbitrage_bot.db')
LOG_PATH = os.path.join(os.path.dirname(__file__), f'bot_log_{datetime.now().strftime("%Y%m%d")}.log')


def get_db_connection():
    """Get SQLite database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current bot status"""
    try:
        # Read last 100 lines of log to determine status
        status = "unknown"
        last_update = None
        active_market = None
        monitored_pairs = 0

        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-100:]

                for line in reversed(lines):
                    # Check for active WebSocket
                    if 'WebSocket feeds active' in line:
                        status = "active"
                        break
                    if 'ACTIVE MARKET SET' in line:
                        parts = line.split('ACTIVE MARKET SET:')
                        if len(parts) > 1:
                            active_market = parts[1].strip()
                    if 'Found' in line and 'matched pairs' in line:
                        try:
                            parts = line.split('Found')[1].split('matched pairs')
                            monitored_pairs = int(parts[0].strip())
                        except:
                            pass

                # Get timestamp of last log entry
                if lines:
                    try:
                        last_line = lines[-1]
                        timestamp_str = last_line.split(' - ')[0]
                        last_update = timestamp_str
                    except:
                        pass

        # Get config
        config = {}
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)

        return jsonify({
            'status': status,
            'last_update': last_update,
            'active_market': active_market,
            'monitored_pairs': monitored_pairs,
            'simulation_mode': config.get('SIMULATION_MODE', True),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/markets', methods=['GET'])
def get_markets():
    """Get currently monitored markets"""
    try:
        markets = []

        # Parse log for market info
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-500:]

                for line in lines:
                    if 'MATCH FOUND' in line:
                        try:
                            # Extract market info
                            parts = line.split('MATCH FOUND')
                            if len(parts) > 1:
                                info = parts[1].strip()
                                # Parse format: "(BTC 15m heuristic): KXBTC... <-> btc-updown..."
                                if '<->' in info:
                                    market_parts = info.split('<->')
                                    kalshi = market_parts[0].split(':')[1].strip() if ':' in market_parts[0] else ''
                                    poly = market_parts[1].strip()
                                    asset = 'BTC' if 'BTC' in info else ('ETH' if 'ETH' in info else 'SOL')

                                    markets.append({
                                        'asset': asset,
                                        'kalshi_ticker': kalshi,
                                        'poly_ticker': poly,
                                        'status': 'monitoring'
                                    })
                        except:
                            pass

        # Remove duplicates
        unique_markets = []
        seen = set()
        for m in reversed(markets):
            key = m['kalshi_ticker']
            if key not in seen:
                seen.add(key)
                unique_markets.append(m)

        return jsonify({
            'markets': list(reversed(unique_markets))[:10],  # Last 10 unique markets
            'count': len(unique_markets)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/opportunities', methods=['GET'])
def get_opportunities():
    """Get detected arbitrage opportunities (including rejected ones)"""
    try:
        # Get config to check simulation mode
        config = {}
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)

        simulation_mode = config.get('SIMULATION_MODE', True)

        conn = get_db_connection()

        # Get recent opportunities from the opportunities table
        query = """
        SELECT
            o.id,
            o.timestamp,
            o.price_kalshi_yes,
            o.price_kalshi_no,
            o.price_poly_yes,
            o.price_poly_no,
            o.cost_a,
            o.cost_b,
            o.net_profit_best,
            o.decision,
            o.reason,
            o.details_json,
            mm.kalshi_ticker,
            mm.poly_ticker,
            mm.title
        FROM opportunities o
        LEFT JOIN matched_markets mm ON o.market_pair_id = mm.id
        ORDER BY o.timestamp DESC
        LIMIT 100
        """

        opportunities = conn.execute(query).fetchall()
        conn.close()

        result = []
        for opp in opportunities:
            # Parse details JSON
            details = {}
            if opp['details_json']:
                try:
                    details = json.loads(opp['details_json'])
                except:
                    pass

            # Calculate volumes (contracts = size from details)
            size = details.get('size', 0)
            kalshi_yes = float(opp['price_kalshi_yes']) if opp['price_kalshi_yes'] else 0
            kalshi_no = float(opp['price_kalshi_no']) if opp['price_kalshi_no'] else 0
            poly_yes = float(opp['price_poly_yes']) if opp['price_poly_yes'] else 0
            poly_no = float(opp['price_poly_no']) if opp['price_poly_no'] else 0

            # Calculate required volumes based on strategy
            buy_side = details.get('buy_side', 'N/A')
            if buy_side == 'YES_K_NO_P':
                kalshi_volume = size * kalshi_yes
                poly_volume = size * poly_no
            else:  # 'NO_K_YES_P'
                kalshi_volume = size * kalshi_no
                poly_volume = size * poly_yes

            total_volume = kalshi_volume + poly_volume

            result.append({
                'id': opp['id'],
                'timestamp': opp['timestamp'],
                'kalshi_ticker': opp['kalshi_ticker'] if opp['kalshi_ticker'] else details.get('kalshi_ticker', 'N/A'),
                'poly_ticker': opp['poly_ticker'] if opp['poly_ticker'] else details.get('poly_ticker', 'N/A'),
                'title': opp['title'],
                'profit': float(opp['net_profit_best']) if opp['net_profit_best'] else 0,
                'decision': opp['decision'],
                'reason': opp['reason'],
                'strategy': buy_side,
                'type': details.get('type', 'HARD'),
                'simulated': simulation_mode,  # Add simulated flag based on config
                'prices': {
                    'kalshi_yes': kalshi_yes,
                    'kalshi_no': kalshi_no,
                    'poly_yes': poly_yes,
                    'poly_no': poly_no
                },
                'volumes': {
                    'total': total_volume,
                    'kalshi': kalshi_volume,
                    'polymarket': poly_volume,
                    'contracts': size
                }
            })

        return jsonify({
            'opportunities': result,
            'count': len(result)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/trades', methods=['GET'])
def get_trades():
    """Get executed trades"""
    try:
        conn = get_db_connection()

        # Get recent trades
        query = """
        SELECT
            t.trade_id,
            t.contracts,
            t.k_cost,
            t.p_cost,
            t.total_cost,
            t.executed_at,
            mp.k_ticker,
            mp.p_ticker,
            ao.profit_potential,
            ao.buy_side
        FROM trades t
        LEFT JOIN market_pairs mp ON t.pair_id = mp.pair_id
        LEFT JOIN arbitrage_opportunities ao ON t.opp_id = ao.opp_id
        ORDER BY t.executed_at DESC
        LIMIT 50
        """

        trades = conn.execute(query).fetchall()
        conn.close()

        result = []
        for trade in trades:
            result.append({
                'id': trade['trade_id'],
                'contracts': float(trade['contracts']) if trade['contracts'] else 0,
                'kalshi_cost': float(trade['k_cost']) if trade['k_cost'] else 0,
                'poly_cost': float(trade['p_cost']) if trade['p_cost'] else 0,
                'total_cost': float(trade['total_cost']) if trade['total_cost'] else 0,
                'expected_profit': float(trade['profit_potential']) if trade['profit_potential'] else 0,
                'strategy': trade['buy_side'],
                'kalshi_ticker': trade['k_ticker'],
                'poly_ticker': trade['p_ticker'],
                'executed_at': trade['executed_at']
            })

        return jsonify({
            'trades': result,
            'count': len(result)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get bot statistics"""
    try:
        conn = get_db_connection()

        # Get trade statistics
        stats_query = """
        SELECT
            COUNT(*) as total_trades,
            SUM(total_cost) as total_invested,
            AVG(total_cost) as avg_trade_size
        FROM trades
        """
        stats = conn.execute(stats_query).fetchone()

        # Get opportunities count
        opp_query = """
        SELECT
            COUNT(*) as total_opportunities,
            AVG(profit_potential) as avg_profit_potential
        FROM arbitrage_opportunities
        WHERE detected_at > datetime('now', '-24 hours')
        """
        opp_stats = conn.execute(opp_query).fetchone()

        conn.close()

        return jsonify({
            'total_trades': stats['total_trades'] or 0,
            'total_invested': float(stats['total_invested']) if stats['total_invested'] else 0.0,
            'avg_trade_size': float(stats['avg_trade_size']) if stats['avg_trade_size'] else 0.0,
            'opportunities_24h': opp_stats['total_opportunities'] or 0,
            'avg_profit_potential': float(opp_stats['avg_profit_potential']) if opp_stats['avg_profit_potential'] else 0.0
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get recent log entries"""
    try:
        logs = []

        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-100:]

                for line in lines:
                    # Parse log line
                    try:
                        parts = line.split(' - ')
                        if len(parts) >= 4:
                            timestamp = parts[0]
                            level = parts[1].strip('[]')
                            module = parts[2]
                            message = ' - '.join(parts[3:]).strip()

                            # Only include INFO, WARNING, ERROR
                            if level in ['INFO', 'WARNING', 'ERROR']:
                                logs.append({
                                    'timestamp': timestamp,
                                    'level': level,
                                    'module': module,
                                    'message': message
                                })
                    except:
                        pass

        return jsonify({
            'logs': logs[-50:],  # Last 50 logs
            'count': len(logs)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/all-markets', methods=['GET'])
def get_all_markets():
    """Get ALL markets from both platforms for manual pairing"""
    try:
        from dotenv import load_dotenv
        from market_data import KalshiFeed, PolymarketFeed

        load_dotenv()

        # Initialize feeds
        kalshi = KalshiFeed(
            key=os.getenv('KALSHI_API_KEY'),
            secret=os.getenv('KALSHI_API_SECRET')
        )

        poly = PolymarketFeed(
            api_key=os.getenv('POLYMARKET_API_KEY'),
            private_key=os.getenv('POLYMARKET_PRIVATE_KEY')
        )

        # Fetch BTC markets from both platforms
        kalshi_btc = kalshi.fetch_events(series_ticker="KXBTC15M", status='active')
        poly_all = poly.fetch_events(tag_id=102467, status='active', validate_tokens=False)

        # Filter Polymarket for BTC only
        poly_btc = [m for m in poly_all if 'btc' in m.ticker.lower()]

        # Convert to JSON-serializable format
        kalshi_markets = []
        for m in kalshi_btc:
            kalshi_markets.append({
                'ticker': m.ticker,
                'title': m.title,
                'close_time': m.resolution_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
                'close_timestamp': int(m.resolution_time.timestamp()),
                'yes_price': m.yes_price,
                'no_price': m.no_price,
                'volume': m.volume
            })

        poly_markets = []
        for m in poly_btc:
            poly_markets.append({
                'ticker': m.ticker,
                'title': m.title,
                'close_time': m.resolution_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
                'close_timestamp': int(m.resolution_time.timestamp()),
                'yes_price': m.yes_price,
                'no_price': m.no_price,
                'volume': m.volume,
                'metadata': m.metadata
            })

        return jsonify({
            'kalshi': kalshi_markets,
            'polymarket': poly_markets,
            'kalshi_count': len(kalshi_markets),
            'poly_count': len(poly_markets),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting Arbitrage Bot API Server...")
    print("Dashboard will be available at http://localhost:5000")
    print("API endpoints:")
    print("   - GET /api/status")
    print("   - GET /api/markets")
    print("   - GET /api/opportunities")
    print("   - GET /api/trades")
    print("   - GET /api/stats")
    print("   - GET /api/logs")
    print("   - GET /api/all-markets  (NEW: Manual pairing)")
    app.run(debug=True, host='0.0.0.0', port=5000)
