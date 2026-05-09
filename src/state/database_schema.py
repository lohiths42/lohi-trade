"""
Database schema definitions for LOHI-TRADE system.

This module contains SQL schema definitions for all tables used in the system:
- trades: Completed trades with entry/exit prices and P&L
- orders: All orders placed via broker API
- news_articles: Ingested news articles with metadata
- sentiment_log: News sentiment analysis results
- bias_log: Aggregated sentiment bias for tickers
- audit_log: System events and actions for compliance
"""

# SQLite schema with all required tables and indexes
SQLITE_SCHEMA = """
-- Trades table: Stores completed trades with P&L
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    strategy TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    entry_time TIMESTAMP NOT NULL,
    exit_time TIMESTAMP,
    realized_pnl REAL,
    stop_loss REAL NOT NULL,
    target REAL NOT NULL,
    exit_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);

-- Orders table: Stores all orders placed via broker API
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT UNIQUE NOT NULL,
    trade_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL,
    trigger_price REAL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    filled_qty INTEGER DEFAULT 0,
    filled_price REAL,
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);

-- Sentiment log table: Stores news sentiment analysis results
CREATE TABLE IF NOT EXISTS sentiment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    confidence REAL NOT NULL,
    raw_score REAL NOT NULL,
    boosted_score REAL NOT NULL,
    news_title TEXT NOT NULL,
    news_source TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sentiment_ticker ON sentiment_log(ticker);
CREATE INDEX IF NOT EXISTS idx_sentiment_created_at ON sentiment_log(created_at);
CREATE INDEX IF NOT EXISTS idx_sentiment_ticker_time ON sentiment_log(ticker, created_at);

-- Bias log table: Stores aggregated sentiment bias for tickers
CREATE TABLE IF NOT EXISTS bias_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    bias TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    article_count INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bias_ticker_time ON bias_log(ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_bias_ticker ON bias_log(ticker);

-- News articles table: Stores ingested news articles for later sentiment analysis
CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    content_hash TEXT NOT NULL,
    sentiment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_articles_article_id ON news_articles(article_id);
CREATE INDEX IF NOT EXISTS idx_news_articles_source ON news_articles(source);
CREATE INDEX IF NOT EXISTS idx_news_articles_created_at ON news_articles(created_at);

-- Audit log table: Stores system events and actions for compliance
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_component ON audit_log(component);

-- ML training samples: Stores feature vectors and trade outcome labels
CREATE TABLE IF NOT EXISTS ml_training_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    signal_id TEXT,
    features BLOB NOT NULL,
    label REAL NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    atr_at_entry REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ml_samples_symbol ON ml_training_samples(symbol);
CREATE INDEX IF NOT EXISTS idx_ml_samples_created_at ON ml_training_samples(created_at);

-- ML model metrics: Tracks model performance over time
CREATE TABLE IF NOT EXISTS ml_model_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_type TEXT NOT NULL,
    accuracy REAL NOT NULL,
    precision_score REAL NOT NULL,
    recall REAL NOT NULL,
    f1_score REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    top_features TEXT,
    trained_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ml_metrics_model_type ON ml_model_metrics(model_type);
CREATE INDEX IF NOT EXISTS idx_ml_metrics_trained_at ON ml_model_metrics(trained_at);

-- ML predictions log: Tracks ML filter decisions for analysis
CREATE TABLE IF NOT EXISTS ml_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    probability REAL NOT NULL,
    predicted_class INTEGER NOT NULL,
    threshold REAL NOT NULL,
    approved INTEGER NOT NULL,
    market_regime TEXT,
    regime_confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol ON ml_predictions(symbol);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_created_at ON ml_predictions(created_at);
"""


def get_sqlite_schema() -> str:
    """
    Returns the complete SQLite schema as a string.
    
    Returns:
        str: SQL statements to create all tables and indexes
    """
    return SQLITE_SCHEMA
