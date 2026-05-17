#!/usr/bin/env python3
"""Seed the FULL NSE + BSE equity universe (~7600+ stocks) into PostgreSQL.

Downloads the official NSE EQUITY_L.csv and BSE equity listing,
classifies sectors using industry keywords, and upserts all securities.

Fundamentals/technicals are populated separately by the live_data_service
background task using yfinance in batches.  Chart and quote data is
fetched on-demand from yfinance when a user views a stock detail page.

Usage:
    cd backend-gateway
    python -m scripts.seed_nse_universe

Requires: asyncpg, httpx, python-dotenv
"""

import asyncio
import csv
import io
import logging
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Exchange CSV endpoints ──────────────────────────────────────────────────
NSE_EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_EQUITY_CSV_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Atea=&segment=Equity&status=Active"

# Common headers to mimic browser (exchanges block non-browser requests)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}

BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

# ── Sector classification by industry keywords ─────────────────────────────

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Insurance": [
        "insurance",
        "life insurance",
        "general insurance",
        "reinsurance",
    ],
    "Banking & Finance": [
        "bank",
        "finance",
        "financial",
        "nbfc",
        "credit",
        "lending",
        "microfinance",
        "wealth",
        "capital market",
        "stock exchange",
        "mutual fund",
        "asset management",
        "housing finance",
        "investment",
        "leasing",
        "securities",
        "fincorp",
        "finserv",
        "fiscal",
        "holding",
        "trading",
        "equity",
        "etf",
        "home loan",
        "mercantile",
        "networth",
        "corporate serv",
        "advisor",
        "consult",
    ],
    "IT/Technology": [
        "software",
        "information technology",
        "it ",
        "computer",
        "digital",
        "cloud",
        "saas",
        "internet",
        "e-commerce",
        "tech",
        "data processing",
        "artificial intelligence",
        "infotech",
        "network",
        "automation",
        "electronic",
        "semiconductor",
        "online",
        "solution",
        "infoway",
        "systems ltd",
        "systems limited",
    ],
    "Pharma": [
        "pharma",
        "drug",
        "healthcare",
        "hospital",
        "diagnostic",
        "medical",
        "biotech",
        "laboratory",
        "pathology",
        "health",
        "bioscien",
        "lifescien",
        "therapeut",
        "surgical",
        "nutraceut",
        "clinical",
        "nutri",
        "ayurved",
    ],
    "FMCG": [
        "consumer",
        "fmcg",
        "food",
        "beverage",
        "personal care",
        "tobacco",
        "dairy",
        "packaged",
        "household",
        "detergent",
        "agro",
        "agri",
        "agricultur",
        "cotton",
        "textile",
        "garment",
        "apparel",
        "fabric",
        "silk",
        "jute",
        "wool",
        "yarn",
        "fibre",
        "flour",
        "edible",
        "rice",
        "wheat",
        "jewel",
        "diamond",
        "cosmetic",
        "soap",
        "paper",
        "newsprint",
        "sugar",
        "tea",
        "spice",
        "confection",
        "biscuit",
        "brewer",
        "footwear",
        "leather",
        "fashion",
        "retail",
        "spirit",
        "liquor",
        "distiller",
        "spinning",
        "weaving",
        "knit",
        "denim",
        "ceramic",
        "glass",
        "stove",
        "kitchen",
        "appliance",
        "export",
        "import",
        "impex",
    ],
    "Energy": [
        "oil",
        "gas",
        "petroleum",
        "power",
        "energy",
        "electricity",
        "solar",
        "wind",
        "renewable",
        "coal",
        "fuel",
        "refiner",
        "petrochem",
        "thermal",
        "hydro",
        "transformer",
        "electrical",
        "cable",
        "drilling",
        "pipeline",
        "electro",
        "switchgear",
        "generator",
        "turbine",
        "boiler",
        "battery",
        "lamp",
        "lighting",
    ],
    "Automobile": [
        "auto",
        "vehicle",
        "motor",
        "car",
        "tractor",
        "tyre",
        "tire",
        "two wheeler",
        "scooter",
        "motorcycle",
        "ev ",
        "electric vehicle",
        "automotive",
        "transmission",
        "passenger vehicle",
        "bearing",
        "brake",
        "axle",
        "mobility",
    ],
    "Metals & Mining": [
        "steel",
        "iron",
        "metal",
        "mining",
        "aluminium",
        "aluminum",
        "copper",
        "zinc",
        "gold",
        "silver",
        "mineral",
        "ore",
        "alloy",
        "stainless",
        "foundry",
        "casting",
        "forging",
        "ferro",
        "tungsten",
        "titanium",
        "nickel",
        "ispat",
        "wire",
        "precision",
        "fastener",
        "forge",
    ],
    "Infrastructure": [
        "infrastructure",
        "construction",
        "cement",
        "road",
        "highway",
        "railway",
        "port",
        "shipping",
        "logistics",
        "warehouse",
        "engineering",
        "epc",
        "real estate",
        "aviation",
        "airline",
        "airport",
        "defence",
        "defense",
        "shipyard",
        "dock",
        "container",
        "transport",
        "cargo",
        "freight",
        "pump",
        "floor",
        "tile",
        "sanitar",
        "crane",
        "compressor",
        "project",
    ],
    "Chemicals": [
        "chemical",
        "specialty chemical",
        "agrochemical",
        "fertilizer",
        "pesticide",
        "paint",
        "pigment",
        "dye",
        "polymer",
        "plastic",
        "fluorochem",
        "resin",
        "solvent",
        "acid",
        "rubber",
        "latex",
        "adhesive",
        "laminate",
        "plywood",
        "synthetic",
        "vinyl",
        "epoxy",
        "nitrochem",
        "coating",
    ],
    "Telecom": [
        "telecom",
        "communication",
        "tower",
        "fiber",
        "broadband",
        "satellite",
        "wireless",
    ],
    "Real Estate": [
        "real estate",
        "property",
        "housing",
        "realty",
        "reit",
        "developer",
        "builder",
        "estate",
    ],
    "Media & Entertainment": [
        "media",
        "entertainment",
        "broadcast",
        "film",
        "television",
        "gaming",
        "advertising",
        "print",
        "publishing",
        "cinema",
        "studio",
    ],
    "Miscellaneous": [],  # catch-all
}


def classify_sector(industry: str | None, company_name: str | None = None) -> str:
    """Classify a stock into a sector based on its industry description or company name."""
    for text in (industry, company_name):
        if not text:
            continue
        text_lower = text.lower()
        for sector, keywords in SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return sector
    return "Miscellaneous"


def _parse_date_nse(val: str | None) -> date | None:
    """Parse NSE date formats like '03-JAN-2000' or '2000-01-03'."""
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_face_value(val: str | None) -> Decimal | None:
    if not val or not val.strip():
        return None
    try:
        return Decimal(val.strip())
    except (InvalidOperation, ValueError):
        return None


async def fetch_nse_equity_list() -> list[dict]:
    """Download and parse the NSE EQUITY_L.csv file.

    Returns a list of dicts with keys: symbol, isin, company_name, exchange,
    sector, industry, listing_date, face_value, status.
    """
    securities = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # First hit NSE homepage to get cookies (NSE requires this)
        try:
            await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
        except Exception:
            pass

        # Now fetch the CSV
        for attempt in range(3):
            try:
                resp = await client.get(NSE_EQUITY_CSV_URL, headers=NSE_HEADERS)
                if resp.status_code == 200:
                    text = resp.text
                    break
                logger.warning("NSE CSV returned %d on attempt %d", resp.status_code, attempt + 1)
            except Exception as e:
                logger.warning("NSE CSV fetch attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(2 * (attempt + 1))
        else:
            logger.error("Failed to fetch NSE EQUITY_L.csv after 3 attempts")
            return securities

    # Parse CSV
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        symbol = (row.get("SYMBOL") or row.get("Symbol") or "").strip()
        isin = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or row.get("ISIN") or "").strip()
        company_name = (row.get("NAME OF COMPANY") or row.get("Company Name") or "").strip()
        industry = (row.get(" INDUSTRY") or row.get("INDUSTRY") or "").strip()
        listing_date_str = (row.get(" DATE OF LISTING") or row.get("DATE OF LISTING") or "").strip()
        face_value_str = (row.get(" FACE VALUE") or row.get("FACE VALUE") or "").strip()

        if not symbol or not isin:
            continue

        # Clean ISIN (sometimes has leading space)
        isin = isin.strip()

        securities.append(
            {
                "symbol": symbol.upper(),
                "isin": isin.upper(),
                "company_name": company_name or symbol,
                "exchange": "NSE",
                "sector": classify_sector(industry, company_name),
                "industry": industry or None,
                "market_cap_category": None,  # Will be filled by live_data_service
                "listing_date": _parse_date_nse(listing_date_str),
                "face_value": _parse_face_value(face_value_str),
                "status": "ACTIVE",
            }
        )

    logger.info("Parsed %d securities from NSE EQUITY_L.csv", len(securities))
    return securities


async def fetch_bse_equity_list() -> list[dict]:
    """Download and parse the BSE active equity listing via their API.

    Returns a list of dicts with keys: symbol, isin, company_name, exchange,
    sector, industry, listing_date, face_value, status, scrip_code.
    """
    securities = []

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                resp = await client.get(BSE_EQUITY_CSV_URL, headers=BSE_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    break
                logger.warning("BSE API returned %d on attempt %d", resp.status_code, attempt + 1)
            except Exception as e:
                logger.warning("BSE API fetch attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(2 * (attempt + 1))
        else:
            logger.error("Failed to fetch BSE equity list after 3 attempts")
            return securities

    if not isinstance(data, list):
        logger.error("BSE API returned unexpected format: %s", type(data))
        return securities

    for item in data:
        if not isinstance(item, dict):
            continue

        scrip_code = str(item.get("Scrip_Code") or item.get("SCRIP_CD") or "").strip()
        symbol = (item.get("scrip_id") or item.get("SCRIP_ID") or "").strip()
        isin = (item.get("ISIN_NUMBER") or item.get("Isin_Number") or "").strip()
        company_name = (
            item.get("Scrip_Name")
            or item.get("SCRIP_NAME")
            or item.get("LongName")
            or item.get("LONG_NAME")
            or ""
        ).strip()
        industry = (item.get("Industry") or item.get("INDUSTRY") or "").strip()
        group = (item.get("Scrip_Group") or item.get("GROUP") or "").strip()
        face_value_str = str(item.get("Face_Value") or item.get("FACE_VALUE") or "").strip()

        # BSE sometimes has scrip_code but no symbol — use scrip_code as fallback
        if not symbol and scrip_code:
            symbol = scrip_code

        if not isin or not symbol:
            continue

        # Skip non-equity groups (W = warrants, MF = mutual funds, etc.)
        if group and group.upper() in ("W", "MF", "IF", "DB", "G", "GS"):
            continue
        # Skip numeric-prefix symbols (segregated portfolios, MF units)
        if symbol and symbol[0].isdigit():
            continue

        securities.append(
            {
                "symbol": symbol.upper(),
                "isin": isin.upper().strip(),
                "company_name": company_name or symbol,
                "exchange": "BSE",
                "sector": classify_sector(industry, company_name),
                "industry": industry or None,
                "market_cap_category": None,
                "listing_date": None,
                "face_value": _parse_face_value(face_value_str),
                "status": "ACTIVE",
                "scrip_code": scrip_code,
            }
        )

    logger.info("Parsed %d securities from BSE API", len(securities))
    return securities


async def seed_database(database_url: str, securities: list[dict]) -> int:
    """Upsert all securities into PostgreSQL.

    For dual-listed stocks (same ISIN on both NSE and BSE), marks exchange as 'BOTH'.
    """
    import asyncpg

    logger.info("Connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(dsn=database_url, min_size=2, max_size=10)
    now = datetime.now(timezone.utc)
    inserted = 0

    # Merge by ISIN: if same ISIN appears in both NSE and BSE, mark as BOTH
    merged: dict[str, dict] = {}
    for sec in securities:
        isin = sec["isin"]
        if isin in merged:
            existing = merged[isin]
            if existing["exchange"] != sec["exchange"]:
                existing["exchange"] = "BOTH"
            # Prefer NSE symbol over BSE scrip_code
            if sec["exchange"] == "NSE":
                existing["symbol"] = sec["symbol"]
                existing["company_name"] = sec.get("company_name") or existing.get(
                    "company_name", ""
                )
                if sec.get("listing_date"):
                    existing["listing_date"] = sec["listing_date"]
        else:
            merged[isin] = dict(sec)

    async with pool.acquire() as conn:
        stmt = await conn.prepare(
            """
            INSERT INTO securities
                (symbol, isin, company_name, exchange, sector, industry,
                 market_cap_category, listing_date, face_value, status, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'ACTIVE', $10)
            ON CONFLICT (isin) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                company_name = EXCLUDED.company_name,
                exchange = EXCLUDED.exchange,
                sector = COALESCE(EXCLUDED.sector, securities.sector),
                industry = COALESCE(EXCLUDED.industry, securities.industry),
                listing_date = COALESCE(EXCLUDED.listing_date, securities.listing_date),
                face_value = COALESCE(EXCLUDED.face_value, securities.face_value),
                status = 'ACTIVE',
                updated_at = EXCLUDED.updated_at
        """
        )

        for sec in merged.values():
            try:
                await stmt.fetch(
                    sec["symbol"],
                    sec["isin"],
                    sec["company_name"],
                    sec["exchange"],
                    sec["sector"],
                    sec.get("industry"),
                    sec.get("market_cap_category"),
                    sec.get("listing_date"),
                    sec.get("face_value"),
                    now,
                )
                inserted += 1
            except Exception as e:
                logger.warning("Failed to upsert %s: %s", sec.get("symbol"), e)

        # Ensure fundamentals/technicals rows exist for all securities
        await conn.execute(
            """
            INSERT INTO security_fundamentals (security_id, updated_at)
            SELECT id, $1 FROM securities
            WHERE id NOT IN (SELECT security_id FROM security_fundamentals)
        """,
            now,
        )

        await conn.execute(
            """
            INSERT INTO security_technicals (security_id, updated_at)
            SELECT id, $1 FROM securities
            WHERE id NOT IN (SELECT security_id FROM security_technicals)
        """,
            now,
        )

    await pool.close()
    return inserted


async def main():
    from dotenv import load_dotenv

    for env_path in [_root / ".env", _root.parent / ".env"]:
        if env_path.exists():
            load_dotenv(env_path)
            break

    database_url = os.environ.get("DATABASE_URL", "postgresql://lohi:lohi@localhost:5432/lohitrade")

    logger.info("=" * 60)
    logger.info("LOHI-TRADE Full NSE + BSE Universe Seeder")
    logger.info("=" * 60)

    # Fetch NSE stocks
    nse_securities = await fetch_nse_equity_list()
    logger.info("NSE: %d securities fetched", len(nse_securities))

    # Fetch BSE stocks
    bse_securities = await fetch_bse_equity_list()
    logger.info("BSE: %d securities fetched", len(bse_securities))

    all_securities = nse_securities + bse_securities
    if not all_securities:
        logger.error("No securities fetched. Check internet connection or exchange availability.")
        sys.exit(1)

    inserted = await seed_database(database_url, all_securities)
    logger.info("=" * 60)
    logger.info(
        "Seeding complete: %d securities inserted/updated (NSE: %d, BSE: %d)",
        inserted,
        len(nse_securities),
        len(bse_securities),
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
