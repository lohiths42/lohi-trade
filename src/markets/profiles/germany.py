"""Germany (XETRA) market profile."""

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
)

GERMANY_PROFILE = MarketProfile(
    country=Country.GERMANY,
    country_name="Germany",
    currency="EUR",
    currency_symbol="€",
    timezone="Europe/Berlin",
    number_format=NumberFormat.EUROPEAN,
    exchanges=[Exchange.XETRA, Exchange.FRA],
    primary_exchange=Exchange.XETRA,
    benchmark_index_name="DAX 40",
    benchmark_symbol="^GDAXI",
    benchmark_redis_key="dax40",
    sessions=MarketSession(
        pre_market_start=time(8, 0),
        pre_market_end=time(9, 0),
        market_open=time(9, 0),
        trading_start=time(9, 15),
        trading_end=time(17, 20),
        square_off_time=time(17, 25),
        market_close=time(17, 30),
    ),
    settlement_cycle=SettlementCycle.T2,
    tax_profile=TaxProfile(
        country=Country.GERMANY,
        currency="EUR",
        transaction_taxes=[
            # Note: Solidarity surcharge applies to the capital gains TAX, not to
            # individual transactions. It's included in the effective CGT rate (26.375%).
            # No per-transaction taxes in Germany beyond broker commission.
        ],
        capital_gains_short_term_pct=26.375,  # 25% + 5.5% soli + church tax varies
        capital_gains_long_term_pct=26.375,  # Germany has flat rate regardless of holding period
        short_term_threshold_days=0,  # No distinction
        wash_sale_rule=False,
        wash_sale_window_days=0,
        dividend_tax_pct=26.375,  # Same flat rate
        last_updated="2025-01-01",
        source="manual",
        verified_by_user=True,
        disclaimer=(
            "Germany applies flat 25% Abgeltungsteuer (withholding tax) + 5.5% Soli + optional church tax. "
            "€1,000 annual Sparerpauschbetrag (saver's allowance). "
            "Loss offsetting rules apply. Consult a Steuerberater."
        ),
    ),
    available_brokers=[
        BrokerInfo(
            broker_id="interactive_brokers",
            name="Interactive Brokers (Germany)",
            description="Professional broker with XETRA access. BaFin regulated.",
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
            broker_id="scalable_capital",
            name="Scalable Capital",
            description="German neobroker with flat-rate trading. Limited API.",
            api_type="rest",
            documentation_url="https://scalable.capital",
            supports_paper_trading=False,
            supports_options=False,
            supports_futures=False,
            commission_model="zero_commission",
            credential_keys=["SCALABLE_EMAIL", "SCALABLE_PASSWORD"],
            validation_patterns={
                "SCALABLE_EMAIL": r"^.+@.+\..+$",
                "SCALABLE_PASSWORD": r"^.{8,}$",
            },
        ),
    ],
    news_sources=[
        NewsSource(
            name="Handelsblatt",
            url="https://www.handelsblatt.com/rss/",
            language="de",
            category="general",
        ),
        NewsSource(
            name="Börse Frankfurt News",
            url="https://www.boerse-frankfurt.de",
            language="de",
            category="regulatory",
        ),
        NewsSource(
            name="Reuters Germany", url="https://www.reutersagency.com/feed/", category="general"
        ),
    ],
    data_suffix=".DE",
    supports_short_selling=True,
    supports_options=True,
    supports_futures=True,
    supports_pre_market=True,
    supports_after_hours=False,
    min_lot_size=1,
    default_symbols=[
        "SAP.DE",
        "SIE.DE",
        "ALV.DE",
        "DTE.DE",
        "BAS.DE",
        "MBG.DE",
        "BMW.DE",
        "MUV2.DE",
        "IFX.DE",
        "ADS.DE",
        "DHL.DE",
        "VOW3.DE",
        "HEN3.DE",
        "BEI.DE",
        "RWE.DE",
    ],
    regulator="BaFin (Federal Financial Supervisory Authority)",
    regulator_url="https://www.bafin.de",
    filing_sources=["bundesanzeiger"],
)
