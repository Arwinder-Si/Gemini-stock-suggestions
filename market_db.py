"""
market_db.py
-------------
SQLite persistent storage for the NSE trading system.
Stores global signals, screener history, and news features.
"""

import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "market_data.db")


def get_connection():
    """Returns a SQLite connection."""
    return sqlite3.connect(DB_PATH)


def init_db():
    """Initialize the database schema if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Global Signals Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_signals (
            date TEXT,
            signal_name TEXT,
            value REAL,
            change_pct REAL,
            fetched_at TEXT,
            PRIMARY KEY (date, signal_name)
        )
    """)

    # 2. Screener History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screener_history (
            date TEXT,
            stock TEXT,
            score INTEGER,
            vol_ratio REAL,
            rsi REAL,
            dist_ema20 REAL,
            sector TEXT,
            PRIMARY KEY (date, stock)
        )
    """)

    # 3. News History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_history (
            date TEXT,
            stock TEXT,
            sentiment_7d REAL,
            num_articles INTEGER,
            has_reg_risk INTEGER,
            top_headline TEXT,
            PRIMARY KEY (date, stock)
        )
    """)
    
    # 4. Gap Prediction Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gap_prediction (
            date TEXT PRIMARY KEY,
            prediction_pct REAL,
            bias TEXT,
            calculated_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_global_signals(df: pd.DataFrame):
    """Save global market signals DataFrame to SQLite."""
    if df.empty:
        return
        
    init_db()
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for signal_name, row in df.iterrows():
        try:
            conn.execute("""
                INSERT OR REPLACE INTO global_signals (date, signal_name, value, change_pct, fetched_at)
                VALUES (?, ?, ?, ?, ?)
            """, (today, signal_name, row['value'], row['change_pct'], now_ts))
        except Exception as e:
            print(f"Error saving {signal_name}: {e}")
            
    conn.commit()
    conn.close()


def save_gap_prediction(prediction_pct: float, bias: str):
    """Save the daily gap prediction."""
    init_db()
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT OR REPLACE INTO gap_prediction (date, prediction_pct, bias, calculated_at)
        VALUES (?, ?, ?, ?)
    """, (today, prediction_pct, bias, now_ts))
    
    conn.commit()
    conn.close()


def get_latest_gap_prediction() -> dict:
    """Fetch the most recent gap prediction."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, prediction_pct, bias, calculated_at 
        FROM gap_prediction 
        ORDER BY date DESC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "date": row[0],
            "prediction_pct": row[1],
            "bias": row[2],
            "calculated_at": row[3]
        }
    return None

def save_screener_results(csv_path: str):
    """Load screener_results.csv and save to SQLite."""
    if not os.path.exists(csv_path):
        return
        
    init_db()
    df = pd.read_csv(csv_path)
    if df.empty:
        return
        
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    for _, row in df.iterrows():
        try:
            conn.execute("""
                INSERT OR REPLACE INTO screener_history 
                (date, stock, score, vol_ratio, rsi, dist_ema20, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (today, row['Stock'], row['Score'], row['Vol_Ratio'], 
                  row['RSI'], row['Dist_EMA20'], row['Sector']))
        except Exception as e:
            print(f"Error saving screener history for {row['Stock']}: {e}")
            
    conn.commit()
    conn.close()


def save_news_results(csv_path: str):
    """Load news_features.csv and save to SQLite."""
    if not os.path.exists(csv_path):
        return
        
    init_db()
    df = pd.read_csv(csv_path)
    if df.empty:
        return
        
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    for _, row in df.iterrows():
        try:
            reg_risk = 1 if row.get('has_neg_reg_news_7d', False) else 0
            conn.execute("""
                INSERT OR REPLACE INTO news_history 
                (date, stock, sentiment_7d, num_articles, has_reg_risk, top_headline)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (today, row['symbol'], row['sentiment_7d'], 
                  row['num_articles_7d'], reg_risk, str(row.get('top_headline', ''))))
        except Exception as e:
            pass
            
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized Database at {DB_PATH}")
