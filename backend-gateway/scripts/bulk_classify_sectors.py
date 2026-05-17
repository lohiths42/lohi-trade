#!/usr/bin/env python3
"""Bulk sector classification script for all stocks.

Phase 1: Company-name-based heuristic (instant, no API calls)
Phase 2: yfinance bulk fetch for remaining Miscellaneous stocks (parallel batches)

Usage:
    cd backend-gateway
    python -m scripts.bulk_classify_sectors
"""

import asyncio
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Company name → sector heuristic keywords ────────────────────────────────
# Order matters: more specific patterns first to avoid false positives.

NAME_SECTOR_RULES: list[tuple[str, list[str]]] = [
    (
        "Insurance",
        [
            r"\binsurance\b",
            r"\blife\s+ins",
            r"\bgeneral\s+ins",
            r"\breinsur",
            r"\binsure\b",
        ],
    ),
    (
        "Banking & Finance",
        [
            r"\bbank\b",
            r"\bbanking\b",
            r"\bnbfc\b",
            r"\bfinance\b",
            r"\bfinancial\b",
            r"\bcredit\b",
            r"\blending\b",
            r"\bmicrofinance\b",
            r"\bwealth\b",
            r"\bcapital\s+market",
            r"\bstock\s+exchange",
            r"\basset\s+manage",
            r"\bhousing\s+finance",
            r"\binvestment\b",
            r"\bleasing\b",
            r"\bsecurities\b",
            r"\bfincorp\b",
            r"\bfinserv\b",
            r"\bfin\s+serv",
            r"\bfinvest\b",
            r"\bfintec",
            r"\bnidhi\b",
            r"\bfiscal\b",
            r"\bholding",
            r"\btrading\b",
            r"\bventure\b",
            r"\bequity\b",
            r"\bmutual\s+fund",
            r"\betf\b",
            r"\bindex\s+fund",
        ],
    ),
    (
        "IT/Technology",
        [
            r"\bsoftware\b",
            r"\binformation\s+tech",
            r"\binfotech\b",
            r"\binfo\s+tech",
            r"\bcomputer\b",
            r"\bdigital\b",
            r"\bcloud\b",
            r"\bsaas\b",
            r"\binternet\b",
            r"\be-commerce\b",
            r"\btechnolog",
            r"\bdata\s+proc",
            r"\bcyber\b",
            r"\bsystem\b.*\btech",
            r"\btech\s+ltd",
            r"\btechno\b",
            r"\btechsys\b",
            r"\bi\.?t\.?\b",
            r"\bsgs\s+tech",
            r"\binfoway\b",
            r"\bnetwork\b",
            r"\bautomation\b",
            r"\bsystems?\s+ltd",
            r"\bsystems?\s+limited",
            r"\belectronic",
            r"\bsemiconductor\b",
        ],
    ),
    (
        "AI/Deep Tech",
        [
            r"\bartificial\s+intell",
            r"\bai\s+",
            r"\bmachine\s+learn",
            r"\bdeep\s+tech",
            r"\brobotics?\b",
            r"\bneural\b",
        ],
    ),
    (
        "Pharma",
        [
            r"\bpharma\b",
            r"\bdrug\b",
            r"\bhealthcare\b",
            r"\bhospital\b",
            r"\bdiagnostic\b",
            r"\bmedical\b",
            r"\bbiotech\b",
            r"\blaborator",
            r"\bpatholog",
            r"\bhealth\b",
            r"\bbioscien",
            r"\blifescien",
            r"\bcure\b",
            r"\btherapeu",
            r"\boncolog",
            r"\bnutraceut",
            r"\bclinical\b",
            r"\bsurgical\b",
        ],
    ),
    (
        "FMCG",
        [
            r"\bconsumer\b",
            r"\bfmcg\b",
            r"\bfood\b",
            r"\bbeverage\b",
            r"\bpersonal\s+care",
            r"\btobacco\b",
            r"\bdairy\b",
            r"\bpackaged\b",
            r"\bhousehold\b",
            r"\bdetergent\b",
            r"\btea\b.*\bltd",
            r"\bspice",
            r"\bsugar\b",
            r"\bconfection",
            r"\bbiscuit\b",
            r"\bbrewer",
            r"\bagro\b",
            r"\bagri\b",
            r"\bagricultur",
            r"\bcotton\b",
            r"\btextile\b",
            r"\bgarment\b",
            r"\bapparel\b",
            r"\bfabric\b",
            r"\bsilk\b",
            r"\bjute\b",
            r"\bwool\b",
            r"\byarn\b",
            r"\bfibre\b",
            r"\bflour\b",
            r"\bedible\b",
            r"\brice\b",
            r"\bwheat\b",
            r"\bjewel",
            r"\bgems?\b",
            r"\bdiamond\b",
            r"\bornament",
            r"\bcosmet",
            r"\bsoap\b",
            r"\bpaper\b",
            r"\bnewsprint",
        ],
    ),
    (
        "Energy",
        [
            r"\boil\b",
            r"\bgas\b",
            r"\bpetroleum\b",
            r"\bpower\b",
            r"\benergy\b",
            r"\belectricit",
            r"\bsolar\b",
            r"\bwind\b",
            r"\brenewable\b",
            r"\bcoal\b",
            r"\bfuel\b",
            r"\brefiner",
            r"\bpetrochem",
            r"\bpowergensys\b",
            r"\bthermal\b",
            r"\bhydro\b",
            r"\btransformer\b",
            r"\belectrical\b",
            r"\bcable\b",
            r"\bdrilling\b",
            r"\bpipeline\b",
        ],
    ),
    (
        "Automobile",
        [
            r"\bauto\b",
            r"\bvehicle\b",
            r"\bmotor\b",
            r"\bcar\b.*\bltd",
            r"\btractor\b",
            r"\btyre\b",
            r"\btire\b",
            r"\btwo\s+wheeler",
            r"\bscooter\b",
            r"\bmotorcycl",
            r"\bautomobil",
            r"\bautomotive\b",
            r"\bgoodyear\b",
            r"\bmrf\b",
            r"\bceat\b",
            r"\bapollo\s+tyre",
            r"\btransmission",
            r"\bpassenger\s+vehicle",
            r"\bev\b",
            r"\bbearing\b",
            r"\bbrake\b",
            r"\baxle\b",
        ],
    ),
    (
        "Metals & Mining",
        [
            r"\bsteel\b",
            r"\biron\b",
            r"\bmetal\b",
            r"\bmining\b",
            r"\balumini?um\b",
            r"\bcopper\b",
            r"\bzinc\b",
            r"\bgold\b",
            r"\bsilver\b",
            r"\bmineral\b",
            r"\bore\b",
            r"\bbimetal\b",
            r"\bhindalco\b",
            r"\btata\s+steel",
            r"\bjsw\s+steel",
            r"\bvedanta\b",
            r"\bnmdc\b",
            r"\bsail\b",
            r"\balloy",
            r"\bstainless\b",
            r"\bfoundry\b",
            r"\bfoundr",
            r"\bcasting\b",
            r"\bforging\b",
            r"\bferro\b",
            r"\btungsten\b",
            r"\btitanium\b",
            r"\bnickel\b",
            r"\btin\b.*\bltd",
            r"\blead\b.*\bltd",
        ],
    ),
    (
        "Infrastructure",
        [
            r"\binfra\b",
            r"\bconstruct",
            r"\bcement\b",
            r"\broad\b",
            r"\bhighway\b",
            r"\brailway\b",
            r"\bport\b",
            r"\bshipping\b",
            r"\blogistic",
            r"\bwarehouse\b",
            r"\bengineering\b",
            r"\bepc\b",
            r"\bbridge\b",
            r"\bpipe\s+ind",
            r"\bpipe\b.*\bltd",
            r"\baviation\b",
            r"\bairline\b",
            r"\bairport\b",
            r"\bdefence\b",
            r"\bdefense\b",
            r"\bshipyard\b",
            r"\bdock\b",
            r"\bcontainer\b",
            r"\btransport\b",
            r"\bcargo\b",
            r"\bfreight\b",
            r"\bproject\b.*\bltd",
            r"\bproject\b.*\blimited",
        ],
    ),
    (
        "Chemicals",
        [
            r"\bchemical\b",
            r"\bagrochemical\b",
            r"\bfertiliz",
            r"\bpesticid",
            r"\bpaint\b",
            r"\bpigment\b",
            r"\bdye\b",
            r"\bpolymer\b",
            r"\bplastic\b",
            r"\bplascon\b",
            r"\bmica\b",
            r"\bfluorochem",
            r"\bresin\b",
            r"\bsolvent\b",
            r"\bacid\b",
            r"\bchemie\b",
            r"\bchemist\b",
        ],
    ),
    (
        "Telecom",
        [
            r"\btelecom\b",
            r"\bcommunication\b",
            r"\btower\b.*\bltd",
            r"\bfiber\b",
            r"\bbroadband\b",
            r"\bsatellite\b",
            r"\bwireless\b",
            r"\bbharti\b",
            r"\bairtel\b",
            r"\bjio\b",
            r"\bvodafone\b",
        ],
    ),
    (
        "Real Estate",
        [
            r"\breal\s+estate\b",
            r"\bproperty\b",
            r"\bhousing\b",
            r"\brealty\b",
            r"\breit\b",
            r"\bdlf\b",
            r"\bgodrej\s+prop",
            r"\boberoirealty\b",
            r"\bdeveloper\b",
            r"\bbuilder\b",
        ],
    ),
    (
        "Media & Entertainment",
        [
            r"\bmedia\b",
            r"\bentertainment\b",
            r"\bbroadcast\b",
            r"\bfilm\b",
            r"\btelevision\b",
            r"\bgaming\b",
            r"\badvertis",
            r"\bprint\b",
            r"\bpublish",
            r"\bnews\b.*\bltd",
            r"\bcinema\b",
            r"\bstudio\b",
        ],
    ),
]

# Compile patterns once
_COMPILED_RULES: list[tuple[str, list[re.Pattern]]] = [
    (sector, [re.compile(p, re.IGNORECASE) for p in patterns])
    for sector, patterns in NAME_SECTOR_RULES
]


def classify_by_name(company_name: str) -> str | None:
    """Classify sector from company name using regex patterns.
    Returns sector name or None if no match.
    """
    if not company_name:
        return None
    for sector, patterns in _COMPILED_RULES:
        for pat in patterns:
            if pat.search(company_name):
                return sector
    return None


# ── yfinance sector mapping (same as live_data_service.py) ──────────────────

_YF_SECTOR_MAP = {
    "Financial Services": "Banking & Finance",
    "Financials": "Banking & Finance",
    "Technology": "IT/Technology",
    "Information Technology": "IT/Technology",
    "Communication Services": "Telecom",
    "Healthcare": "Pharma",
    "Consumer Defensive": "FMCG",
    "Consumer Staples": "FMCG",
    "Consumer Cyclical": "FMCG",
    "Consumer Discretionary": "FMCG",
    "Energy": "Energy",
    "Utilities": "Energy",
    "Industrials": "Infrastructure",
    "Basic Materials": "Metals & Mining",
    "Materials": "Metals & Mining",
    "Real Estate": "Real Estate",
}


def map_yf_sector(yf_sector: str | None) -> str:
    if not yf_sector:
        return "Miscellaneous"
    return _YF_SECTOR_MAP.get(yf_sector, "Miscellaneous")


def fetch_yf_sector(symbol: str) -> tuple[str, str | None, str | None]:
    """Fetch sector from yfinance for a single symbol. Returns (symbol, sector, industry)."""
    import yfinance as yf

    for suffix in (".NS", ".BO"):
        try:
            t = yf.Ticker(symbol + suffix)
            info = t.info or {}
            yf_sector = info.get("sector")
            yf_industry = info.get("industry")
            if yf_sector:
                return (symbol, map_yf_sector(yf_sector), yf_industry)
        except Exception:
            continue
    return (symbol, None, None)


# ── Main logic ──────────────────────────────────────────────────────────────

YFINANCE_BATCH = 50  # parallel threads per batch
YFINANCE_MAX_STOCKS = 5000  # max stocks to process via yfinance


async def main():
    from dotenv import load_dotenv

    for env_path in [_root / ".env", _root.parent / ".env"]:
        if env_path.exists():
            load_dotenv(env_path)
            break

    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "postgresql://lohi:lohi@localhost:5432/lohitrade")
    pool = await asyncpg.create_pool(dsn=database_url, min_size=2, max_size=10)
    now = datetime.now(timezone.utc)

    # ── Phase 1: Name-based heuristic ───────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 1: Company name-based sector classification")
    logger.info("=" * 60)

    async with pool.acquire() as conn:
        misc_rows = await conn.fetch(
            "SELECT id, symbol, company_name FROM securities WHERE sector = 'Miscellaneous' OR sector IS NULL"
        )
    logger.info("Found %d stocks with Miscellaneous/NULL sector", len(misc_rows))

    phase1_updates = 0
    async with pool.acquire() as conn:
        for row in misc_rows:
            sector = classify_by_name(row["company_name"])
            if sector:
                await conn.execute(
                    "UPDATE securities SET sector = $1, updated_at = $2 WHERE id = $3",
                    sector,
                    now,
                    row["id"],
                )
                phase1_updates += 1

    logger.info("Phase 1 complete: %d stocks classified by company name", phase1_updates)

    # Show distribution after phase 1
    async with pool.acquire() as conn:
        dist = await conn.fetch(
            "SELECT sector, COUNT(*) as cnt FROM securities GROUP BY sector ORDER BY cnt DESC"
        )
        for r in dist:
            logger.info("  %-25s %d", r["sector"], r["cnt"])

    # ── Phase 2: yfinance bulk fetch for remaining Miscellaneous ────────
    logger.info("=" * 60)
    logger.info("PHASE 2: yfinance sector enrichment for remaining Miscellaneous stocks")
    logger.info("=" * 60)

    async with pool.acquire() as conn:
        remaining = await conn.fetch(
            "SELECT id, symbol FROM securities WHERE sector = 'Miscellaneous' OR sector IS NULL ORDER BY symbol LIMIT $1",
            YFINANCE_MAX_STOCKS,
        )
    logger.info("Remaining Miscellaneous stocks to process via yfinance: %d", len(remaining))

    if not remaining:
        logger.info("No stocks need yfinance enrichment. Done!")
        await pool.close()
        return

    # Process in parallel batches using ThreadPoolExecutor
    phase2_updates = 0
    total_processed = 0
    symbols_map = {r["symbol"]: r["id"] for r in remaining}
    symbol_list = list(symbols_map.keys())

    for batch_start in range(0, len(symbol_list), YFINANCE_BATCH):
        batch = symbol_list[batch_start : batch_start + YFINANCE_BATCH]
        total_processed += len(batch)

        logger.info(
            "Processing batch %d-%d of %d...",
            batch_start + 1,
            batch_start + len(batch),
            len(symbol_list),
        )

        # Parallel yfinance calls
        with ThreadPoolExecutor(max_workers=min(20, len(batch))) as executor:
            results = list(executor.map(fetch_yf_sector, batch))

        # Update DB
        async with pool.acquire() as conn:
            for symbol, sector, industry in results:
                if sector and sector != "Miscellaneous":
                    sec_id = symbols_map[symbol]
                    await conn.execute(
                        "UPDATE securities SET sector = $1, industry = COALESCE($2, industry), updated_at = $3 WHERE id = $4",
                        sector,
                        industry,
                        now,
                        sec_id,
                    )
                    phase2_updates += 1

        logger.info(
            "  Batch done: %d/%d classified so far (phase 2)", phase2_updates, total_processed
        )

        # Small delay between batches
        await asyncio.sleep(1)

    logger.info("Phase 2 complete: %d stocks classified via yfinance", phase2_updates)

    # ── Final distribution ──────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("FINAL SECTOR DISTRIBUTION")
    logger.info("=" * 60)
    async with pool.acquire() as conn:
        dist = await conn.fetch(
            "SELECT sector, COUNT(*) as cnt FROM securities GROUP BY sector ORDER BY cnt DESC"
        )
        for r in dist:
            logger.info("  %-25s %d", r["sector"], r["cnt"])
        total = await conn.fetchrow("SELECT COUNT(*) as cnt FROM securities")
        logger.info("  %-25s %d", "TOTAL", total["cnt"])

    await pool.close()
    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
