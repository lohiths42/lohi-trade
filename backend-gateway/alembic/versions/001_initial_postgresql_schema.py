"""Initial PostgreSQL schema for LOHI-TRADE platform expansion.

Creates all new tables for multi-user support, verification, fund management,
stock universe, watchlists, screener, broker connections, chatbot, and API logging.
Adds user_id column to existing migrated tables. Enables Row-Level Security.

Revision ID: 001
Revises: None
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    # Users & Authentication
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email VARCHAR(255) UNIQUE NOT NULL,
        phone VARCHAR(15),
        name VARCHAR(255) NOT NULL,
        password_hash VARCHAR(255),
        role VARCHAR(20) NOT NULL DEFAULT 'TRADER',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        is_onboarded BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE social_logins (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        provider VARCHAR(20) NOT NULL,
        provider_id VARCHAR(255) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(provider, provider_id)
    );
    """)

    op.execute("""
    CREATE TABLE refresh_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        token_hash VARCHAR(255) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Verification & Compliance
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE pan_verifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        pan_encrypted BYTEA NOT NULL,
        pan_masked VARCHAR(12) NOT NULL,
        holder_name VARCHAR(255),
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        rejection_reason TEXT,
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE kyc_verifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        full_name VARCHAR(255) NOT NULL,
        date_of_birth DATE NOT NULL,
        address TEXT NOT NULL,
        aadhaar_encrypted BYTEA,
        document_type VARCHAR(50) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED',
        rejection_reason TEXT,
        verification_ref VARCHAR(255),
        document_expiry_at TIMESTAMPTZ,
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE dmat_accounts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        account_number_encrypted BYTEA NOT NULL,
        depository VARCHAR(10) NOT NULL,
        dp_name VARCHAR(255),
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        linked_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE bank_accounts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        account_number_encrypted BYTEA NOT NULL,
        ifsc_code VARCHAR(11) NOT NULL,
        bank_name VARCHAR(255) NOT NULL,
        account_holder_name VARCHAR(255) NOT NULL,
        account_type VARCHAR(20) NOT NULL,
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Fund Management
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE fund_transactions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        type VARCHAR(20) NOT NULL,
        amount DECIMAL(15,2) NOT NULL,
        payment_method VARCHAR(20),
        bank_account_id UUID REFERENCES bank_accounts(id),
        transaction_ref VARCHAR(255),
        status VARCHAR(20) NOT NULL DEFAULT 'INITIATED',
        failure_reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ
    );
    """)

    op.execute("""
    CREATE TABLE trading_balances (
        user_id UUID PRIMARY KEY REFERENCES users(id),
        available_balance DECIMAL(15,2) NOT NULL DEFAULT 0,
        blocked_margin DECIMAL(15,2) NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Stock Universe
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE securities (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(30) NOT NULL,
        isin VARCHAR(20) UNIQUE NOT NULL,
        company_name VARCHAR(255) NOT NULL,
        exchange VARCHAR(10) NOT NULL,
        sector VARCHAR(100),
        industry VARCHAR(100),
        market_cap_category VARCHAR(20),
        listing_date DATE,
        face_value DECIMAL(10,2),
        status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("CREATE INDEX idx_securities_symbol ON securities(symbol);")
    op.execute("CREATE INDEX idx_securities_sector ON securities(sector);")
    op.execute("CREATE INDEX idx_securities_status ON securities(status);")
    op.execute("""
    CREATE INDEX idx_securities_search ON securities USING gin(
        to_tsvector('english', symbol || ' ' || company_name || ' ' || isin)
    );
    """)

    op.execute("""
    CREATE TABLE security_fundamentals (
        security_id INT PRIMARY KEY REFERENCES securities(id),
        pe_ratio DECIMAL(10,2),
        pb_ratio DECIMAL(10,2),
        market_cap DECIMAL(20,2),
        dividend_yield DECIMAL(6,3),
        eps DECIMAL(10,2),
        roe DECIMAL(6,2),
        debt_to_equity DECIMAL(10,2),
        revenue_growth_1y DECIMAL(6,2),
        revenue_growth_3y DECIMAL(6,2),
        profit_growth_1y DECIMAL(6,2),
        profit_growth_3y DECIMAL(6,2),
        return_1y DECIMAL(8,2),
        cagr_3y DECIMAL(8,2),
        cagr_5y DECIMAL(8,2),
        high_52w DECIMAL(12,2),
        low_52w DECIMAL(12,2),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE security_technicals (
        security_id INT PRIMARY KEY REFERENCES securities(id),
        rsi_14 DECIMAL(6,2),
        sma_50 DECIMAL(12,2),
        sma_200 DECIMAL(12,2),
        avg_volume_20d BIGINT,
        price_change_1d DECIMAL(8,4),
        price_change_1w DECIMAL(8,4),
        price_change_1m DECIMAL(8,4),
        price_change_3m DECIMAL(8,4),
        price_change_6m DECIMAL(8,4),
        price_change_1y DECIMAL(8,4),
        price_change_3y DECIMAL(8,4),
        price_change_5y DECIMAL(8,4),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Watchlists
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE watchlists (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        name VARCHAR(100) NOT NULL,
        is_prebuilt BOOLEAN NOT NULL DEFAULT FALSE,
        sort_order INT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE watchlist_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        watchlist_id UUID NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
        security_id INT NOT NULL REFERENCES securities(id),
        sort_order INT NOT NULL DEFAULT 0,
        added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(watchlist_id, security_id)
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Screener Presets
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE screener_presets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        name VARCHAR(100) NOT NULL,
        filters JSONB NOT NULL,
        is_prebuilt BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Corporate Actions
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE corporate_actions (
        id SERIAL PRIMARY KEY,
        security_id INT NOT NULL REFERENCES securities(id),
        action_type VARCHAR(30) NOT NULL,
        ex_date DATE,
        record_date DATE,
        details JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Broker Connections (per-user)
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE broker_connections (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        broker_name VARCHAR(30) NOT NULL,
        credentials_encrypted BYTEA NOT NULL,
        access_token_encrypted BYTEA,
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        is_backup BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(20) NOT NULL DEFAULT 'DISCONNECTED',
        last_connected_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Chatbot
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE chatbot_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        messages JSONB NOT NULL DEFAULT '[]',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # ═══════════════════════════════════════════════════════════════
    # Existing tables (migrated from SQLite, now with user_id)
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE trades (
        id SERIAL PRIMARY KEY,
        trade_id TEXT UNIQUE NOT NULL,
        user_id UUID NOT NULL REFERENCES users(id),
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        strategy TEXT NOT NULL,
        entry_price DOUBLE PRECISION NOT NULL,
        exit_price DOUBLE PRECISION,
        quantity INTEGER NOT NULL,
        entry_time TIMESTAMPTZ NOT NULL,
        exit_time TIMESTAMPTZ,
        realized_pnl DOUBLE PRECISION,
        stop_loss DOUBLE PRECISION NOT NULL,
        target DOUBLE PRECISION NOT NULL,
        exit_reason TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_trades_symbol ON trades(symbol);")
    op.execute("CREATE INDEX idx_trades_entry_time ON trades(entry_time);")
    op.execute("CREATE INDEX idx_trades_strategy ON trades(strategy);")
    op.execute("CREATE INDEX idx_trades_user_id ON trades(user_id);")

    op.execute("""
    CREATE TABLE orders (
        id SERIAL PRIMARY KEY,
        order_id TEXT UNIQUE NOT NULL,
        user_id UUID NOT NULL REFERENCES users(id),
        trade_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price DOUBLE PRECISION,
        trigger_price DOUBLE PRECISION,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        filled_qty INTEGER DEFAULT 0,
        filled_price DOUBLE PRECISION,
        rejection_reason TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_orders_status ON orders(status);")
    op.execute("CREATE INDEX idx_orders_created_at ON orders(created_at);")
    op.execute("CREATE INDEX idx_orders_symbol ON orders(symbol);")
    op.execute("CREATE INDEX idx_orders_user_id ON orders(user_id);")

    op.execute("""
    CREATE TABLE sentiment_log (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id),
        article_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        sentiment TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        raw_score DOUBLE PRECISION NOT NULL,
        boosted_score DOUBLE PRECISION NOT NULL,
        news_title TEXT NOT NULL,
        news_source TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_sentiment_ticker ON sentiment_log(ticker);")
    op.execute("CREATE INDEX idx_sentiment_created_at ON sentiment_log(created_at);")
    op.execute("CREATE INDEX idx_sentiment_ticker_time ON sentiment_log(ticker, created_at);")
    op.execute("CREATE INDEX idx_sentiment_user_id ON sentiment_log(user_id);")

    op.execute("""
    CREATE TABLE bias_log (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id),
        ticker TEXT NOT NULL,
        bias TEXT NOT NULL,
        score DOUBLE PRECISION NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        article_count INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_bias_ticker_time ON bias_log(ticker, created_at);")
    op.execute("CREATE INDEX idx_bias_ticker ON bias_log(ticker);")
    op.execute("CREATE INDEX idx_bias_user_id ON bias_log(user_id);")

    # news_articles: shared table, no user_id needed
    op.execute("""
    CREATE TABLE news_articles (
        id SERIAL PRIMARY KEY,
        article_id TEXT UNIQUE NOT NULL,
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        url TEXT NOT NULL,
        published_at TIMESTAMPTZ NOT NULL,
        fetched_at TIMESTAMPTZ NOT NULL,
        content_hash TEXT NOT NULL,
        sentiment TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_news_articles_article_id ON news_articles(article_id);")
    op.execute("CREATE INDEX idx_news_articles_source ON news_articles(source);")
    op.execute("CREATE INDEX idx_news_articles_created_at ON news_articles(created_at);")

    op.execute("""
    CREATE TABLE audit_log (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id),
        event_type TEXT NOT NULL,
        component TEXT NOT NULL,
        message TEXT NOT NULL,
        metadata TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_audit_event_type ON audit_log(event_type);")
    op.execute("CREATE INDEX idx_audit_created_at ON audit_log(created_at);")
    op.execute("CREATE INDEX idx_audit_component ON audit_log(component);")
    op.execute("CREATE INDEX idx_audit_user_id ON audit_log(user_id);")

    op.execute("""
    CREATE TABLE ml_training_samples (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id),
        symbol TEXT NOT NULL,
        signal_id TEXT,
        features BYTEA NOT NULL,
        label DOUBLE PRECISION NOT NULL,
        side TEXT NOT NULL,
        entry_price DOUBLE PRECISION NOT NULL,
        exit_price DOUBLE PRECISION NOT NULL,
        atr_at_entry DOUBLE PRECISION NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_ml_samples_symbol ON ml_training_samples(symbol);")
    op.execute("CREATE INDEX idx_ml_samples_created_at ON ml_training_samples(created_at);")
    op.execute("CREATE INDEX idx_ml_samples_user_id ON ml_training_samples(user_id);")

    # ml_model_metrics: shared table, no user_id needed
    op.execute("""
    CREATE TABLE ml_model_metrics (
        id SERIAL PRIMARY KEY,
        model_type TEXT NOT NULL,
        accuracy DOUBLE PRECISION NOT NULL,
        precision_score DOUBLE PRECISION NOT NULL,
        recall DOUBLE PRECISION NOT NULL,
        f1_score DOUBLE PRECISION NOT NULL,
        sample_count INTEGER NOT NULL,
        top_features TEXT,
        trained_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_ml_metrics_model_type ON ml_model_metrics(model_type);")
    op.execute("CREATE INDEX idx_ml_metrics_trained_at ON ml_model_metrics(trained_at);")

    op.execute("""
    CREATE TABLE ml_predictions (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id),
        signal_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        probability DOUBLE PRECISION NOT NULL,
        predicted_class INTEGER NOT NULL,
        threshold DOUBLE PRECISION NOT NULL,
        approved INTEGER NOT NULL,
        market_regime TEXT,
        regime_confidence DOUBLE PRECISION,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_ml_predictions_symbol ON ml_predictions(symbol);")
    op.execute("CREATE INDEX idx_ml_predictions_created_at ON ml_predictions(created_at);")
    op.execute("CREATE INDEX idx_ml_predictions_user_id ON ml_predictions(user_id);")

    # ═══════════════════════════════════════════════════════════════
    # API Rate Limiting Log
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
    CREATE TABLE api_request_log (
        id BIGSERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        endpoint VARCHAR(255) NOT NULL,
        method VARCHAR(10) NOT NULL,
        status_code INT NOT NULL,
        response_time_ms INT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_api_log_user_time ON api_request_log(user_id, created_at);")

    # ═══════════════════════════════════════════════════════════════
    # Row-Level Security (RLS) Policies
    # ═══════════════════════════════════════════════════════════════
    _rls_tables = [
        "trades",
        "orders",
        "sentiment_log",
        "bias_log",
        "audit_log",
        "ml_training_samples",
        "ml_predictions",
        "social_logins",
        "refresh_tokens",
        "pan_verifications",
        "kyc_verifications",
        "dmat_accounts",
        "bank_accounts",
        "fund_transactions",
        "broker_connections",
        "chatbot_sessions",
    ]
    for table in _rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY {table}_user_isolation ON {table} "
            f"USING (user_id = current_setting('app.current_user_id')::UUID);"
        )

    # watchlists: nullable user_id — NULL rows (pre-built) visible to all
    op.execute("ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY watchlists_user_isolation ON watchlists "
        "USING (user_id IS NULL OR user_id = current_setting('app.current_user_id')::UUID);"
    )

    # screener_presets: nullable user_id — NULL rows (pre-built) visible to all
    op.execute("ALTER TABLE screener_presets ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY screener_presets_user_isolation ON screener_presets "
        "USING (user_id IS NULL OR user_id = current_setting('app.current_user_id')::UUID);"
    )

    # trading_balances: keyed by user_id
    op.execute("ALTER TABLE trading_balances ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY trading_balances_user_isolation ON trading_balances "
        "USING (user_id = current_setting('app.current_user_id')::UUID);"
    )

    # api_request_log: user-scoped
    op.execute("ALTER TABLE api_request_log ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY api_request_log_user_isolation ON api_request_log "
        "USING (user_id = current_setting('app.current_user_id')::UUID);"
    )


def downgrade() -> None:
    # Drop RLS policies and tables in reverse dependency order
    _rls_tables = [
        "api_request_log",
        "trading_balances",
        "screener_presets",
        "watchlists",
        "chatbot_sessions",
        "broker_connections",
        "ml_predictions",
        "ml_training_samples",
        "audit_log",
        "bias_log",
        "sentiment_log",
        "fund_transactions",
        "bank_accounts",
        "dmat_accounts",
        "kyc_verifications",
        "pan_verifications",
        "refresh_tokens",
        "social_logins",
        "trades",
        "orders",
    ]
    for table in _rls_tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_user_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS watchlists_user_isolation ON watchlists;")
    op.execute("DROP POLICY IF EXISTS screener_presets_user_isolation ON screener_presets;")
    op.execute("DROP POLICY IF EXISTS trading_balances_user_isolation ON trading_balances;")
    op.execute("DROP POLICY IF EXISTS api_request_log_user_isolation ON api_request_log;")

    # Drop tables in reverse dependency order
    _tables = [
        "api_request_log",
        "chatbot_sessions",
        "broker_connections",
        "corporate_actions",
        "screener_presets",
        "watchlist_items",
        "watchlists",
        "security_technicals",
        "security_fundamentals",
        "securities",
        "ml_predictions",
        "ml_model_metrics",
        "ml_training_samples",
        "news_articles",
        "audit_log",
        "bias_log",
        "sentiment_log",
        "orders",
        "trades",
        "trading_balances",
        "fund_transactions",
        "bank_accounts",
        "dmat_accounts",
        "kyc_verifications",
        "pan_verifications",
        "refresh_tokens",
        "social_logins",
        "users",
    ]
    for table in _tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
