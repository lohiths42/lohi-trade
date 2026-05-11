"""In-memory fallback StockUniverseService + SectorService.

Activated when PostgreSQL is unavailable at startup (e.g., single-user
local dev without docker-compose up). Ships a curated list of ~60 Nifty-50
symbols with plausible sector / market-cap metadata so that the UI can
render real content instead of 503 errors.

This is NOT intended to replace the full 5000-symbol catalog served by
the PG-backed service; it's a graceful degradation path for OSS users who
want to see the UI working before connecting a broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional, List


@dataclass
class _Sec:
    """Minimal Security stub matching what routers inspect via getattr."""
    id: int
    symbol: str
    isin: str = ""
    company_name: str = ""
    exchange: str = "NSE"
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap_category: Optional[str] = "large-cap"
    listing_date: Optional[date] = None
    face_value: Optional[Decimal] = None
    status: str = "ACTIVE"
    instrument_type: str = "Stock"


# Curated subset — enough to demonstrate every UI surface.
_SEED: List[_Sec] = [
    _Sec(1, "RELIANCE", "INE002A01018", "Reliance Industries Ltd", "NSE", "Energy", "Refining", "large-cap"),
    _Sec(2, "TCS", "INE467B01029", "Tata Consultancy Services", "NSE", "IT/Technology", "IT Services", "large-cap"),
    _Sec(3, "HDFCBANK", "INE040A01034", "HDFC Bank Ltd", "NSE", "Banking & Finance", "Banks", "large-cap"),
    _Sec(4, "INFY", "INE009A01021", "Infosys Ltd", "NSE", "IT/Technology", "IT Services", "large-cap"),
    _Sec(5, "ICICIBANK", "INE090A01021", "ICICI Bank Ltd", "NSE", "Banking & Finance", "Banks", "large-cap"),
    _Sec(6, "HINDUNILVR", "INE030A01027", "Hindustan Unilever Ltd", "NSE", "FMCG", "Personal Care", "large-cap"),
    _Sec(7, "ITC", "INE154A01025", "ITC Ltd", "NSE", "FMCG", "Tobacco & FMCG", "large-cap"),
    _Sec(8, "LT", "INE018A01030", "Larsen & Toubro Ltd", "NSE", "Infrastructure", "Construction", "large-cap"),
    _Sec(9, "SBIN", "INE062A01020", "State Bank of India", "NSE", "Banking & Finance", "Banks", "large-cap"),
    _Sec(10, "BHARTIARTL", "INE397D01024", "Bharti Airtel Ltd", "NSE", "Telecom", "Telecom Services", "large-cap"),
    _Sec(11, "KOTAKBANK", "INE237A01028", "Kotak Mahindra Bank", "NSE", "Banking & Finance", "Banks", "large-cap"),
    _Sec(12, "AXISBANK", "INE238A01034", "Axis Bank Ltd", "NSE", "Banking & Finance", "Banks", "large-cap"),
    _Sec(13, "BAJFINANCE", "INE296A01024", "Bajaj Finance Ltd", "NSE", "Banking & Finance", "NBFC", "large-cap"),
    _Sec(14, "ASIANPAINT", "INE021A01026", "Asian Paints Ltd", "NSE", "Chemicals", "Paints", "large-cap"),
    _Sec(15, "MARUTI", "INE585B01010", "Maruti Suzuki India", "NSE", "Automobile", "Auto - Passenger", "large-cap"),
    _Sec(16, "HCLTECH", "INE860A01027", "HCL Technologies", "NSE", "IT/Technology", "IT Services", "large-cap"),
    _Sec(17, "WIPRO", "INE075A01022", "Wipro Ltd", "NSE", "IT/Technology", "IT Services", "large-cap"),
    _Sec(18, "SUNPHARMA", "INE044A01036", "Sun Pharmaceutical Ind", "NSE", "Pharma", "Pharmaceuticals", "large-cap"),
    _Sec(19, "TITAN", "INE280A01028", "Titan Company Ltd", "NSE", "FMCG", "Consumer Durables", "large-cap"),
    _Sec(20, "NESTLEIND", "INE239A01016", "Nestle India Ltd", "NSE", "FMCG", "Food Processing", "large-cap"),
    _Sec(21, "POWERGRID", "INE752E01010", "Power Grid Corporation", "NSE", "Energy", "Power Transmission", "large-cap"),
    _Sec(22, "NTPC", "INE733E01010", "NTPC Ltd", "NSE", "Energy", "Power Generation", "large-cap"),
    _Sec(23, "TATAMOTORS", "INE155A01022", "Tata Motors Ltd", "NSE", "Automobile", "Auto - Commercial", "large-cap"),
    _Sec(24, "TATASTEEL", "INE081A01020", "Tata Steel Ltd", "NSE", "Metals & Mining", "Steel", "large-cap"),
    _Sec(25, "ADANIENT", "INE423A01024", "Adani Enterprises", "NSE", "Infrastructure", "Diversified", "large-cap"),
    _Sec(26, "JSWSTEEL", "INE019A01038", "JSW Steel Ltd", "NSE", "Metals & Mining", "Steel", "large-cap"),
    _Sec(27, "ONGC", "INE213A01029", "Oil & Natural Gas Corp", "NSE", "Energy", "Oil Exploration", "large-cap"),
    _Sec(28, "COALINDIA", "INE522F01014", "Coal India Ltd", "NSE", "Metals & Mining", "Coal Mining", "large-cap"),
    _Sec(29, "ULTRACEMCO", "INE481G01011", "UltraTech Cement", "NSE", "Infrastructure", "Cement", "large-cap"),
    _Sec(30, "M&M", "INE101A01026", "Mahindra & Mahindra", "NSE", "Automobile", "Auto - Passenger", "large-cap"),
    _Sec(31, "CIPLA", "INE059A01026", "Cipla Ltd", "NSE", "Pharma", "Pharmaceuticals", "large-cap"),
    _Sec(32, "DRREDDY", "INE089A01023", "Dr. Reddy's Laboratories", "NSE", "Pharma", "Pharmaceuticals", "large-cap"),
    _Sec(33, "DIVISLAB", "INE361B01024", "Divi's Laboratories", "NSE", "Pharma", "Pharmaceuticals", "large-cap"),
    _Sec(34, "GRASIM", "INE047A01021", "Grasim Industries", "NSE", "Infrastructure", "Cement", "large-cap"),
    _Sec(35, "HINDALCO", "INE038A01020", "Hindalco Industries", "NSE", "Metals & Mining", "Aluminum", "large-cap"),
    _Sec(36, "INDUSINDBK", "INE095A01012", "IndusInd Bank", "NSE", "Banking & Finance", "Banks", "large-cap"),
    _Sec(37, "BAJAJFINSV", "INE918I01026", "Bajaj Finserv Ltd", "NSE", "Banking & Finance", "NBFC", "large-cap"),
    _Sec(38, "BAJAJ-AUTO", "INE917I01010", "Bajaj Auto Ltd", "NSE", "Automobile", "Auto - 2W", "large-cap"),
    _Sec(39, "EICHERMOT", "INE066A01021", "Eicher Motors Ltd", "NSE", "Automobile", "Auto - Commercial", "large-cap"),
    _Sec(40, "HEROMOTOCO", "INE158A01026", "Hero MotoCorp Ltd", "NSE", "Automobile", "Auto - 2W", "large-cap"),
    _Sec(41, "TECHM", "INE669C01036", "Tech Mahindra Ltd", "NSE", "IT/Technology", "IT Services", "large-cap"),
    _Sec(42, "BRITANNIA", "INE216A01030", "Britannia Industries", "NSE", "FMCG", "Food Processing", "large-cap"),
    _Sec(43, "APOLLOHOSP", "INE437A01024", "Apollo Hospitals", "NSE", "Pharma", "Healthcare", "large-cap"),
    _Sec(44, "LTIM", "INE214T01019", "LTIMindtree Ltd", "NSE", "IT/Technology", "IT Services", "large-cap"),
    _Sec(45, "ADANIPORTS", "INE742F01042", "Adani Ports & SEZ", "NSE", "Infrastructure", "Ports", "large-cap"),
    _Sec(46, "TATACONSUM", "INE192A01025", "Tata Consumer Products", "NSE", "FMCG", "Food Processing", "large-cap"),
    _Sec(47, "UPL", "INE628A01036", "UPL Ltd", "NSE", "Chemicals", "Agrochemicals", "large-cap"),
    _Sec(48, "SBILIFE", "INE123W01016", "SBI Life Insurance", "NSE", "Insurance", "Insurance", "large-cap"),
    _Sec(49, "HDFCLIFE", "INE795G01014", "HDFC Life Insurance", "NSE", "Insurance", "Insurance", "large-cap"),
    _Sec(50, "ICICIPRULI", "INE726G01019", "ICICI Prudential Life", "NSE", "Insurance", "Insurance", "large-cap"),
    # Mid-caps
    _Sec(51, "PAYTM", "INE982J01020", "One 97 Communications", "NSE", "IT/Technology", "Fintech", "mid-cap"),
    _Sec(52, "ZOMATO", "INE758T01015", "Zomato Ltd", "NSE", "IT/Technology", "Consumer Internet", "mid-cap"),
    _Sec(53, "NYKAA", "INE388Y01029", "FSN E-Commerce Ventures", "NSE", "IT/Technology", "E-Commerce", "mid-cap"),
    _Sec(54, "POLICYBZR", "INE06T801030", "PB Fintech Ltd", "NSE", "IT/Technology", "Fintech", "mid-cap"),
    _Sec(55, "DELHIVERY", "INE148O01028", "Delhivery Ltd", "NSE", "Infrastructure", "Logistics", "mid-cap"),
    _Sec(56, "IRCTC", "INE335Y01020", "IRCTC Ltd", "NSE", "Infrastructure", "Travel Services", "mid-cap"),
    _Sec(57, "DLF", "INE271C01023", "DLF Ltd", "NSE", "Real Estate", "Real Estate", "mid-cap"),
    _Sec(58, "PIDILITIND", "INE318A01026", "Pidilite Industries", "NSE", "Chemicals", "Adhesives", "mid-cap"),
    _Sec(59, "GODREJCP", "INE102D01028", "Godrej Consumer Products", "NSE", "FMCG", "Personal Care", "mid-cap"),
    _Sec(60, "TATAELXSI", "INE670A01012", "Tata Elxsi Ltd", "NSE", "IT/Technology", "Embedded Design", "mid-cap"),
]

_SECTORS = sorted({s.sector for s in _SEED if s.sector})


@dataclass
class _PaginatedResult:
    """Matches app.services.stock_universe_service.PaginatedResult shape."""
    items: list = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1


class FallbackStockUniverseService:
    """Implements the subset of StockUniverseService methods called by routers.

    db_pool is always None so callers that do `svc.db_pool is None` can
    branch cleanly (e.g., skip fundamentals/technicals).
    """

    def __init__(self) -> None:
        self.db_pool = None
        self._by_symbol = {s.symbol: s for s in _SEED}

    async def search_securities(self, q: str, limit: int = 20) -> list[_Sec]:
        needle = (q or "").strip().upper()
        if not needle:
            return _SEED[:limit]
        hits: list[_Sec] = []
        for s in _SEED:
            if (needle in s.symbol
                or needle in s.company_name.upper()
                or needle == s.isin.upper()):
                hits.append(s)
                if len(hits) >= limit:
                    break
        return hits

    async def get_security_by_symbol(self, symbol: str) -> Optional[_Sec]:
        return self._by_symbol.get((symbol or "").upper())

    async def list_securities(
        self,
        exchange: Optional[str] = None,
        sector: Optional[str] = None,
        market_cap_category: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        **kwargs: Any,
    ) -> "_PaginatedResult":
        items = list(_SEED)
        if exchange and exchange != "All":
            items = [s for s in items if s.exchange == exchange]
        if sector and sector != "All":
            items = [s for s in items if s.sector == sector]
        if market_cap_category and market_cap_category != "All":
            items = [s for s in items if s.market_cap_category == market_cap_category]
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        sliced = items[start:end]
        return _PaginatedResult(
            items=sliced,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=max(1, (total + page_size - 1) // page_size),
        )


class FallbackSectorService:
    """Implements the subset of SectorService methods used by routers."""

    def __init__(self) -> None:
        self.db_pool = None

    def get_sectors(self) -> list[str]:
        return list(_SECTORS)

    async def get_sector_aggregate(self, name: str) -> Optional[dict]:
        hits = [s for s in _SEED if s.sector == name]
        if not hits:
            return None
        return {
            "sector": name,
            "total_market_cap": "0",
            "stock_count": len(hits),
            "top_gainers": [],
            "top_losers": [],
        }
