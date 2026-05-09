"""Australia (ASX) market profile."""

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

AUSTRALIA_PROFILE = MarketProfile(
    country=Country.AUSTRALIA,
    country_name="Australia",
    currency="AUD",
    currency_symbol="A$",
    timezone="Australia/Sydney",
    number_format=NumberFormat.INTERNATIONAL,
    exchanges=[Exchange.ASX],
    primary_exchange=Exchange.ASX,
    benchmark_index_name="S&P/ASX 200",
    benchmark_symbol="^AXJO",
    benchmark_redis_key="asx200",
    sessions=MarketSession(
        pre_market_start=time(7, 0),
        pre_market_end=time(10, 0),
        market_open=time(10, 0),
        trading_start=time(10, 15),
        trading_end=time(15, 50),
        square_off_time=time(15, 55),
        market_close=time(16, 0),
        post_market_start=time(16, 0),
        post_market_end=time(16, 10),
    ),
    settlement_cycle=SettlementCycle.T2,
    tax_profile=TaxProfile(
        country=Country.AUSTRALIA,
        currency="AUD",
        transaction_taxes=[
            TaxRule(
                name="Brokerage (typical online)",
                rate_pct=0.0,
                applies_to="both",
                description="Varies by broker. Typically $5-$20 flat per trade.",
                is_flat_fee=True,
                flat_fee_amount=10.0,
            ),
        ],
        capital_gains_short_term_pct=47.0,  # Top marginal rate
        capital_gains_long_term_pct=23.5,  # 50% CGT discount for >12 months
        short_term_threshold_days=365,
        wash_sale_rule=False,  # Australia doesn't have wash sale rules
        wash_sale_window_days=0,
        dividend_tax_pct=0.0,  # Franking credits system
        last_updated="2025-07-01",
        source="manual",
        verified_by_user=True,
        disclaimer=(
            "Australia offers 50% CGT discount for assets held >12 months. "
            "Franking credits reduce dividend tax. Rates depend on marginal tax bracket. "
            "Consult a registered tax agent."
        ),
    ),
    available_brokers=[
        BrokerInfo(
            broker_id="interactive_brokers",
            name="Interactive Brokers (Australia)",
            description="Global broker with ASX access. ASIC regulated.",
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
            broker_id="stake",
            name="Stake",
            description="Commission-free ASX and US trading. Modern API.",
            api_type="rest",
            documentation_url="https://stake.com.au",
            supports_paper_trading=False,
            supports_options=False,
            supports_futures=False,
            commission_model="zero_commission",
            credential_keys=["STAKE_API_KEY", "STAKE_ACCOUNT_ID"],
            validation_patterns={
                "STAKE_API_KEY": r"^.{10,}$",
                "STAKE_ACCOUNT_ID": r"^.{4,}$",
            },
        ),
    ],
    news_sources=[
        NewsSource(name="AFR (Australian Financial Review)", url="https://www.afr.com/rss", category="general"),
        NewsSource(name="ASX Announcements", url="https://www.asx.com.au/asx/statistics/announcements.do", category="regulatory"),
        NewsSource(name="Reuters Australia", url="https://www.reutersagency.com/feed/", category="general"),
    ],
    data_suffix=".AX",
    supports_short_selling=True,
    supports_options=True,
    supports_futures=True,
    supports_pre_market=True,
    supports_after_hours=False,
    min_lot_size=1,
    default_symbols=[
        "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX",
        "ANZ.AX", "FMG.AX", "WES.AX", "MQG.AX", "TLS.AX",
        "WOW.AX", "RIO.AX", "ALL.AX", "STO.AX", "COL.AX",
    ],
    regulator="ASIC (Australian Securities and Investments Commission)",
    regulator_url="https://asic.gov.au",
    filing_sources=["asx_announcements"],
)
