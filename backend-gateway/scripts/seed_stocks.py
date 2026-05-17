#!/usr/bin/env python3
"""Seed the securities, security_fundamentals, and security_technicals tables
with real Indian stock data using yfinance.

Usage:
    cd backend-gateway
    python -m scripts.seed_stocks

Or from project root:
    python backend-gateway/scripts/seed_stocks.py

Requires: yfinance, asyncpg, python-dotenv
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Ensure backend-gateway is on the path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Top Indian stocks (NSE) — F&O + Nifty 50 + popular mid/small caps ──────
# Symbol format: "SYMBOL.NS" for yfinance, stored as "SYMBOL" in DB

NIFTY_50 = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "HINDUNILVR",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "LT",
    "AXISBANK",
    "BAJFINANCE",
    "ASIANPAINT",
    "MARUTI",
    "HCLTECH",
    "TITAN",
    "SUNPHARMA",
    "ULTRACEMCO",
    "NTPC",
    "WIPRO",
    "NESTLEIND",
    "TATAMOTORS",
    "M&M",
    "POWERGRID",
    "JSWSTEEL",
    "TATASTEEL",
    "ADANIENT",
    "ADANIPORTS",
    "BAJAJFINSV",
    "TECHM",
    "ONGC",
    "COALINDIA",
    "HDFCLIFE",
    "DIVISLAB",
    "DRREDDY",
    "GRASIM",
    "CIPLA",
    "APOLLOHOSP",
    "EICHERMOT",
    "SBILIFE",
    "BPCL",
    "TATACONSUM",
    "BRITANNIA",
    "HEROMOTOCO",
    "INDUSINDBK",
    "BAJAJ-AUTO",
    "HINDALCO",
    "UPL",
    "LTIM",
]

ADDITIONAL_STOCKS = [
    "ZOMATO",
    "PAYTM",
    "NYKAA",
    "DELHIVERY",
    "IRCTC",
    "TATAPOWER",
    "VEDL",
    "BANKBARODA",
    "PNB",
    "CANBK",
    "IDFCFIRSTB",
    "FEDERALBNK",
    "BANDHANBNK",
    "BIOCON",
    "LUPIN",
    "AUROPHARMA",
    "TORNTPHARM",
    "PIDILITIND",
    "GODREJCP",
    "DABUR",
    "MARICO",
    "COLPAL",
    "HAVELLS",
    "VOLTAS",
    "CROMPTON",
    "TRENT",
    "PAGEIND",
    "MUTHOOTFIN",
    "MANAPPURAM",
    "CHOLAFIN",
    "SBICARD",
    "PIIND",
    "ATUL",
    "DEEPAKNTR",
    "NAVINFLUOR",
    "COFORGE",
    "PERSISTENT",
    "MPHASIS",
    "LTTS",
    "HAPPSTMNDS",
    "POLYCAB",
    "KEI",
    "DIXON",
    "KAYNES",
    "AFFLE",
    "ZYDUSLIFE",
    "GLENMARK",
    "IPCALAB",
    "LALPATHLAB",
    "METROPOLIS",
]

ALL_SYMBOLS = NIFTY_50 + ADDITIONAL_STOCKS

# Sector mapping based on common knowledge
SECTOR_MAP = {
    "RELIANCE": ("Energy", "Oil & Gas"),
    "TCS": ("IT/Technology", "IT Services"),
    "HDFCBANK": ("Banking & Finance", "Private Banks"),
    "INFY": ("IT/Technology", "IT Services"),
    "ICICIBANK": ("Banking & Finance", "Private Banks"),
    "HINDUNILVR": ("FMCG", "Personal Care"),
    "ITC": ("FMCG", "Tobacco"),
    "SBIN": ("Banking & Finance", "PSU Banks"),
    "BHARTIARTL": ("Telecom", "Telecom Services"),
    "KOTAKBANK": ("Banking & Finance", "Private Banks"),
    "LT": ("Infrastructure", "Roads & Highways"),
    "AXISBANK": ("Banking & Finance", "Private Banks"),
    "BAJFINANCE": ("Banking & Finance", "NBFCs"),
    "ASIANPAINT": ("Chemicals", "Paints & Coatings"),
    "MARUTI": ("Automobile", "Passenger Vehicles"),
    "HCLTECH": ("IT/Technology", "IT Services"),
    "TITAN": ("FMCG", "Personal Care"),
    "SUNPHARMA": ("Pharma", "Pharmaceuticals"),
    "ULTRACEMCO": ("Infrastructure", "Urban Infrastructure"),
    "NTPC": ("Energy", "Power Generation"),
    "WIPRO": ("IT/Technology", "IT Services"),
    "NESTLEIND": ("FMCG", "Packaged Foods"),
    "TATAMOTORS": ("Automobile", "Passenger Vehicles"),
    "M&M": ("Automobile", "Passenger Vehicles"),
    "POWERGRID": ("Energy", "Power Distribution"),
    "JSWSTEEL": ("Metals & Mining", "Steel"),
    "TATASTEEL": ("Metals & Mining", "Steel"),
    "ADANIENT": ("Infrastructure", "Roads & Highways"),
    "ADANIPORTS": ("Infrastructure", "Ports & Shipping"),
    "BAJAJFINSV": ("Banking & Finance", "NBFCs"),
    "TECHM": ("IT/Technology", "IT Services"),
    "ONGC": ("Energy", "Oil & Gas"),
    "COALINDIA": ("Metals & Mining", "Mining"),
    "HDFCLIFE": ("Insurance", "Life Insurance"),
    "DIVISLAB": ("Pharma", "Pharmaceuticals"),
    "DRREDDY": ("Pharma", "Pharmaceuticals"),
    "GRASIM": ("Infrastructure", "Urban Infrastructure"),
    "CIPLA": ("Pharma", "Pharmaceuticals"),
    "APOLLOHOSP": ("Pharma", "Healthcare Services"),
    "EICHERMOT": ("Automobile", "Two Wheelers"),
    "SBILIFE": ("Insurance", "Life Insurance"),
    "BPCL": ("Energy", "Oil & Gas"),
    "TATACONSUM": ("FMCG", "Food & Beverages"),
    "BRITANNIA": ("FMCG", "Packaged Foods"),
    "HEROMOTOCO": ("Automobile", "Two Wheelers"),
    "INDUSINDBK": ("Banking & Finance", "Private Banks"),
    "BAJAJ-AUTO": ("Automobile", "Two Wheelers"),
    "HINDALCO": ("Metals & Mining", "Aluminium"),
    "UPL": ("Chemicals", "Agrochemicals"),
    "LTIM": ("IT/Technology", "IT Services"),
    "ZOMATO": ("IT/Technology", "Internet Services"),
    "PAYTM": ("IT/Technology", "Internet Services"),
    "NYKAA": ("IT/Technology", "Internet Services"),
    "DELHIVERY": ("Infrastructure", "Roads & Highways"),
    "IRCTC": ("Infrastructure", "Railways"),
    "TATAPOWER": ("Energy", "Power Generation"),
    "VEDL": ("Metals & Mining", "Mining"),
    "BANKBARODA": ("Banking & Finance", "PSU Banks"),
    "PNB": ("Banking & Finance", "PSU Banks"),
    "CANBK": ("Banking & Finance", "PSU Banks"),
    "IDFCFIRSTB": ("Banking & Finance", "Private Banks"),
    "FEDERALBNK": ("Banking & Finance", "Private Banks"),
    "BANDHANBNK": ("Banking & Finance", "Private Banks"),
    "BIOCON": ("Pharma", "Biotechnology"),
    "LUPIN": ("Pharma", "Pharmaceuticals"),
    "AUROPHARMA": ("Pharma", "Pharmaceuticals"),
    "TORNTPHARM": ("Pharma", "Pharmaceuticals"),
    "PIDILITIND": ("Chemicals", "Specialty Chemicals"),
    "GODREJCP": ("FMCG", "Personal Care"),
    "DABUR": ("FMCG", "Personal Care"),
    "MARICO": ("FMCG", "Personal Care"),
    "COLPAL": ("FMCG", "Personal Care"),
    "HAVELLS": ("Infrastructure", "Urban Infrastructure"),
    "VOLTAS": ("Infrastructure", "Urban Infrastructure"),
    "CROMPTON": ("Infrastructure", "Urban Infrastructure"),
    "TRENT": ("FMCG", "Household Products"),
    "PAGEIND": ("FMCG", "Household Products"),
    "MUTHOOTFIN": ("Banking & Finance", "NBFCs"),
    "MANAPPURAM": ("Banking & Finance", "NBFCs"),
    "CHOLAFIN": ("Banking & Finance", "NBFCs"),
    "SBICARD": ("Banking & Finance", "NBFCs"),
    "PIIND": ("Chemicals", "Agrochemicals"),
    "ATUL": ("Chemicals", "Specialty Chemicals"),
    "DEEPAKNTR": ("Chemicals", "Specialty Chemicals"),
    "NAVINFLUOR": ("Chemicals", "Specialty Chemicals"),
    "COFORGE": ("IT/Technology", "IT Services"),
    "PERSISTENT": ("IT/Technology", "IT Services"),
    "MPHASIS": ("IT/Technology", "IT Services"),
    "LTTS": ("IT/Technology", "IT Services"),
    "HAPPSTMNDS": ("IT/Technology", "IT Services"),
    "POLYCAB": ("Infrastructure", "Urban Infrastructure"),
    "KEI": ("Infrastructure", "Urban Infrastructure"),
    "DIXON": ("IT/Technology", "IT Services"),
    "KAYNES": ("IT/Technology", "Semiconductors"),
    "AFFLE": ("IT/Technology", "Internet Services"),
    "ZYDUSLIFE": ("Pharma", "Pharmaceuticals"),
    "GLENMARK": ("Pharma", "Pharmaceuticals"),
    "IPCALAB": ("Pharma", "Pharmaceuticals"),
    "LALPATHLAB": ("Pharma", "Healthcare Services"),
    "METROPOLIS": ("Pharma", "Healthcare Services"),
}


def _safe_decimal(val, default=None) -> Decimal | None:
    """Convert a value to Decimal safely."""
    if val is None:
        return default
    try:
        import math

        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _safe_decimal4(val, default=None) -> Decimal | None:
    """Convert to Decimal with 4 decimal places."""
    if val is None:
        return default
    try:
        import math

        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return Decimal(str(val)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _classify_market_cap(market_cap_val) -> str | None:
    """Classify market cap into large-cap, mid-cap, small-cap."""
    if market_cap_val is None:
        return None
    try:
        mc = float(market_cap_val)
    except (ValueError, TypeError):
        return None
    # In INR crores: large > 20000 Cr, mid 5000-20000, small < 5000
    # yfinance returns in absolute currency units
    mc_cr = mc / 1e7  # Convert to crores
    if mc_cr >= 20000:
        return "large-cap"
    elif mc_cr >= 5000:
        return "mid-cap"
    else:
        return "small-cap"


def fetch_stock_data(symbols: list[str]) -> list[dict]:
    """Fetch stock data from yfinance for given NSE symbols."""
    results = []
    batch_size = 10

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        yf_symbols = [f"{s}.NS" for s in batch]
        logger.info("Fetching batch %d-%d: %s", i + 1, i + len(batch), ", ".join(batch))

        tickers = yf.Tickers(" ".join(yf_symbols))

        for sym, yf_sym in zip(batch, yf_symbols):
            try:
                ticker = tickers.tickers.get(yf_sym)
                if ticker is None:
                    logger.warning("Ticker %s not found in yfinance", yf_sym)
                    continue

                info = ticker.info or {}
                if not info.get("symbol") and not info.get("shortName"):
                    logger.warning("No data for %s", sym)
                    continue

                sector_info = SECTOR_MAP.get(sym, ("Miscellaneous", "Other"))
                market_cap = info.get("marketCap")

                # Get historical data for price changes
                hist = None
                try:
                    hist = ticker.history(period="1y")
                except Exception:
                    pass

                price_changes = _compute_price_changes(hist)

                stock = {
                    "symbol": sym,
                    "isin": info.get("isin", f"INE{sym[:6].upper()}01010"),
                    "company_name": info.get("longName") or info.get("shortName") or sym,
                    "exchange": "NSE",
                    "sector": sector_info[0],
                    "industry": sector_info[1],
                    "market_cap_category": _classify_market_cap(market_cap),
                    "listing_date": None,
                    "face_value": _safe_decimal(info.get("faceValue", 10)),
                    # Fundamentals
                    "pe_ratio": _safe_decimal(info.get("trailingPE")),
                    "pb_ratio": _safe_decimal(info.get("priceToBook")),
                    "market_cap": _safe_decimal(market_cap),
                    "dividend_yield": _safe_decimal(
                        (info.get("dividendYield") or 0) * 100
                        if info.get("dividendYield")
                        else None
                    ),
                    "eps": _safe_decimal(info.get("trailingEps")),
                    "roe": _safe_decimal(
                        (info.get("returnOnEquity") or 0) * 100
                        if info.get("returnOnEquity")
                        else None
                    ),
                    "debt_to_equity": _safe_decimal(info.get("debtToEquity")),
                    "revenue_growth_1y": _safe_decimal(
                        (info.get("revenueGrowth") or 0) * 100
                        if info.get("revenueGrowth")
                        else None
                    ),
                    "high_52w": _safe_decimal(info.get("fiftyTwoWeekHigh")),
                    "low_52w": _safe_decimal(info.get("fiftyTwoWeekLow")),
                    # Technicals
                    "rsi_14": _compute_rsi(hist),
                    "sma_50": _safe_decimal(info.get("fiftyDayAverage")),
                    "sma_200": _safe_decimal(info.get("twoHundredDayAverage")),
                    "avg_volume_20d": info.get("averageVolume"),
                    **price_changes,
                }
                results.append(stock)
                logger.info(
                    "  ✓ %s — %s (mcap: %s)",
                    sym,
                    stock["company_name"],
                    stock["market_cap_category"],
                )

            except Exception as e:
                logger.warning("  ✗ %s failed: %s", sym, str(e))
                continue

    return results


def _compute_rsi(hist, period=14) -> Decimal | None:
    """Compute RSI from historical price data."""
    if hist is None or len(hist) < period + 1:
        return None
    try:
        close = hist["Close"].values
        deltas = [close[i] - close[i - 1] for i in range(1, len(close))]
        recent = deltas[-(period):]
        gains = [d for d in recent if d > 0]
        losses = [-d for d in recent if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        return _safe_decimal(rsi)
    except Exception:
        return None


def _compute_price_changes(hist) -> dict:
    """Compute price change percentages for various periods."""
    result = {
        "price_change_1d": None,
        "price_change_1w": None,
        "price_change_1m": None,
        "price_change_3m": None,
        "price_change_6m": None,
        "price_change_1y": None,
    }
    if hist is None or len(hist) < 2:
        return result

    try:
        close = hist["Close"]
        current = float(close.iloc[-1])

        periods = {
            "price_change_1d": 1,
            "price_change_1w": 5,
            "price_change_1m": 21,
            "price_change_3m": 63,
            "price_change_6m": 126,
            "price_change_1y": 252,
        }

        for key, days in periods.items():
            if len(close) > days:
                past = float(close.iloc[-days - 1])
                if past > 0:
                    change = ((current - past) / past) * 100
                    result[key] = _safe_decimal4(change)
    except Exception:
        pass

    return result


async def seed_database(database_url: str, stocks: list[dict]) -> int:
    """Insert stock data into PostgreSQL tables."""
    import asyncpg

    logger.info("Connecting to PostgreSQL: %s", database_url[:30] + "...")
    pool = await asyncpg.create_pool(dsn=database_url, min_size=2, max_size=5)

    now = datetime.now(timezone.utc)
    inserted = 0

    async with pool.acquire() as conn:
        for stock in stocks:
            try:
                # Upsert into securities
                row = await conn.fetchrow(
                    """
                    INSERT INTO securities
                        (symbol, isin, company_name, exchange, sector, industry,
                         market_cap_category, listing_date, face_value, status, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'ACTIVE', $10)
                    ON CONFLICT (isin) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        company_name = EXCLUDED.company_name,
                        exchange = EXCLUDED.exchange,
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        market_cap_category = EXCLUDED.market_cap_category,
                        face_value = EXCLUDED.face_value,
                        status = 'ACTIVE',
                        updated_at = EXCLUDED.updated_at
                    RETURNING id
                    """,
                    stock["symbol"],
                    stock["isin"],
                    stock["company_name"],
                    stock["exchange"],
                    stock["sector"],
                    stock["industry"],
                    stock["market_cap_category"],
                    stock.get("listing_date"),
                    stock.get("face_value"),
                    now,
                )

                if row is None:
                    continue

                sec_id = row["id"]

                # Upsert fundamentals
                await conn.execute(
                    """
                    INSERT INTO security_fundamentals
                        (security_id, pe_ratio, pb_ratio, market_cap, dividend_yield,
                         eps, roe, debt_to_equity, revenue_growth_1y,
                         high_52w, low_52w, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (security_id) DO UPDATE SET
                        pe_ratio = EXCLUDED.pe_ratio,
                        pb_ratio = EXCLUDED.pb_ratio,
                        market_cap = EXCLUDED.market_cap,
                        dividend_yield = EXCLUDED.dividend_yield,
                        eps = EXCLUDED.eps,
                        roe = EXCLUDED.roe,
                        debt_to_equity = EXCLUDED.debt_to_equity,
                        revenue_growth_1y = EXCLUDED.revenue_growth_1y,
                        high_52w = EXCLUDED.high_52w,
                        low_52w = EXCLUDED.low_52w,
                        updated_at = EXCLUDED.updated_at
                    """,
                    sec_id,
                    stock.get("pe_ratio"),
                    stock.get("pb_ratio"),
                    stock.get("market_cap"),
                    stock.get("dividend_yield"),
                    stock.get("eps"),
                    stock.get("roe"),
                    stock.get("debt_to_equity"),
                    stock.get("revenue_growth_1y"),
                    stock.get("high_52w"),
                    stock.get("low_52w"),
                    now,
                )

                # Upsert technicals
                await conn.execute(
                    """
                    INSERT INTO security_technicals
                        (security_id, rsi_14, sma_50, sma_200, avg_volume_20d,
                         price_change_1d, price_change_1w, price_change_1m,
                         price_change_3m, price_change_6m, price_change_1y,
                         updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (security_id) DO UPDATE SET
                        rsi_14 = EXCLUDED.rsi_14,
                        sma_50 = EXCLUDED.sma_50,
                        sma_200 = EXCLUDED.sma_200,
                        avg_volume_20d = EXCLUDED.avg_volume_20d,
                        price_change_1d = EXCLUDED.price_change_1d,
                        price_change_1w = EXCLUDED.price_change_1w,
                        price_change_1m = EXCLUDED.price_change_1m,
                        price_change_3m = EXCLUDED.price_change_3m,
                        price_change_6m = EXCLUDED.price_change_6m,
                        price_change_1y = EXCLUDED.price_change_1y,
                        updated_at = EXCLUDED.updated_at
                    """,
                    sec_id,
                    stock.get("rsi_14"),
                    stock.get("sma_50"),
                    stock.get("sma_200"),
                    stock.get("avg_volume_20d"),
                    stock.get("price_change_1d"),
                    stock.get("price_change_1w"),
                    stock.get("price_change_1m"),
                    stock.get("price_change_3m"),
                    stock.get("price_change_6m"),
                    stock.get("price_change_1y"),
                    now,
                )

                inserted += 1

            except Exception as e:
                logger.warning("Failed to insert %s: %s", stock.get("symbol"), str(e))
                continue

    await pool.close()
    return inserted


async def main():
    """Main entry point."""
    from dotenv import load_dotenv

    # Load .env from backend-gateway or project root
    for env_path in [_root / ".env", _root.parent / ".env", _root.parent / ".env.template"]:
        if env_path.exists():
            load_dotenv(env_path)
            break

    database_url = os.environ.get("DATABASE_URL", "postgresql://lohi:lohi@localhost:5432/lohitrade")
    logger.info("Database URL: %s", database_url[:40] + "...")

    logger.info("=" * 60)
    logger.info(
        "LOHI-TRADE Stock Seeder — Fetching %d Indian stocks via yfinance", len(ALL_SYMBOLS)
    )
    logger.info("=" * 60)

    stocks = fetch_stock_data(ALL_SYMBOLS)
    logger.info("Fetched data for %d / %d stocks", len(stocks), len(ALL_SYMBOLS))

    if not stocks:
        logger.error("No stock data fetched. Check your internet connection.")
        sys.exit(1)

    inserted = await seed_database(database_url, stocks)
    logger.info("=" * 60)
    logger.info("Seeding complete: %d stocks inserted/updated", inserted)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
