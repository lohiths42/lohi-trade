"""Seed the SQLite database with demo data for frontend testing."""

import sqlite3
import os
import random
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'lohi_trade.db')

SYMBOLS = ['RELIANCE', 'HDFCBANK', 'INFY', 'TCS', 'ICICIBANK', 'TATAMOTORS', 'SBIN', 'ADANIENT']
STRATEGIES = ['MEAN_REVERSION', 'TREND_FOLLOWING', 'ORB']
SIDES = ['BUY', 'SELL']
SENTIMENTS = ['BULLISH', 'BEARISH', 'NEUTRAL']
NEWS_SOURCES = ['MoneyControl', 'LiveMint', 'Economic Times', 'NSE', 'Reuters', 'Bloomberg']

def seed():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now()

    # --- Seed trades (5 open + 20 closed) ---
    print("Seeding trades...")
    for i in range(25):
        symbol = random.choice(SYMBOLS)
        side = random.choice(SIDES)
        strategy = random.choice(STRATEGIES)
        entry_price = round(random.uniform(500, 4000), 2)
        quantity = random.choice([10, 25, 50, 100])
        entry_time = (now - timedelta(hours=random.randint(1, 72))).isoformat()
        stop_loss = round(entry_price * (0.97 if side == 'BUY' else 1.03), 2)
        target = round(entry_price * (1.04 if side == 'BUY' else 0.96), 2)
        trade_id = f"T{1000+i}"

        if i < 5:
            # Open positions
            c.execute("""INSERT OR IGNORE INTO trades
                (trade_id, symbol, side, strategy, entry_price, exit_price, quantity,
                 entry_time, exit_time, realized_pnl, stop_loss, target, exit_reason)
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?, NULL)""",
                (trade_id, symbol, side, strategy, entry_price, quantity, entry_time, stop_loss, target))
        else:
            exit_price = round(entry_price + random.uniform(-100, 150), 2)
            pnl = round((exit_price - entry_price) * quantity * (1 if side == 'BUY' else -1), 2)
            exit_time = (datetime.fromisoformat(entry_time) + timedelta(minutes=random.randint(5, 180))).isoformat()
            exit_reason = random.choice(['target_hit', 'stop_loss', 'square_off', 'manual'])
            c.execute("""INSERT OR IGNORE INTO trades
                (trade_id, symbol, side, strategy, entry_price, exit_price, quantity,
                 entry_time, exit_time, realized_pnl, stop_loss, target, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, symbol, side, strategy, entry_price, exit_price, quantity,
                 entry_time, exit_time, pnl, stop_loss, target, exit_reason))

    # --- Seed orders ---
    print("Seeding orders...")
    statuses = ['FILLED', 'FILLED', 'FILLED', 'CANCELLED', 'PENDING', 'REJECTED']
    for i in range(30):
        symbol = random.choice(SYMBOLS)
        side = random.choice(SIDES)
        order_type = random.choice(['LIMIT', 'MARKET', 'SL', 'SL-M'])
        quantity = random.choice([10, 25, 50, 100])
        price = round(random.uniform(500, 4000), 2)
        status = random.choice(statuses)
        created_at = (now - timedelta(hours=random.randint(0, 48))).isoformat()
        order_id = f"ORD{2000+i}"
        trade_id = f"T{1000 + random.randint(0, 24)}"
        filled_qty = quantity if status == 'FILLED' else 0
        filled_price = price if status == 'FILLED' else None
        rejection = 'Insufficient margin' if status == 'REJECTED' else None
        c.execute("""INSERT OR IGNORE INTO orders
            (order_id, trade_id, symbol, side, order_type, quantity, price,
             trigger_price, status, broker_order_id, filled_qty, filled_price,
             rejection_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)""",
            (order_id, trade_id, symbol, side, order_type, quantity, price,
             status, filled_qty, filled_price, rejection, created_at, created_at))

    # --- Seed bias_log ---
    print("Seeding bias_log...")
    for symbol in SYMBOLS:
        bias = random.choice(SENTIMENTS)
        score = round(random.uniform(-1, 1), 3)
        confidence = round(random.uniform(0.4, 0.95), 3)
        article_count = random.randint(2, 15)
        created_at = (now - timedelta(minutes=random.randint(5, 120))).isoformat()
        c.execute("""INSERT INTO bias_log (ticker, bias, score, confidence, article_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (symbol, bias, score, confidence, article_count, created_at))

    # --- Seed sentiment_log (news) ---
    print("Seeding sentiment_log...")
    headlines = [
        "Q3 results beat street estimates, stock rallies",
        "Regulatory concerns weigh on sector outlook",
        "New partnership announced with global tech firm",
        "Analyst upgrades rating to outperform",
        "Supply chain disruptions may impact margins",
        "Board approves share buyback program",
        "FII selling pressure continues in banking sector",
        "Strong domestic demand drives revenue growth",
        "Management guidance cautious for next quarter",
        "Sector rotation favors defensive stocks",
        "RBI policy decision expected to boost sentiment",
        "Export orders surge on weak rupee",
        "Infrastructure push to benefit construction stocks",
    ]
    for i in range(20):
        ticker = random.choice(SYMBOLS)
        sentiment = random.choice(SENTIMENTS)
        confidence = round(random.uniform(0.5, 0.98), 3)
        raw_score = round(random.uniform(-1, 1), 3)
        boosted_score = round(raw_score * random.uniform(1.0, 1.5), 3)
        title = f"{ticker}: {random.choice(headlines)}"
        source = random.choice(NEWS_SOURCES)
        article_id = f"ART{3000+i}"
        created_at = (now - timedelta(minutes=random.randint(5, 300))).isoformat()
        c.execute("""INSERT INTO sentiment_log
            (article_id, ticker, sentiment, confidence, raw_score, boosted_score,
             news_title, news_source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (article_id, ticker, sentiment, confidence, raw_score, boosted_score, title, source, created_at))

    # --- Seed audit_log ---
    print("Seeding audit_log...")
    log_messages = [
        ("Signal generated: BUY RELIANCE @ 2450.00", "signal_pipeline", "INFO"),
        ("RMS check passed for HDFCBANK", "rms", "INFO"),
        ("Order placed: ORD2001 MARKET BUY INFY x50", "oms", "INFO"),
        ("Position opened: T1001 RELIANCE BUY", "soldier", "INFO"),
        ("Bias updated: TATAMOTORS -> BULLISH (0.72)", "commander", "INFO"),
        ("Kill switch status checked: inactive", "kill_switch", "DEBUG"),
        ("Redis stream consumer reconnected", "broker_manager", "WARNING"),
        ("Order rejected: insufficient margin for ADANIENT", "oms", "ERROR"),
        ("Volatility guard triggered for SBIN", "rms", "WARNING"),
        ("Sentiment analysis completed: 8 articles processed", "commander", "INFO"),
        ("WebSocket connection established to broker", "broker_manager", "INFO"),
        ("Daily P&L limit approaching: -1800 of -4000", "rms", "WARNING"),
        ("Square-off initiated for end of day", "soldier", "INFO"),
        ("Candle builder: 5min candle completed for TCS", "soldier", "DEBUG"),
        ("Indicator engine: RSI(14) = 72.3 for ICICIBANK", "soldier", "DEBUG"),
    ]
    for i in range(40):
        msg, component, event_type = random.choice(log_messages)
        created_at = (now - timedelta(minutes=random.randint(1, 480))).isoformat()
        c.execute("""INSERT INTO audit_log (event_type, component, message, metadata, created_at)
            VALUES (?, ?, ?, NULL, ?)""",
            (event_type, component, msg, created_at))

    conn.commit()
    conn.close()
    print("Demo data seeded successfully!")

if __name__ == '__main__':
    seed()
