"""Live Data Service — background task that keeps stock data fresh.

Responsibilities:
1. On startup: if securities table is empty, seed from NSE EQUITY_L.csv
2. Every 15 minutes during market hours (9:00–16:00 IST, Mon–Fri):
   refresh fundamentals & technicals in batches via yfinance
3. Daily at 7:00 AM IST: full catalog refresh from NSE CSV
4. Classify market cap categories based on actual market cap values

The service runs as an asyncio background task started from main.py.
"""

import asyncio
import csv
import io
import logging
import math
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

# Market hours (IST)
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(16, 0)

# Refresh intervals
INTRADAY_REFRESH_SECONDS = 15 * 60  # 15 minutes
CATALOG_REFRESH_HOUR = 7  # 7 AM IST daily

# Batch size for yfinance calls
YFINANCE_BATCH_SIZE = 25

# NSE CSV URL
NSE_EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/",
}

# ── Sector classification ───────────────────────────────────────────────────

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Insurance": [
        "insurance", "life insurance", "general insurance", "reinsurance",
    ],
    "Banking & Finance": [
        "bank", "finance", "financial", "nbfc", "credit", "lending",
        "microfinance", "wealth", "capital market", "stock exchange",
        "mutual fund", "asset management", "housing finance",
        "investment", "leasing", "securities", "fincorp", "finserv",
        "fiscal", "holding", "trading", "equity", "etf",
        "home loan", "mercantile", "networth", "corporate serv",
        "advisor", "consult",
    ],
    "IT/Technology": [
        "software", "information technology", "it ", "computer",
        "digital", "cloud", "saas", "internet", "e-commerce", "tech",
        "data processing", "artificial intelligence", "infotech",
        "network", "automation", "electronic", "semiconductor",
        "online", "solution", "infoway", "systems ltd", "systems limited",
    ],
    "Pharma": [
        "pharma", "drug", "healthcare", "hospital", "diagnostic",
        "medical", "biotech", "laboratory", "pathology", "health",
        "bioscien", "lifescien", "therapeut", "surgical", "nutraceut",
        "clinical", "nutri", "ayurved",
    ],
    "FMCG": [
        "consumer", "fmcg", "food", "beverage", "personal care",
        "tobacco", "dairy", "packaged", "household", "detergent",
        "agro", "agri", "agricultur", "cotton", "textile", "garment",
        "apparel", "fabric", "silk", "jute", "wool", "yarn", "fibre",
        "flour", "edible", "rice", "wheat", "jewel", "diamond",
        "cosmetic", "soap", "paper", "newsprint", "sugar", "tea",
        "spice", "confection", "biscuit", "brewer", "footwear",
        "leather", "fashion", "retail", "spirit", "liquor", "distiller",
        "spinning", "weaving", "knit", "denim", "ceramic", "glass",
        "stove", "kitchen", "appliance", "export", "import", "impex",
    ],
    "Energy": [
        "oil", "gas", "petroleum", "power", "energy", "electricity",
        "solar", "wind", "renewable", "coal", "fuel", "refiner",
        "petrochem", "thermal", "hydro", "transformer", "electrical",
        "cable", "drilling", "pipeline", "electro", "switchgear",
        "generator", "turbine", "boiler", "battery", "lamp", "lighting",
    ],
    "Automobile": [
        "auto", "vehicle", "motor", "car", "tractor", "tyre", "tire",
        "two wheeler", "scooter", "motorcycle", "automotive",
        "transmission", "passenger vehicle", "bearing", "brake", "axle",
        "mobility", "electric vehicl",
    ],
    "Metals & Mining": [
        "steel", "iron", "metal", "mining", "aluminium", "aluminum",
        "copper", "zinc", "gold", "silver", "mineral", "ore",
        "alloy", "stainless", "foundry", "casting", "forging",
        "ferro", "tungsten", "titanium", "nickel", "ispat",
        "wire", "precision", "fastener", "forge",
    ],
    "Infrastructure": [
        "infrastructure", "construction", "cement", "road", "highway",
        "railway", "port", "shipping", "logistics", "warehouse",
        "engineering", "epc", "aviation", "airline", "airport",
        "defence", "defense", "shipyard", "dock", "container",
        "transport", "cargo", "freight", "pump", "floor", "tile",
        "sanitar", "crane", "compressor", "project",
    ],
    "Chemicals": [
        "chemical", "specialty chemical", "agrochemical", "fertilizer",
        "pesticide", "paint", "pigment", "dye", "polymer", "plastic",
        "fluorochem", "resin", "solvent", "acid", "rubber", "latex",
        "adhesive", "laminate", "plywood", "synthetic", "vinyl", "epoxy",
        "nitrochem", "coating",
    ],
    "Telecom": [
        "telecom", "communication", "tower", "fiber", "broadband",
        "satellite", "wireless",
    ],
    "Real Estate": [
        "real estate", "property", "housing", "realty", "reit",
        "developer", "builder", "estate",
    ],
    "Media & Entertainment": [
        "media", "entertainment", "broadcast", "film", "television",
        "gaming", "advertising", "print", "publishing", "cinema", "studio",
    ],
}


def _classify_sector(industry: str | None, company_name: str | None = None) -> str:
    """Classify sector from industry string or company name."""
    for text in (industry, company_name):
        if not text:
            continue
        low = text.lower()
        for sector, keywords in SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw in low:
                    return sector
    return "Miscellaneous"


def _classify_market_cap(mc_val) -> str | None:
    """large-cap >= 20000 Cr, mid-cap 5000-20000 Cr, small-cap < 5000 Cr."""
    if mc_val is None:
        return None
    try:
        mc = float(mc_val)
    except (ValueError, TypeError):
        return None
    mc_cr = mc / 1e7  # INR to crores
    if mc_cr >= 20000:
        return "large-cap"
    elif mc_cr >= 5000:
        return "mid-cap"
    return "small-cap"


def _safe_decimal(val, places=2) -> Decimal | None:
    if val is None:
        return None
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        q = Decimal("0." + "0" * places)
        return Decimal(str(val)).quantize(q)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_decimal4(val) -> Decimal | None:
    return _safe_decimal(val, 4)


# ── Core service class ──────────────────────────────────────────────────────


class LiveDataService:
    """Background service that keeps the stock universe fresh."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_catalog_refresh: Optional[date] = None

    async def start(self):
        """Start the background refresh loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("LiveDataService started")

    async def stop(self):
        """Stop the background refresh loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LiveDataService stopped")

    async def _run_loop(self):
        """Main loop: seed if empty, then refresh periodically."""
        try:
            # Step 1: Check if DB needs seeding
            count = await self._get_security_count()
            if count < 3000:
                logger.info("Only %d securities in DB — seeding full NSE + BSE universe...", count)
                await self._seed_from_nse_csv()
                await self._seed_from_bse_api()
                count = await self._get_security_count()
                logger.info("After seeding: %d securities", count)

            # Step 2: Continuous refresh loop
            while self._running:
                now_ist = datetime.now(IST)

                # Daily catalog refresh at 7 AM IST
                if (
                    now_ist.hour == CATALOG_REFRESH_HOUR
                    and self._last_catalog_refresh != now_ist.date()
                ):
                    logger.info("Running daily catalog refresh...")
                    await self._seed_from_nse_csv()
                    await self._seed_from_bse_api()
                    self._last_catalog_refresh = now_ist.date()

                # Refresh fundamentals/technicals during market hours
                # or once after market close
                if self._is_market_time(now_ist) or self._is_post_market(now_ist):
                    logger.info("Refreshing live data (batch)...")
                    await self._refresh_live_data()

                # Sleep until next refresh
                await asyncio.sleep(INTRADAY_REFRESH_SECONDS)

        except asyncio.CancelledError:
            logger.info("LiveDataService loop cancelled")
        except Exception:
            logger.exception("LiveDataService loop crashed")

    @staticmethod
    def _is_market_time(now_ist: datetime) -> bool:
        """Check if current time is during market hours (Mon-Fri 9:00-16:00 IST)."""
        if now_ist.weekday() >= 5:  # Saturday/Sunday
            return False
        return MARKET_OPEN <= now_ist.time() <= MARKET_CLOSE

    @staticmethod
    def _is_post_market(now_ist: datetime) -> bool:
        """Check if we're in the post-market window (16:00-17:00 IST)."""
        if now_ist.weekday() >= 5:
            return False
        return time(16, 0) <= now_ist.time() <= time(17, 0)

    async def _get_security_count(self) -> int:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM securities")
            return row["cnt"] if row else 0

    # ── NSE CSV seeding ─────────────────────────────────────────────────

    async def _seed_from_nse_csv(self):
        """Download NSE EQUITY_L.csv and upsert all securities."""
        securities = await self._fetch_nse_csv()
        if not securities:
            logger.warning("No securities from NSE CSV — skipping seed")
            return

        now = datetime.now(timezone.utc)
        inserted = 0

        async with self.db_pool.acquire() as conn:
            for sec in securities:
                try:
                    await conn.execute(
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
                        """,
                        sec["symbol"], sec["isin"], sec["company_name"],
                        sec["exchange"], sec["sector"], sec.get("industry"),
                        sec.get("market_cap_category"), sec.get("listing_date"),
                        sec.get("face_value"), now,
                    )
                    inserted += 1
                except Exception as e:
                    logger.debug("Upsert failed for %s: %s", sec.get("symbol"), e)

            # Ensure fundamentals/technicals rows exist
            await conn.execute("""
                INSERT INTO security_fundamentals (security_id, updated_at)
                SELECT id, $1 FROM securities
                WHERE id NOT IN (SELECT security_id FROM security_fundamentals)
            """, now)
            await conn.execute("""
                INSERT INTO security_technicals (security_id, updated_at)
                SELECT id, $1 FROM securities
                WHERE id NOT IN (SELECT security_id FROM security_technicals)
            """, now)

        logger.info("NSE CSV seed: %d securities upserted", inserted)

    # ── BSE API seeding ─────────────────────────────────────────────────

    BSE_EQUITY_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Atea=&segment=Equity&status=Active"
    BSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
    }

    async def _seed_from_bse_api(self):
        """Download BSE active equity listing and upsert all securities."""
        securities = await self._fetch_bse_api()
        if not securities:
            logger.warning("No securities from BSE API — skipping BSE seed")
            return

        now = datetime.now(timezone.utc)
        inserted = 0

        async with self.db_pool.acquire() as conn:
            for sec in securities:
                try:
                    # For BSE-only stocks, insert normally.
                    # For dual-listed (same ISIN already exists as NSE), update exchange to BOTH.
                    existing = await conn.fetchrow(
                        "SELECT id, exchange FROM securities WHERE isin = $1",
                        sec["isin"],
                    )
                    if existing:
                        # Already exists — mark as BOTH if it was NSE-only
                        if existing["exchange"] == "NSE":
                            await conn.execute(
                                "UPDATE securities SET exchange = 'BOTH', updated_at = $1 WHERE id = $2",
                                now, existing["id"],
                            )
                        # If already BOTH or BSE, skip
                    else:
                        # New BSE-only stock
                        await conn.execute(
                            """
                            INSERT INTO securities
                                (symbol, isin, company_name, exchange, sector, industry,
                                 market_cap_category, listing_date, face_value, status, updated_at)
                            VALUES ($1, $2, $3, 'BSE', $4, $5, $6, $7, $8, 'ACTIVE', $9)
                            ON CONFLICT (isin) DO NOTHING
                            """,
                            sec["symbol"], sec["isin"], sec["company_name"],
                            sec["sector"], sec.get("industry"),
                            sec.get("market_cap_category"), sec.get("listing_date"),
                            sec.get("face_value"), now,
                        )
                    inserted += 1
                except Exception as e:
                    logger.debug("BSE upsert failed for %s: %s", sec.get("symbol"), e)

            # Ensure fundamentals/technicals rows exist for new securities
            await conn.execute("""
                INSERT INTO security_fundamentals (security_id, updated_at)
                SELECT id, $1 FROM securities
                WHERE id NOT IN (SELECT security_id FROM security_fundamentals)
            """, now)
            await conn.execute("""
                INSERT INTO security_technicals (security_id, updated_at)
                SELECT id, $1 FROM securities
                WHERE id NOT IN (SELECT security_id FROM security_technicals)
            """, now)

        logger.info("BSE API seed: %d securities processed", inserted)

    async def _fetch_bse_api(self) -> list[dict]:
        """Download and parse BSE active equity listing."""
        securities = []
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(self.BSE_EQUITY_API_URL, headers=self.BSE_HEADERS)
                if resp.status_code != 200:
                    logger.warning("BSE API returned %d", resp.status_code)
                    return securities

                data = resp.json()

            if not isinstance(data, list):
                logger.warning("BSE API returned non-list: %s", type(data))
                return securities

            for item in data:
                if not isinstance(item, dict):
                    continue

                scrip_code = str(item.get("Scrip_Code") or item.get("SCRIP_CD") or "").strip()
                symbol = (item.get("scrip_id") or item.get("SCRIP_ID") or "").strip()
                isin = (item.get("ISIN_NUMBER") or item.get("Isin_Number") or "").strip()
                company_name = (item.get("Scrip_Name") or item.get("SCRIP_NAME") or
                                item.get("LongName") or item.get("LONG_NAME") or "").strip()
                industry = (item.get("Industry") or item.get("INDUSTRY") or "").strip()
                group = (item.get("Scrip_Group") or item.get("GROUP") or "").strip()
                face_value_str = str(item.get("Face_Value") or item.get("FACE_VALUE") or "").strip()

                if not symbol and scrip_code:
                    symbol = scrip_code
                if not isin or not symbol:
                    continue
                # Skip non-equity groups
                if group and group.upper() in ("W", "MF", "IF", "DB", "G", "GS"):
                    continue
                # Skip numeric-prefix symbols (segregated portfolios, MF units)
                if symbol and symbol[0].isdigit():
                    continue

                face_value = None
                try:
                    face_value = Decimal(face_value_str) if face_value_str else None
                except (InvalidOperation, ValueError):
                    pass

                securities.append({
                    "symbol": symbol.upper(),
                    "isin": isin.upper().strip(),
                    "company_name": company_name or symbol,
                    "exchange": "BSE",
                    "sector": _classify_sector(industry, company_name),
                    "industry": industry or None,
                    "market_cap_category": None,
                    "listing_date": None,
                    "face_value": face_value,
                })

            logger.info("Parsed %d securities from BSE API", len(securities))
        except Exception:
            logger.exception("Failed to fetch/parse BSE API")

        return securities

    async def _fetch_nse_csv(self) -> list[dict]:
        """Download and parse NSE EQUITY_L.csv."""
        securities = []
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                # Hit NSE homepage first for cookies
                try:
                    await client.get("https://www.nseindia.com/", headers=NSE_HEADERS)
                except Exception:
                    pass

                resp = await client.get(NSE_EQUITY_CSV_URL, headers=NSE_HEADERS)
                if resp.status_code != 200:
                    logger.warning("NSE CSV returned %d", resp.status_code)
                    return securities

                text = resp.text

            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                symbol = (row.get("SYMBOL") or "").strip()
                isin = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip()
                name = (row.get("NAME OF COMPANY") or "").strip()
                industry = (row.get(" INDUSTRY") or row.get("INDUSTRY") or "").strip()
                listing_str = (row.get(" DATE OF LISTING") or row.get("DATE OF LISTING") or "").strip()
                fv_str = (row.get(" FACE VALUE") or row.get("FACE VALUE") or "").strip()

                if not symbol or not isin:
                    continue

                listing_date = None
                for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        listing_date = datetime.strptime(listing_str, fmt).date()
                        break
                    except ValueError:
                        continue

                face_value = None
                try:
                    face_value = Decimal(fv_str) if fv_str else None
                except (InvalidOperation, ValueError):
                    pass

                securities.append({
                    "symbol": symbol.upper(),
                    "isin": isin.upper().strip(),
                    "company_name": name or symbol,
                    "exchange": "NSE",
                    "sector": _classify_sector(industry, name),
                    "industry": industry or None,
                    "market_cap_category": None,
                    "listing_date": listing_date,
                    "face_value": face_value,
                })

            logger.info("Parsed %d securities from NSE CSV", len(securities))
        except Exception:
            logger.exception("Failed to fetch/parse NSE CSV")

        return securities

    # ── Live data refresh via yfinance ──────────────────────────────────

    async def _refresh_live_data(self):
        """Refresh fundamentals & technicals for stocks in batches.

        Prioritizes stocks that haven't been updated recently.
        Processes YFINANCE_BATCH_SIZE stocks per cycle to avoid rate limits.
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance not installed — cannot refresh live data")
            return

        # Get stocks needing refresh (oldest updated_at first)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.id, s.symbol
                FROM securities s
                LEFT JOIN security_technicals st ON st.security_id = s.id
                WHERE s.status = 'ACTIVE'
                ORDER BY st.updated_at ASC NULLS FIRST
                LIMIT $1
            """, YFINANCE_BATCH_SIZE * 5)  # Fetch more, process in batches

        if not rows:
            return

        symbols = [(r["id"], r["symbol"]) for r in rows]

        # Process in batches
        for i in range(0, min(len(symbols), YFINANCE_BATCH_SIZE * 5), YFINANCE_BATCH_SIZE):
            batch = symbols[i:i + YFINANCE_BATCH_SIZE]
            yf_symbols = [f"{sym}.NS" for _, sym in batch]

            try:
                # Run yfinance in a thread to avoid blocking the event loop.
                # `to_thread` replaces the deprecated
                # `asyncio.get_event_loop().run_in_executor(None, …)` pattern
                # and is safe on Python 3.10+ running inside a coroutine.
                data = await asyncio.to_thread(self._fetch_yfinance_batch, yf_symbols)

                now = datetime.now(timezone.utc)
                async with self.db_pool.acquire() as conn:
                    for (sec_id, sym), yf_sym in zip(batch, yf_symbols):
                        info = data.get(yf_sym)
                        if not info:
                            continue

                        market_cap = info.get("market_cap")
                        mc_category = _classify_market_cap(market_cap)

                        # Update market_cap_category on securities table
                        if mc_category:
                            await conn.execute(
                                "UPDATE securities SET market_cap_category = $1, updated_at = $2 WHERE id = $3",
                                mc_category, now, sec_id,
                            )

                        # Update sector/industry from yfinance if currently Miscellaneous/None
                        yf_sector = info.get("yf_sector")
                        yf_industry = info.get("yf_industry")
                        if yf_sector or yf_industry:
                            mapped_sector = _map_yfinance_sector(yf_sector)
                            await conn.execute("""
                                UPDATE securities SET
                                    sector = CASE WHEN sector = 'Miscellaneous' OR sector IS NULL
                                                  THEN $1 ELSE sector END,
                                    industry = COALESCE($2, industry),
                                    market_cap_category = COALESCE($3, market_cap_category),
                                    updated_at = $4
                                WHERE id = $5
                            """, mapped_sector, yf_industry, mc_category, now, sec_id)

                        # Update fundamentals
                        await conn.execute("""
                            UPDATE security_fundamentals SET
                                pe_ratio = COALESCE($2, pe_ratio),
                                pb_ratio = COALESCE($3, pb_ratio),
                                market_cap = COALESCE($4, market_cap),
                                dividend_yield = COALESCE($5, dividend_yield),
                                eps = COALESCE($6, eps),
                                roe = COALESCE($7, roe),
                                debt_to_equity = COALESCE($8, debt_to_equity),
                                revenue_growth_1y = COALESCE($9, revenue_growth_1y),
                                high_52w = COALESCE($10, high_52w),
                                low_52w = COALESCE($11, low_52w),
                                updated_at = $12
                            WHERE security_id = $1
                        """,
                            sec_id,
                            _safe_decimal(info.get("pe_ratio")),
                            _safe_decimal(info.get("pb_ratio")),
                            _safe_decimal(market_cap),
                            _safe_decimal(info.get("dividend_yield")),
                            _safe_decimal(info.get("eps")),
                            _safe_decimal(info.get("roe")),
                            _safe_decimal(info.get("debt_to_equity")),
                            _safe_decimal(info.get("revenue_growth_1y")),
                            _safe_decimal(info.get("high_52w")),
                            _safe_decimal(info.get("low_52w")),
                            now,
                        )

                        # Update technicals
                        await conn.execute("""
                            UPDATE security_technicals SET
                                rsi_14 = COALESCE($2, rsi_14),
                                sma_50 = COALESCE($3, sma_50),
                                sma_200 = COALESCE($4, sma_200),
                                avg_volume_20d = COALESCE($5, avg_volume_20d),
                                price_change_1d = COALESCE($6, price_change_1d),
                                price_change_1w = COALESCE($7, price_change_1w),
                                price_change_1m = COALESCE($8, price_change_1m),
                                price_change_3m = COALESCE($9, price_change_3m),
                                price_change_6m = COALESCE($10, price_change_6m),
                                price_change_1y = COALESCE($11, price_change_1y),
                                updated_at = $12
                            WHERE security_id = $1
                        """,
                            sec_id,
                            _safe_decimal(info.get("rsi_14")),
                            _safe_decimal(info.get("sma_50")),
                            _safe_decimal(info.get("sma_200")),
                            info.get("avg_volume_20d"),
                            _safe_decimal4(info.get("price_change_1d")),
                            _safe_decimal4(info.get("price_change_1w")),
                            _safe_decimal4(info.get("price_change_1m")),
                            _safe_decimal4(info.get("price_change_3m")),
                            _safe_decimal4(info.get("price_change_6m")),
                            _safe_decimal4(info.get("price_change_1y")),
                            now,
                        )

                logger.info("Refreshed batch %d-%d (%d symbols)",
                            i + 1, i + len(batch), len(batch))

            except Exception:
                logger.exception("Failed to refresh batch %d-%d", i + 1, i + len(batch))

            # Small delay between batches to be nice to yfinance
            await asyncio.sleep(2)

    @staticmethod
    def _fetch_yfinance_batch(yf_symbols: list[str]) -> dict[str, dict]:
        """Fetch stock info from yfinance (runs in thread pool).

        Returns {yf_symbol: {pe_ratio, pb_ratio, market_cap, ...}}.
        Uses fast_info where available, falls back to .info for fundamentals.
        """
        import yfinance as yf

        result = {}
        try:
            # First, try bulk download for price data (much faster)
            try:
                hist_data = yf.download(
                    " ".join(yf_symbols),
                    period="1y",
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )
            except Exception:
                hist_data = None

            for yf_sym in yf_symbols:
                try:
                    ticker = yf.Ticker(yf_sym)

                    # Try fast_info first (much faster than .info)
                    fi = None
                    try:
                        fi = ticker.fast_info
                    except Exception:
                        pass

                    info = {}
                    try:
                        info = ticker.info or {}
                    except Exception:
                        pass

                    # Skip if no data at all
                    if not fi and not info.get("symbol") and not info.get("shortName"):
                        # Try BSE suffix as fallback
                        bse_sym = yf_sym.replace(".NS", ".BO")
                        try:
                            ticker = yf.Ticker(bse_sym)
                            fi = ticker.fast_info
                            info = ticker.info or {}
                            if not fi and not info.get("symbol"):
                                continue
                        except Exception:
                            continue

                    # Extract market cap
                    market_cap = None
                    if fi:
                        try:
                            market_cap = fi.market_cap
                        except Exception:
                            pass
                    if not market_cap:
                        market_cap = info.get("marketCap")

                    # Get historical data for price changes and RSI
                    hist = None
                    try:
                        if hist_data is not None and len(yf_symbols) > 1:
                            try:
                                hist = hist_data[yf_sym] if yf_sym in hist_data.columns.get_level_values(0) else None
                            except Exception:
                                hist = None
                        if hist is None or (hasattr(hist, 'empty') and hist.empty):
                            hist = ticker.history(period="1y")
                    except Exception:
                        pass

                    price_changes = _compute_price_changes(hist)
                    rsi = _compute_rsi(hist)

                    div_yield = info.get("dividendYield")
                    roe = info.get("returnOnEquity")
                    rev_growth = info.get("revenueGrowth")

                    # Get 50/200 day averages
                    sma_50 = info.get("fiftyDayAverage")
                    sma_200 = info.get("twoHundredDayAverage")
                    if not sma_50 and fi:
                        try:
                            sma_50 = fi.fifty_day_average
                        except Exception:
                            pass
                    if not sma_200 and fi:
                        try:
                            sma_200 = fi.two_hundred_day_average
                        except Exception:
                            pass

                    result[yf_sym] = {
                        "yf_sector": info.get("sector"),
                        "yf_industry": info.get("industry"),
                        "pe_ratio": info.get("trailingPE"),
                        "pb_ratio": info.get("priceToBook"),
                        "market_cap": market_cap,
                        "dividend_yield": (div_yield * 100) if div_yield else None,
                        "eps": info.get("trailingEps"),
                        "roe": (roe * 100) if roe else None,
                        "debt_to_equity": info.get("debtToEquity"),
                        "revenue_growth_1y": (rev_growth * 100) if rev_growth else None,
                        "high_52w": info.get("fiftyTwoWeekHigh"),
                        "low_52w": info.get("fiftyTwoWeekLow"),
                        "rsi_14": rsi,
                        "sma_50": sma_50,
                        "sma_200": sma_200,
                        "avg_volume_20d": info.get("averageVolume"),
                        **price_changes,
                    }
                except Exception:
                    continue
        except Exception:
            pass

        return result


# ── Helper functions ────────────────────────────────────────────────────────

# Map yfinance sector names to our 15 predefined sectors
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


def _map_yfinance_sector(yf_sector: str | None) -> str:
    """Map a yfinance sector name to our predefined sector list."""
    if not yf_sector:
        return "Miscellaneous"
    return _YF_SECTOR_MAP.get(yf_sector, "Miscellaneous")


def _compute_rsi(hist, period=14) -> float | None:
    if hist is None or len(hist) < period + 1:
        return None
    try:
        close = hist["Close"].values
        deltas = [close[i] - close[i - 1] for i in range(1, len(close))]
        recent = deltas[-period:]
        gains = [d for d in recent if d > 0]
        losses = [-d for d in recent if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        return 100 - (100 / (1 + rs))
    except Exception:
        return None


def _compute_price_changes(hist) -> dict:
    result = {
        "price_change_1d": None, "price_change_1w": None,
        "price_change_1m": None, "price_change_3m": None,
        "price_change_6m": None, "price_change_1y": None,
    }
    if hist is None or len(hist) < 2:
        return result
    try:
        close = hist["Close"]
        current = float(close.iloc[-1])
        periods = {
            "price_change_1d": 1, "price_change_1w": 5,
            "price_change_1m": 21, "price_change_3m": 63,
            "price_change_6m": 126, "price_change_1y": 252,
        }
        for key, days in periods.items():
            if len(close) > days:
                past = float(close.iloc[-days - 1])
                if past > 0:
                    result[key] = ((current - past) / past) * 100
    except Exception:
        pass
    return result
