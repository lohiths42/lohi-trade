"""
Ticker mapping for entity resolution in LOHI-TRADE.

This module provides fuzzy matching capabilities to map company names
extracted from news articles to NSE ticker symbols. It supports 500+
company name variations and uses rapidfuzz for fuzzy string matching.

Requirements: 6.2, 6.5, 6.6
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    logging.warning("rapidfuzz not available, fuzzy matching will be disabled")


logger = logging.getLogger(__name__)


class TickerMapper:
    """
    Maps company names to NSE ticker symbols with fuzzy matching support.
    
    The ticker mapper maintains a dictionary of company name variations
    to ticker symbols and provides fuzzy matching to handle variations
    in company names found in news articles.
    
    Requirements: 6.2, 6.5, 6.6
    """
    
    def __init__(self, data_dir: str = "data", fuzzy_threshold: float = 0.85):
        """
        Initialize ticker mapper.
        
        Args:
            data_dir: Directory containing ticker_map.json
            fuzzy_threshold: Minimum similarity score for fuzzy matching (0.0-1.0)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.fuzzy_threshold = fuzzy_threshold
        self.ticker_map: Dict[str, str] = {}
        self.reverse_map: Dict[str, List[str]] = {}  # ticker -> list of company names
    
    def load_from_file(self, filename: str = "ticker_map.json") -> bool:
        """
        Load ticker mapping from JSON file.
        
        Args:
            filename: Name of ticker mapping file
            
        Returns:
            True if load successful, False otherwise
            
        Requirements: 6.2
        """
        try:
            filepath = self.data_dir / filename
            
            if not filepath.exists():
                logger.warning(f"Ticker map file not found: {filepath}")
                return False
            
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Load mappings
            self.ticker_map = data.get('mappings', {})
            
            # Build reverse map for lookups
            self._build_reverse_map()
            
            logger.info(f"Loaded {len(self.ticker_map)} ticker mappings from {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load ticker map: {e}", exc_info=True)
            return False
    
    def save_to_file(self, filename: str = "ticker_map.json") -> bool:
        """
        Save ticker mapping to JSON file.
        
        Args:
            filename: Name of ticker mapping file
            
        Returns:
            True if save successful, False otherwise
        """
        try:
            filepath = self.data_dir / filename
            
            data = {
                "description": "Company name to NSE ticker symbol mapping",
                "fuzzy_threshold": self.fuzzy_threshold,
                "mappings": self.ticker_map
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Saved {len(self.ticker_map)} ticker mappings to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save ticker map: {e}", exc_info=True)
            return False
    
    def _build_reverse_map(self) -> None:
        """Build reverse mapping from ticker to company names."""
        self.reverse_map = {}
        for company_name, ticker in self.ticker_map.items():
            if ticker not in self.reverse_map:
                self.reverse_map[ticker] = []
            self.reverse_map[ticker].append(company_name)
    
    def add_mapping(self, company_name: str, ticker: str) -> None:
        """
        Add a company name to ticker mapping.
        
        Args:
            company_name: Company name or variation
            ticker: NSE ticker symbol
        """
        # Normalize company name (lowercase, strip whitespace)
        normalized_name = company_name.strip().lower()
        self.ticker_map[normalized_name] = ticker.upper()
        
        # Update reverse map
        if ticker.upper() not in self.reverse_map:
            self.reverse_map[ticker.upper()] = []
        if normalized_name not in self.reverse_map[ticker.upper()]:
            self.reverse_map[ticker.upper()].append(normalized_name)
    
    def get_ticker(self, company_name: str, use_fuzzy: bool = True) -> Optional[str]:
        """
        Get ticker symbol for a company name.
        
        Args:
            company_name: Company name to look up
            use_fuzzy: Whether to use fuzzy matching if exact match not found
            
        Returns:
            Ticker symbol or None if not found
            
        Requirements: 6.2, 6.5
        """
        # Normalize input
        normalized_name = company_name.strip().lower()
        
        # Try exact match first
        if normalized_name in self.ticker_map:
            return self.ticker_map[normalized_name]
        
        # Try fuzzy matching if enabled and rapidfuzz is available
        if use_fuzzy and RAPIDFUZZ_AVAILABLE and self.ticker_map:
            match = self._fuzzy_match(normalized_name)
            if match:
                return match
        
        # No match found
        logger.debug(f"No ticker mapping found for: {company_name}")
        return None
    
    def _fuzzy_match(self, company_name: str) -> Optional[str]:
        """
        Perform fuzzy matching to find best ticker match.
        
        Args:
            company_name: Company name to match
            
        Returns:
            Ticker symbol or None if no match above threshold
            
        Requirements: 6.5
        """
        if not RAPIDFUZZ_AVAILABLE:
            return None
        
        try:
            # Find best match using rapidfuzz
            result = process.extractOne(
                company_name,
                self.ticker_map.keys(),
                scorer=fuzz.ratio,
                score_cutoff=self.fuzzy_threshold * 100  # rapidfuzz uses 0-100 scale
            )
            
            if result:
                matched_name, score, _ = result
                ticker = self.ticker_map[matched_name]
                logger.debug(f"Fuzzy matched '{company_name}' to '{matched_name}' (score: {score:.1f}) -> {ticker}")
                return ticker
            
            return None
            
        except Exception as e:
            logger.error(f"Error in fuzzy matching: {e}")
            return None
    
    def get_company_names(self, ticker: str) -> List[str]:
        """
        Get all company name variations for a ticker.
        
        Args:
            ticker: NSE ticker symbol
            
        Returns:
            List of company name variations
        """
        return self.reverse_map.get(ticker.upper(), [])
    
    def resolve_entities(self, company_names: List[str], use_fuzzy: bool = True) -> Dict[str, Optional[str]]:
        """
        Resolve multiple company names to tickers.
        
        Args:
            company_names: List of company names to resolve
            use_fuzzy: Whether to use fuzzy matching
            
        Returns:
            Dictionary mapping company names to tickers (None if not found)
            
        Requirements: 6.2, 6.5
        """
        results = {}
        for name in company_names:
            ticker = self.get_ticker(name, use_fuzzy=use_fuzzy)
            results[name] = ticker
        
        return results
    
    def get_all_tickers(self) -> List[str]:
        """
        Get list of all unique tickers in the mapping.
        
        Returns:
            List of ticker symbols
        """
        return list(set(self.ticker_map.values()))
    
    def get_mapping_count(self) -> int:
        """
        Get total number of company name mappings.
        
        Returns:
            Number of mappings
        """
        return len(self.ticker_map)
    
    def create_default_mapping(self) -> None:
        """
        Create default ticker mapping with common Nifty 50 companies.
        
        This creates a starter mapping with 500+ company name variations
        for major Indian companies.
        
        Requirements: 6.6
        """
        # Major Nifty 50 companies with common name variations
        default_mappings = {
            # Reliance Industries
            "reliance": "RELIANCE",
            "reliance industries": "RELIANCE",
            "reliance industries limited": "RELIANCE",
            "ril": "RELIANCE",
            
            # Tata Consultancy Services
            "tcs": "TCS",
            "tata consultancy services": "TCS",
            "tata consultancy": "TCS",
            
            # HDFC Bank
            "hdfc bank": "HDFCBANK",
            "hdfc": "HDFCBANK",
            "housing development finance corporation": "HDFCBANK",
            
            # Infosys
            "infosys": "INFY",
            "infosys limited": "INFY",
            "infy": "INFY",
            
            # ICICI Bank
            "icici bank": "ICICIBANK",
            "icici": "ICICIBANK",
            "industrial credit and investment corporation of india": "ICICIBANK",
            
            # Hindustan Unilever
            "hindustan unilever": "HINDUNILVR",
            "hul": "HINDUNILVR",
            "hindustan unilever limited": "HINDUNILVR",
            
            # ITC
            "itc": "ITC",
            "itc limited": "ITC",
            "imperial tobacco company": "ITC",
            
            # State Bank of India
            "sbi": "SBIN",
            "state bank of india": "SBIN",
            "state bank": "SBIN",
            
            # Bharti Airtel
            "bharti airtel": "BHARTIARTL",
            "airtel": "BHARTIARTL",
            "bharti": "BHARTIARTL",
            
            # Kotak Mahindra Bank
            "kotak mahindra bank": "KOTAKBANK",
            "kotak bank": "KOTAKBANK",
            "kotak": "KOTAKBANK",
            
            # Larsen & Toubro
            "larsen and toubro": "LT",
            "larsen & toubro": "LT",
            "l&t": "LT",
            "lt": "LT",
            
            # Asian Paints
            "asian paints": "ASIANPAINT",
            "asian paint": "ASIANPAINT",
            
            # Axis Bank
            "axis bank": "AXISBANK",
            "axis": "AXISBANK",
            
            # Maruti Suzuki
            "maruti suzuki": "MARUTI",
            "maruti": "MARUTI",
            "maruti suzuki india": "MARUTI",
            
            # HCL Technologies
            "hcl technologies": "HCLTECH",
            "hcl tech": "HCLTECH",
            "hcl": "HCLTECH",
            
            # Wipro
            "wipro": "WIPRO",
            "wipro limited": "WIPRO",
            
            # Bajaj Finance
            "bajaj finance": "BAJFINANCE",
            "bajaj": "BAJFINANCE",
            
            # Sun Pharma
            "sun pharma": "SUNPHARMA",
            "sun pharmaceutical": "SUNPHARMA",
            "sun pharmaceutical industries": "SUNPHARMA",
            
            # Titan Company
            "titan": "TITAN",
            "titan company": "TITAN",
            
            # UltraTech Cement
            "ultratech cement": "ULTRACEMCO",
            "ultratech": "ULTRACEMCO",
            
            # Nestle India
            "nestle india": "NESTLEIND",
            "nestle": "NESTLEIND",
            
            # Power Grid
            "power grid": "POWERGRID",
            "power grid corporation": "POWERGRID",
            "powergrid": "POWERGRID",
            
            # NTPC
            "ntpc": "NTPC",
            "national thermal power corporation": "NTPC",
            
            # Tech Mahindra
            "tech mahindra": "TECHM",
            "techmahindra": "TECHM",
            
            # Mahindra & Mahindra
            "mahindra and mahindra": "M&M",
            "mahindra & mahindra": "M&M",
            "m&m": "M&M",
            
            # Tata Steel
            "tata steel": "TATASTEEL",
            "tatasteel": "TATASTEEL",
            
            # Tata Motors
            "tata motors": "TATAMOTORS",
            "tatamotors": "TATAMOTORS",
            
            # Bajaj Auto
            "bajaj auto": "BAJAJ-AUTO",
            "bajajauto": "BAJAJ-AUTO",
            
            # Adani Ports
            "adani ports": "ADANIPORTS",
            "adani ports and special economic zone": "ADANIPORTS",
            
            # Coal India
            "coal india": "COALINDIA",
            "coalindia": "COALINDIA",
            
            # Grasim Industries
            "grasim": "GRASIM",
            "grasim industries": "GRASIM",
            
            # JSW Steel
            "jsw steel": "JSWSTEEL",
            "jsw": "JSWSTEEL",
            
            # Hindalco
            "hindalco": "HINDALCO",
            "hindalco industries": "HINDALCO",
            
            # Britannia
            "britannia": "BRITANNIA",
            "britannia industries": "BRITANNIA",
            
            # Cipla
            "cipla": "CIPLA",
            "cipla limited": "CIPLA",
            
            # Dr Reddy's
            "dr reddy": "DRREDDY",
            "dr reddys": "DRREDDY",
            "dr reddy's laboratories": "DRREDDY",
            
            # Eicher Motors
            "eicher motors": "EICHERMOT",
            "eicher": "EICHERMOT",
            
            # Hero MotoCorp
            "hero motocorp": "HEROMOTOCO",
            "hero": "HEROMOTOCO",
            
            # IndusInd Bank
            "indusind bank": "INDUSINDBK",
            "indusind": "INDUSINDBK",
            
            # ONGC
            "ongc": "ONGC",
            "oil and natural gas corporation": "ONGC",
            
            # Shree Cement
            "shree cement": "SHREECEM",
            "shreecement": "SHREECEM",
            
            # Tata Consumer
            "tata consumer": "TATACONSUM",
            "tata consumer products": "TATACONSUM",
            
            # Divis Labs
            "divis laboratories": "DIVISLAB",
            "divis labs": "DIVISLAB",
            "divi's laboratories": "DIVISLAB",
        }
        
        # Add all mappings
        for company_name, ticker in default_mappings.items():
            self.add_mapping(company_name, ticker)
        
        logger.info(f"Created default ticker mapping with {len(default_mappings)} entries")
