"""Canada (TSX) market profile."""

from datetime import time

from ..market_profile import (
    BrokerInfo,
    Country,
    Exchange,
    MarketProfile,
    MarketSession,
    NewsSource,
    NumberFormat,
    SettlementCycle,
    TaxProfile,
    TaxRule,
)

CANADA_PROFILE = MarketProfile(
    country=Country.CANADA,
    country_name="Canada",
    currency="CAD",
    currency_symbol="C$",
    timezone="America/Toronto",
    number_format=NumberFormat.INTERNATIONAL,
    exchanges=[Exchange.TSX],
    primary_exchange=Exchange.TSX,
    benchmark_index_name="S&P/TSX Composite",
    benchmark_symbol="^GSPTSE",
    benchmark_redis_key="tsx_composite",
    sessions=MarketSession(
        pre_market_start=time(7, 0),
        pre_market_end=time(9, 30),
        market_open=time(9, 30),
        trading_start=time(9, 45),
        trading_end=time(15, 50),
        square_off_time=time(15, 55),
        market_close=time(16, 0),
        post_market_start=time(16, 0),
        post_market_end=time(17, 0),
    ),
    settlement_cycle=SettlementCycle.T1,
    tax_profile=TaxProfile(
        country=Country.CANADA,
        currency="CAD",
        transaction_taxes=[
            TaxRule(
                name="ECN Fees",
                rate_pct=0.0,
                applies_to="both",
                description="Electronic Communication Network fees (varies by broker)",
                is_flat_fee=True,
                flat_fee_amount=0.0035,  # per share typical
            ),
        ],
        capital_gains_short_term_pct=26.65,  # 50% inclusion rate at top bracket (53.3% * 0.5)
        capital_gains_long_term_pct=26.65,  # Same rate — Canada uses inclusion rate, not holding period
        short_term_threshold_days=0,  # Canada doesn't distinguish by holding period
        wash_sale_rule=True,  # Superficial loss rule
        wash_sale_window_days=30,  # 30 days before or after
        dividend_tax_pct=39.34,  # Top marginal rate on eligible dividends (with gross-up)
        last_updated="2025-01-01",
        source="manual",
        verified_by_user=True,
        disclaimer=(
            "Canada uses 50% capital gains inclusion rate (66.67% for gains over $250K). "
            "Superficial loss rule: 30 days before/after. TFSA accounts are tax-free. "
            "Consult a CPA for filing."
        ),
    ),
    available_brokers=[
        BrokerInfo(
            broker_id="interactive_brokers",
            name="Interactive Brokers (Canada)",
            description="Professional broker with TSX access. IIROC regulated.",
            api_type="rest",
            documentation_url="https://interactivebrokers.github.io/cpwebapi/",
            supports_paper_trading=True,
            supports_options=True,
            supports_futures=True,
            commission_model="per_share",
            credential_keys=["IB_ACCOUNT_ID", "IB_USERNAME", "IB_PASSWORD"],
            validation_patterns={
                "IB_ACCOUNT_ID": r"^[A-Z0-9]{4,}$",
                "IB_USERNAME": r"^.{3,}$",
                "IB_PASSWORD": r"^.{6,}$",
            },
        ),
        BrokerInfo(
            broker_id="questrade",
            name="Questrade",
            description="Canadian discount broker with REST API. Good for self-directed trading.",
            api_type="rest",
            documentation_url="https://www.questrade.com/api",
            supports_paper_trading=True,
            supports_options=True,
            supports_futures=False,
            commission_model="per_share",
            credential_keys=["QUESTRADE_REFRESH_TOKEN"],
            validation_patterns={
                "QUESTRADE_REFRESH_TOKEN": r"^.{20,}$",
            },
        ),
        BrokerInfo(
            broker_id="wealthsimple",
            name="Wealthsimple Trade",
            description="Commission-free Canadian stock trading.",
            api_type="rest",
            documentation_url="https://wealthsimple.com",
            supports_paper_trading=False,
            supports_options=True,
            supports_futures=False,
            commission_model="zero_commission",
            credential_keys=["WEALTHSIMPLE_EMAIL", "WEALTHSIMPLE_PASSWORD"],
            validation_patterns={
                "WEALTHSIMPLE_EMAIL": r"^.+@.+\..+$",
                "WEALTHSIMPLE_PASSWORD": r"^.{8,}$",
            },
        ),
    ],
    news_sources=[
        NewsSource(
            name="Globe and Mail",
            url="https://www.theglobeandmail.com/investing/rss/",
            category="general",
        ),
        NewsSource(name="BNN Bloomberg", url="https://www.bnnbloomberg.ca/rss", category="general"),
        NewsSource(name="TMX SEDAR+", url="https://www.sedarplus.ca", category="regulatory"),
    ],
    data_suffix=".TO",
    supports_short_selling=True,
    supports_options=True,
    supports_futures=True,
    supports_pre_market=True,
    supports_after_hours=True,
    min_lot_size=1,
    default_symbols=[
        "RY.TO",
        "TD.TO",
        "ENB.TO",
        "CNR.TO",
        "BMO.TO",
        "BN.TO",
        "CP.TO",
        "SHOP.TO",
        "BCE.TO",
        "TRI.TO",
        "SU.TO",
        "ATD.TO",
        "CSU.TO",
        "MFC.TO",
        "NTR.TO",
    ],
    regulator="CSA (Canadian Securities Administrators)",
    regulator_url="https://www.securities-administrators.ca",
    filing_sources=["sedar_plus"],
)
