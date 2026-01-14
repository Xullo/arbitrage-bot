
import sqlite3
import json
from datetime import datetime
from typing import Optional
import logging
import threading
import queue
import dataclasses

logger = logging.getLogger("DatabaseManager")

class DatabaseManager:
    def __init__(self, db_path="arbitrage_bot.db"):
        self.db_path = db_path
        self._init_db()
        
        # Async Writing Setup
        self.write_queue = queue.Queue()
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        
        # In-Memory Cache for Pair IDs (K_Ticker, P_Ticker) -> ID
        self.pair_id_cache = {}

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Table: Matched Markets
            # Expanded Schema
            # Checking if table needs migration is complex in simple script.
            # Ideally, user should delete old DB or we handle "add column"
            # For simplicity, we create with new schema. if exists, we might error on missing cols if we don't migrate.
            # Let's try to add columns if they don't exist (Migration)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS matched_markets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kalshi_ticker TEXT NOT NULL,
                    poly_ticker TEXT NOT NULL,
                    title TEXT,
                    resolution_time DATETIME,
                    kalshi_opened_at DATETIME, 
                    kalshi_closed_at DATETIME, 
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    
                    -- New Columns
                    kalshi_id TEXT,
                    poly_id TEXT,
                    poly_title TEXT,
                    kalshi_raw_json TEXT,
                    poly_raw_json TEXT,
                    
                    UNIQUE(kalshi_ticker, poly_ticker)
                )
            """)
            
            # Migration check (naive)
            # Check if 'kalshi_id' exists
            cursor.execute("PRAGMA table_info(matched_markets)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'kalshi_id' not in columns:
                logger.info("Migrating DB: Adding new columns to matched_markets...")
                try:
                    cursor.execute("ALTER TABLE matched_markets ADD COLUMN kalshi_id TEXT")
                    cursor.execute("ALTER TABLE matched_markets ADD COLUMN poly_id TEXT")
                    cursor.execute("ALTER TABLE matched_markets ADD COLUMN poly_title TEXT")
                    cursor.execute("ALTER TABLE matched_markets ADD COLUMN kalshi_raw_json TEXT")
                    cursor.execute("ALTER TABLE matched_markets ADD COLUMN poly_raw_json TEXT")
                except Exception as e:
                    logger.warning(f"Migration partial error (continuing): {e}")

            # Table: Opportunities
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_pair_id INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    
                    price_kalshi_yes REAL,
                    price_kalshi_no REAL,
                    price_poly_yes REAL,
                    price_poly_no REAL,
                    
                    cost_a REAL,
                    cost_b REAL,
                    
                    net_profit_best REAL,
                    decision TEXT, 
                    reason TEXT,
                    
                    details_json TEXT,
                    
                    FOREIGN KEY(market_pair_id) REFERENCES matched_markets(id)
                )
            """)

            # Table: Daily Risk Metrics (SRE Fix)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_risk_metrics (
                    date DATE PRIMARY KEY,
                    daily_pnl REAL DEFAULT 0.0,
                    current_exposure REAL DEFAULT 0.0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully (Async Mode).")
        except Exception as e:
            logger.error(f"Database Initialization Failed: {e}")

    def _worker(self):
        """Background thread to process DB writes."""
        while self.running:
            try:
                task = self.write_queue.get(timeout=1) # check running every 1s
                event_type, data = task
                
                if event_type == 'close':
                    break
                
                self._perform_insert(event_type, data)
                self.write_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"DB Worker Error: {e}")

    def _perform_insert(self, event_type, data):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if event_type == 'opportunity':
                cursor.execute("""
                    INSERT INTO opportunities (
                        market_pair_id, price_kalshi_yes, price_kalshi_no, price_poly_yes, price_poly_no,
                        cost_a, cost_b, net_profit_best, decision, reason, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, data)
                
            elif event_type == 'insert_market':
                # Only used if we want async market insert. 
                # But we do sync cache check.
                # If we do async insert, we can't get ID easily for the cache update unless we re-query.
                # Currently register_market_pair is mostly SYNC for ID retrieval.
                pass
                
            conn.commit()
        except Exception as e:
            logger.error(f"Insert Failed ({event_type}): {e}")
        finally:
            if conn:
                conn.close()

    def register_market_pair(self, k_ticker: str, p_ticker: str, k_title: str, res_time: datetime,
                             k_id: str = None, p_id: str = None, p_title: str = None,
                             k_raw: dict = None, p_raw: dict = None) -> Optional[int]:
        """
        Registers a matched pair. 
        Synchronous check/insert ensures we get the ID immediately for the loop.
        Optimization: Uses In-Memory Cache to avoid DB Query on every tick.
        """
        cache_key = (k_ticker, p_ticker)
        if cache_key in self.pair_id_cache:
            return self.pair_id_cache[cache_key]
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check existence first
            cursor.execute("SELECT id FROM matched_markets WHERE kalshi_ticker = ? AND poly_ticker = ?", (k_ticker, p_ticker))
            row = cursor.fetchone()
            
            if row:
                pair_id = row[0]
                # Update Cache
                self.pair_id_cache[cache_key] = pair_id
                conn.close()
                return pair_id
            
            # Insert (Sync)
            # Serialize JSON
            k_json = json.dumps(k_raw, default=str) if k_raw else None
            p_json = json.dumps(p_raw, default=str) if p_raw else None
            
            cursor.execute("""
                INSERT INTO matched_markets (
                    kalshi_ticker, poly_ticker, title, resolution_time,
                    kalshi_id, poly_id, poly_title, kalshi_raw_json, poly_raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (k_ticker, p_ticker, k_title, res_time, k_id, p_id, p_title, k_json, p_json))
            
            pair_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            self.pair_id_cache[cache_key] = pair_id
            return pair_id
            
        except Exception as e:
            logger.error(f"Failed to register market pair: {e}")
            return None

    def log_opportunity(self, pair_id: int, k_yes: float, k_no: float, p_yes: float, p_no: float, 
                        cost_a: float, cost_b: float, profit: float, decision: str, reason: str, details: dict):
        """
        Asynchronous logging. Pushes to queue.
        """
        data = (
            pair_id, k_yes, k_no, p_yes, p_no,
            cost_a, cost_b, profit, decision, reason, json.dumps(details, default=str)
        )
        self.write_queue.put(('opportunity', data))

    def save_risk_state(self, daily_pnl: float, current_exposure: float):
        """
        Saves current risk metrics to DB (Upsert for today).
        """
        today = datetime.now().date().isoformat()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_risk_metrics (date, daily_pnl, current_exposure, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    daily_pnl=excluded.daily_pnl,
                    current_exposure=excluded.current_exposure,
                    updated_at=CURRENT_TIMESTAMP
            """, (today, daily_pnl, current_exposure))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save risk state: {e}")

    def load_risk_state(self) -> dict:
        """
        Loads today's risk metrics. Returns default dict if not found.
        """
        today = datetime.now().date().isoformat()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT daily_pnl, current_exposure FROM daily_risk_metrics WHERE date = ?", (today,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {"daily_pnl": row[0], "current_exposure": row[1]}
        except Exception as e:
            logger.error(f"Failed to load risk state: {e}")
        
        return {"daily_pnl": 0.0, "current_exposure": 0.0}

    def close(self):
        self.running = False
        self.write_queue.put(('close', None))
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2)
        logger.info("Database Worker Stopped.")
