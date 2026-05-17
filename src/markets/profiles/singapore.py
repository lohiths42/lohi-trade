"""Singapore (SGX) market profile."""

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

SINGAPORE_PROFILE = MarketProfile(
    country=Country.SINGAPORE,
    country_name="Singapore",
    currency="SGD",
    currency_symbol="S$",
    timezone="Asia/Singapore",
    number_format=NumberFormat.INTERNATIONAL,
    exchanges=[Exchange.SGX],
    primary_exchange=Exchange.SGX,
    benchmark_index_name="Straits Times Index",
    benchmark_symbol="^STI",
    benchmark_redis_key="sti",
    sessions=MarketSession(
        pre_market_start=time(8, 30),
        pre_market_end=time(9, 0),
        market_open=time(9, 0),
        trading_start=time(9, 15),
        trading_end=time(17, 0),
        square_off_time=time(17, 2),
        market_close=time(17, 6),
    ),
    settlement_cycle=SettlementCycle.T2,
    tax_profile=TaxProfile(
        country=Country.SINGAPORE,
        currency="SGD",
        transaction_taxes=[
            TaxRule(
                name="SGX Clearing Fee",
                rate_pct=0.0325,
                applies_to="both",
                description="SGX clearing fee on contract value",
            ),
            TaxRule(
                name="SGX Trading Fee",
                rate_pct=0.0075,
                applies_to="both",
                description="SGX access fee",
            ),
        ],
        capital_gains_short_term_pct=0.0,  # Singapore has NO capital gains tax
        capital_gains_long_term_pct=0.0,
        short_term_threshold_days=0,
        wash_sale_rule=False,
        wash_sale_window_days=0,
        dividend_tax_pct=0.0,  # No dividend tax for individuals
        last_updated="2025-01-01",
        source="manual",
        verified_by_user=True,
        disclaimer=(
            "Singapore has NO capital gains tax for individuals. However, frequent traders "
            "may be classified as 'traders' by IRAS and taxed at income tax rates. "
            "Consult a tax advisor if trading is your primary activity."
        ),
    ),
    available_brokers=[
        BrokerInfo(
            broker_id="interactive_brokers",
            name="Interactive Brokers (Singapore)",
            description="Global broker with SGX access. MAS regulated.",
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
            broker_id="tiger_brokers",
            name="Tiger Brokers",
            description="Multi-market broker popular in Singapore. Good mobile and API.",
            api_type="rest",
            documentation_url="https://quant.itigerup.com/openapi/en/python/overview/introduction.html",
            supports_paper_trading=True,
            supports_options=True,
            supports_futures=True,
            commission_model="per_trade",
            credential_keys=["TIGER_ID", "TIGER_PRIVATE_KEY"],
            validation_patterns={
                "TIGER_ID": r"^.{4,}$",
                "TIGER_PRIVATE_KEY": r"^.{50,}$",
            },
        ),
        BrokerInfo(
            broker_id="moomoo",
            name="Moomoo (Futu)",
            description="Commission-free SGX trading with OpenAPI.",
            api_type="rest",
            documentation_url="https://openapi.moomoo.com",
            supports_paper_trading=True,
            supports_options=True,
            supports_futures=False,
            commission_model="zero_commission",
            credential_keys=["MOOMOO_RSA_KEY_PATH", "MOOMOO_ACCOUNT_ID"],
            validation_patterns={
                "MOOMOO_RSA_KEY_PATH": r"^.{5,}$",
                "MOOMOO_ACCOUNT_ID": r"^.{4,}$",
            },
        ),
    ],
    news_sources=[
        NewsSource(
            name="Business Times Singapore",
            url="https://www.businesstimes.com.sg/rss",
            category="general",
        ),
        NewsSource(
            name="SGX Announcements",
            url="https://www.sgx.com/securities/company-announcements",
            category="regulatory",
        ),
        NewsSource(
            name="Channel News Asia", url="https://www.channelnewsasia.com/rss", category="general"
        ),
    ],
    data_suffix=".SI",
    supports_short_selling=True,
    supports_options=True,
    supports_futures=True,
    supports_pre_market=True,
    supports_after_hours=False,
    min_lot_size=100,  # SGX trades in board lots of 100
    default_symbols=[
        "D05.SI",
        "O39.SI",
        "U11.SI",
        "Z74.SI",
        "BN4.SI",
        "C6L.SI",
        "A17U.SI",
        "C38U.SI",
        "G13.SI",
        "S58.SI",
        "V03.SI",
        "Y92.SI",
        "F34.SI",
        "BS6.SI",
        "S63.SI",
    ],
    regulator="MAS (Monetary Authority of Singapore)",
    regulator_url="https://www.mas.gov.sg",
    filing_sources=["sgx_announcements"],
)
