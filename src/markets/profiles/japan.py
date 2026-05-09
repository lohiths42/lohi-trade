"""Japan (JPX/TSE) market profile."""

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

JAPAN_PROFILE = MarketProfile(
    country=Country.JAPAN,
    country_name="Japan",
    currency="JPY",
    currency_symbol="¥",
    timezone="Asia/Tokyo",
    number_format=NumberFormat.INTERNATIONAL,
    exchanges=[Exchange.JPX, Exchange.TSE_JP],
    primary_exchange=Exchange.JPX,
    benchmark_index_name="Nikkei 225",
    benchmark_symbol="^N225",
    benchmark_redis_key="nikkei225",
    sessions=MarketSession(
        market_open=time(9, 0),
        trading_start=time(9, 15),
        trading_end=time(15, 20),  # Afternoon session ends 15:30, buffer before
        square_off_time=time(15, 25),
        market_close=time(15, 30),
    ),
    settlement_cycle=SettlementCycle.T2,
    tax_profile=TaxProfile(
        country=Country.JAPAN,
        currency="JPY",
        transaction_taxes=[
            TaxRule(
                name="Brokerage Commission",
                rate_pct=0.0,
                applies_to="both",
                description="Varies by broker and trade size. Many online brokers offer zero commission.",
                is_flat_fee=True,
                flat_fee_amount=0.0,
            ),
        ],
        capital_gains_short_term_pct=20.315,  # 15% income + 5% resident + 0.315% reconstruction
        capital_gains_long_term_pct=20.315,  # Same rate — Japan doesn't distinguish
        short_term_threshold_days=0,  # No distinction
        wash_sale_rule=False,
        wash_sale_window_days=0,
        dividend_tax_pct=20.315,  # Same flat rate
        last_updated="2025-01-01",
        source="manual",
        verified_by_user=True,
        disclaimer=(
            "Japan applies flat 20.315% tax on capital gains and dividends "
            "(15.315% national + 5% local). NISA accounts offer tax-free allowance. "
            "Consult a zeirishi (tax accountant)."
        ),
    ),
    available_brokers=[
        BrokerInfo(
            broker_id="interactive_brokers",
            name="Interactive Brokers (Japan)",
            description="Global broker with JPX access. FSA Japan regulated.",
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
            broker_id="sbi_securities",
            name="SBI Securities",
            description="Japan's largest online broker. Japanese-language API.",
            api_type="rest",
            documentation_url="https://www.sbisec.co.jp",
            supports_paper_trading=False,
            supports_options=True,
            supports_futures=True,
            commission_model="zero_commission",
            credential_keys=["SBI_USER_ID", "SBI_PASSWORD", "SBI_TRADE_PASSWORD"],
            validation_patterns={
                "SBI_USER_ID": r"^.{4,}$",
                "SBI_PASSWORD": r"^.{6,}$",
                "SBI_TRADE_PASSWORD": r"^.{4,}$",
            },
        ),
    ],
    news_sources=[
        NewsSource(name="Nikkei Asia", url="https://asia.nikkei.com/rss", category="general"),
        NewsSource(name="Japan Times Business", url="https://www.japantimes.co.jp/feed/", category="general"),
        NewsSource(name="JPX TDnet", url="https://www.jpx.co.jp/english/listing/disclosure/", category="regulatory"),
    ],
    data_suffix=".T",
    supports_short_selling=True,
    supports_options=True,
    supports_futures=True,
    supports_pre_market=False,
    supports_after_hours=False,
    min_lot_size=100,  # Japan trades in lots of 100 shares
    default_symbols=[
        "7203.T", "6758.T", "9984.T", "6861.T", "8306.T",
        "6501.T", "7267.T", "9432.T", "4502.T", "6902.T",
        "8035.T", "6098.T", "4063.T", "7974.T", "9433.T",
    ],
    regulator="FSA (Financial Services Agency of Japan)",
    regulator_url="https://www.fsa.go.jp/en/",
    filing_sources=["jpx_tdnet"],
)
