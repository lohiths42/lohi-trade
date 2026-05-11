"""United Kingdom (LSE) market profile."""

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

UK_PROFILE = MarketProfile(
    country=Country.UNITED_KINGDOM,
    country_name="United Kingdom",
    currency="GBP",
    currency_symbol="£",
    timezone="Europe/London",
    number_format=NumberFormat.INTERNATIONAL,
    exchanges=[Exchange.LSE],
    primary_exchange=Exchange.LSE,
    benchmark_index_name="FTSE 100",
    benchmark_symbol="^FTSE",
    benchmark_redis_key="ftse100",
    sessions=MarketSession(
        pre_market_start=time(7, 0),
        pre_market_end=time(8, 0),
        market_open=time(8, 0),
        trading_start=time(8, 15),
        trading_end=time(16, 20),
        square_off_time=time(16, 25),
        market_close=time(16, 30),
        post_market_start=time(16, 30),
        post_market_end=time(17, 15),
    ),
    settlement_cycle=SettlementCycle.T2,
    tax_profile=TaxProfile(
        country=Country.UNITED_KINGDOM,
        currency="GBP",
        transaction_taxes=[
            TaxRule(
                name="Stamp Duty Reserve Tax (SDRT)",
                rate_pct=0.5,
                applies_to="buy",
                description="0.5% stamp duty on UK share purchases (electronic)",
            ),
            TaxRule(
                name="PTM Levy",
                rate_pct=0.0,
                applies_to="both",
                description="£1 flat fee on trades over £10,000 (Panel on Takeovers and Mergers)",
                is_flat_fee=True,
                flat_fee_amount=1.0,
                threshold=10000.0,
            ),
        ],
        capital_gains_short_term_pct=20.0,  # Higher rate
        capital_gains_long_term_pct=20.0,  # No distinction in UK
        short_term_threshold_days=0,  # UK doesn't distinguish by holding period
        wash_sale_rule=True,  # UK has "bed and breakfasting" rules
        wash_sale_window_days=30,
        dividend_tax_pct=33.75,  # Higher rate dividend tax
        last_updated="2025-04-06",
        source="manual",
        verified_by_user=True,
        disclaimer=(
            "UK CGT has annual exempt amount (£3,000 for 2024-25). "
            "ISA accounts are tax-free. Rates depend on income tax band. "
            "Consult a chartered accountant for filing."
        ),
    ),
    available_brokers=[
        BrokerInfo(
            broker_id="interactive_brokers",
            name="Interactive Brokers (UK)",
            description="Professional broker with comprehensive API. FCA regulated.",
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
            broker_id="ig",
            name="IG",
            description="UK's largest spread betting and CFD provider with REST API.",
            api_type="rest",
            documentation_url="https://labs.ig.com/rest-trading-api-reference",
            supports_paper_trading=True,
            supports_options=False,
            supports_futures=True,
            commission_model="per_trade",
            credential_keys=["IG_API_KEY", "IG_USERNAME", "IG_PASSWORD", "IG_ACCOUNT_ID"],
            validation_patterns={
                "IG_API_KEY": r"^[a-f0-9]{30,}$",
                "IG_USERNAME": r"^.{3,}$",
                "IG_PASSWORD": r"^.{6,}$",
            },
        ),
        BrokerInfo(
            broker_id="saxo",
            name="Saxo Markets",
            description="Multi-asset broker with OpenAPI. Good for equities and derivatives.",
            api_type="rest",
            documentation_url="https://www.developer.saxo/openapi/learn",
            supports_paper_trading=True,
            supports_options=True,
            supports_futures=True,
            commission_model="per_trade",
            credential_keys=["SAXO_APP_KEY", "SAXO_APP_SECRET", "SAXO_ACCOUNT_ID"],
            validation_patterns={
                "SAXO_APP_KEY": r"^.{10,}$",
                "SAXO_APP_SECRET": r"^.{10,}$",
            },
        ),
    ],
    news_sources=[
        NewsSource(name="Financial Times", url="https://www.ft.com/rss/home/uk", category="general"),
        NewsSource(name="Reuters UK", url="https://www.reutersagency.com/feed/", category="general"),
        NewsSource(name="London Stock Exchange RNS", url="https://www.londonstockexchange.com/news", category="regulatory"),
        NewsSource(name="Investegate", url="https://www.investegate.co.uk/Rss.aspx", category="regulatory"),
    ],
    data_suffix=".L",
    supports_short_selling=True,
    supports_options=True,
    supports_futures=True,
    supports_pre_market=True,
    supports_after_hours=False,
    min_lot_size=1,
    default_symbols=[
        "AZN.L", "SHEL.L", "HSBA.L", "ULVR.L", "BP.L",
        "GSK.L", "RIO.L", "DGE.L", "LSEG.L", "REL.L",
        "BATS.L", "NG.L", "VOD.L", "BARC.L", "LLOY.L",
    ],
    regulator="FCA (Financial Conduct Authority)",
    regulator_url="https://www.fca.org.uk",
    filing_sources=["lse_rns"],
)
