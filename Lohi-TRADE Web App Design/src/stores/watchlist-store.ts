/**
 * Watchlist Zustand store.
 * Manages monitored symbols with backend persistence via PUT /api/config.
 */

import { create } from 'zustand';
import { api } from '../lib/api-client';
import { showToast } from '../components/shared/Toast';

// NIFTY 200 NSE symbols for autocomplete
const NSE_SYMBOLS = [
  // NIFTY 50
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN',
  'BHARTIARTL', 'KOTAKBANK', 'ITC', 'LT', 'AXISBANK', 'BAJFINANCE', 'ASIANPAINT',
  'MARUTI', 'TITAN', 'SUNPHARMA', 'ULTRACEMCO', 'NESTLEIND', 'WIPRO', 'HCLTECH',
  'ADANIENT', 'ADANIPORTS', 'POWERGRID', 'NTPC', 'JSWSTEEL', 'TATAMOTORS',
  'TATASTEEL', 'ONGC', 'COALINDIA', 'BAJAJFINSV', 'TECHM', 'INDUSINDBK',
  'HINDALCO', 'DRREDDY', 'CIPLA', 'EICHERMOT', 'DIVISLAB', 'BPCL', 'GRASIM',
  'BRITANNIA', 'APOLLOHOSP', 'HEROMOTOCO', 'SBILIFE', 'HDFCLIFE', 'TATACONSUM',
  'M&M', 'UPL', 'BAJAJ-AUTO',
  // NIFTY NEXT 50
  'ADANIGREEN', 'ADANIPOWER', 'AMBUJACEM', 'AUROPHARMA', 'BANKBARODA',
  'BERGEPAINT', 'BOSCHLTD', 'CANBK', 'CHOLAFIN', 'COLPAL', 'CONCOR', 'DABUR',
  'DLF', 'GAIL', 'GODREJCP', 'HAVELLS', 'ICICIGI', 'ICICIPRULI', 'IDEA',
  'IDFCFIRSTB', 'INDHOTEL', 'INDUSTOWER', 'IOC', 'IRCTC', 'JINDALSTEL',
  'JSWENERGY', 'JUBLFOOD', 'LICI', 'LUPIN', 'MARICO', 'MCDOWELL-N',
  'MOTHERSON', 'MUTHOOTFIN', 'NAUKRI', 'NHPC', 'NMDC', 'OBEROIRLTY',
  'OFSS', 'PAGEIND', 'PEL', 'PERSISTENT', 'PETRONET', 'PIDILITIND',
  'PIIND', 'PNB', 'POLYCAB', 'SAIL', 'SHREECEM', 'SHRIRAMFIN',
  'SIEMENS', 'SRF', 'TATACOMM', 'TATAELXSI', 'TATAPOWER', 'TORNTPHARM',
  'TRENT', 'UNIONBANK', 'UNITDSPR', 'VEDL', 'VOLTAS', 'ZOMATO', 'ZYDUSLIFE',
  // NIFTY MIDCAP SELECT & OTHERS
  'ABB', 'ACC', 'ABCAPITAL', 'ABFRL', 'ALKEM', 'ASHOKLEY', 'ASTRAL',
  'ATUL', 'AUBANK', 'BALKRISIND', 'BANDHANBNK', 'BATAINDIA', 'BEL',
  'BHARATFORG', 'BHEL', 'BIOCON', 'BSE', 'CANFINHOME', 'CGPOWER',
  'CHAMBLFERT', 'COFORGE', 'CROMPTON', 'CUB', 'CUMMINSIND', 'DEEPAKNTR',
  'DELHIVERY', 'DEVYANI', 'DIXON', 'ESCORTS', 'EXIDEIND', 'FEDERALBNK',
  'FORTIS', 'GLENMARK', 'GMRINFRA', 'GNFC', 'GODREJPROP', 'GRANULES',
  'GUJGASLTD', 'HAL', 'HDFCAMC', 'HINDPETRO', 'HONAUT', 'IPCALAB',
  'IRFC', 'IEX', 'INDIAMART', 'INDIANB', 'JKCEMENT', 'JSL',
  'KALYANKJIL', 'KEI', 'LAURUSLABS', 'LICHSGFIN', 'LTIM', 'LTTS',
  'MANAPPURAM', 'MFSL', 'MAXHEALTH', 'METROPOLIS', 'MPHASIS', 'MRF',
  'NATIONALUM', 'NAVINFLUOR', 'NIACL', 'OIL', 'PAYTM', 'PFC',
  'PHOENIXLTD', 'PRESTIGE', 'PVRINOX', 'RAJESHEXPO', 'RAMCOCEM',
  'RBLBANK', 'RECLTD', 'SBICARD', 'SJVN', 'SONACOMS', 'STARHEALTH',
  'SUNDARMFIN', 'SUNDRMFAST', 'SUPREMEIND', 'SYNGENE', 'TATACHEM',
  'TIINDIA', 'TORNTPOWER', 'TVSMOTOR', 'UBL', 'UJJIVANSFB',
  'WHIRLPOOL', 'YESBANK',
];

export interface WatchlistState {
  symbols: string[];
  searchQuery: string;
  suggestions: string[];
  lastSaved: string[];
}

export interface WatchlistActions {
  setSymbols: (symbols: string[]) => void;
  addSymbol: (symbol: string) => boolean;
  removeSymbol: (symbol: string) => void;
  setSearchQuery: (query: string) => void;
  save: () => Promise<void>;
}

export type WatchlistStore = WatchlistState & WatchlistActions;

export function filterSuggestions(query: string, currentSymbols: string[]): string[] {
  if (!query.trim()) return [];
  const q = query.toUpperCase();
  return NSE_SYMBOLS.filter(
    (s) => s.includes(q) && !currentSymbols.includes(s),
  ).slice(0, 8);
}

export const useWatchlistStore = create<WatchlistStore>((set, get) => ({
  symbols: [],
  searchQuery: '',
  suggestions: [],
  lastSaved: [],

  setSymbols: (symbols) => set({ symbols, lastSaved: symbols }),

  addSymbol: (symbol) => {
    const upper = symbol.toUpperCase().trim();
    if (!upper) return false;
    const { symbols } = get();
    if (symbols.includes(upper)) return false; // duplicate
    set({ symbols: [...symbols, upper], searchQuery: '', suggestions: [] });
    return true;
  },

  removeSymbol: (symbol) => {
    set((state) => ({
      symbols: state.symbols.filter((s) => s !== symbol),
    }));
  },

  setSearchQuery: (query) => {
    const { symbols } = get();
    set({
      searchQuery: query,
      suggestions: filterSuggestions(query, symbols),
    });
  },

  save: async () => {
    const { symbols, lastSaved } = get();
    if (symbols.length === 0) {
      showToast('Cannot save empty watchlist', 'warning');
      return;
    }
    try {
      const config = await api.getConfig();
      await api.updateConfig({ ...config, symbols });
      set({ lastSaved: symbols });
      showToast('Watchlist saved', 'success');
    } catch {
      // Revert to last saved state
      set({ symbols: lastSaved });
      showToast('Failed to save watchlist', 'error');
    }
  },
}));
