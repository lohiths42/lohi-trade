import { useState, useEffect, useCallback } from 'react';
import { Globe, MapPin, Building2, Clock, Banknote, CheckCircle2, Loader2 } from 'lucide-react';

/**
 * CountrySelectionStep — Setup Wizard Step: Select your trading market.
 *
 * This is the FIRST meaningful configuration step. The user picks their
 * country, which determines:
 * - Trading hours and timezone
 * - Currency and number formatting
 * - Available brokers (shown in the Integrations step)
 * - Benchmark index for volatility guard
 * - Tax rules for charge estimation
 * - Default symbol watchlist
 *
 * Calls: GET /api/market/countries → POST /api/market/select
 */

export interface CountryOption {
  code: string;
  name: string;
  currency: string;
  currency_symbol: string;
  primary_exchange: string;
  timezone: string;
  regulator: string;
  broker_count: number;
}

export interface MarketSelectionResult {
  country: string;
  country_name: string;
  currency: string;
  currency_symbol: string;
  timezone: string;
  primary_exchange: string;
  exchanges: string[];
  benchmark_index: string;
  settlement_cycle: string;
  sessions: {
    market_open: string;
    trading_start: string;
    trading_end: string;
    square_off_time: string;
    market_close: string;
  };
  available_brokers: {
    broker_id: string;
    name: string;
    description: string;
    supports_paper_trading: boolean;
    commission_model: string;
  }[];
  tax_profile: {
    source: string;
    verified: boolean;
    short_term_cgt_pct: number;
    long_term_cgt_pct: number;
    threshold_days: number;
    wash_sale_rule: boolean;
    transaction_taxes_count: number;
    disclaimer: string;
  };
  default_symbols: string[];
  regulator: string;
  supports_short_selling: boolean;
  supports_options: boolean;
  supports_futures: boolean;
}

export interface CountrySelectionStepProps {
  selectedCountry: string | null;
  onCountrySelected: (result: MarketSelectionResult) => void;
}

const API_BASE = '/api';

// Country flag emojis
const FLAGS: Record<string, string> = {
  IN: '🇮🇳', US: '🇺🇸', UK: '🇬🇧', AU: '🇦🇺',
  CA: '🇨🇦', DE: '🇩🇪', JP: '🇯🇵', SG: '🇸🇬',
};

export function CountrySelectionStep({ selectedCountry, onCountrySelected }: CountrySelectionStepProps) {
  const [countries, setCountries] = useState<CountryOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string | null>(selectedCountry);
  const [result, setResult] = useState<MarketSelectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch available countries on mount
  useEffect(() => {
    async function fetchCountries() {
      try {
        const res = await fetch(`${API_BASE}/market/countries`);
        if (!res.ok) throw new Error('Failed to fetch countries');
        const data = await res.json();
        setCountries(data);
      } catch (e) {
        setError('Could not load available markets. Is the backend running?');
      } finally {
        setLoading(false);
      }
    }
    fetchCountries();
  }, []);

  const handleSelect = useCallback(async (code: string) => {
    setSelected(code);
    setSelecting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/market/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ country_code: code }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Selection failed');
      }
      const data = await res.json();
      setResult(data);
      onCountrySelected(data);
    } catch (e: any) {
      setError(e.message || 'Failed to select market');
      setSelected(null);
    } finally {
      setSelecting(false);
    }
  }, [onCountrySelected]);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 60 }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} color="var(--fg-muted)" />
        <span style={{ marginLeft: 10, fontSize: 13, color: 'var(--fg-muted)' }}>Loading markets...</span>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.02em' }}>
          Select your market
        </h2>
        <p style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 4 }}>
          Choose the country where you'll be trading. This sets your timezone, currency, available brokers, and tax rules.
        </p>
      </div>

      {error && (
        <div style={{
          padding: '10px 14px', borderRadius: 'var(--r-sm)', marginBottom: 14,
          background: 'var(--bear-soft)', border: '1px solid color-mix(in srgb, var(--bear) 30%, transparent)',
          fontSize: 12, color: 'var(--bear)',
        }}>
          {error}
        </div>
      )}

      {/* Country Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
        {countries.map((country) => {
          const isSelected = selected === country.code;
          const flag = FLAGS[country.code] || '🌐';

          return (
            <button
              key={country.code}
              type="button"
              onClick={() => handleSelect(country.code)}
              disabled={selecting}
              style={{
                display: 'flex', flexDirection: 'column', gap: 6,
                padding: '14px 16px', borderRadius: 'var(--r-md)',
                background: isSelected ? 'color-mix(in srgb, var(--accent) 8%, var(--surface-3))' : 'var(--surface-3)',
                border: isSelected
                  ? '2px solid var(--accent)'
                  : '1px solid var(--line-2)',
                cursor: selecting ? 'wait' : 'pointer',
                textAlign: 'left' as const,
                transition: 'all 150ms ease',
                opacity: selecting && !isSelected ? 0.6 : 1,
                position: 'relative' as const,
              }}
            >
              {isSelected && (
                <CheckCircle2
                  size={16}
                  color="var(--accent)"
                  style={{ position: 'absolute', top: 10, right: 10 }}
                />
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 22 }}>{flag}</span>
                <div>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)' }}>
                    {country.name}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--fg-muted)', marginLeft: 6 }}>
                    {country.primary_exchange}
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 12, fontSize: 10, color: 'var(--fg-muted)', marginTop: 2 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  <Banknote size={10} /> {country.currency}
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  <Clock size={10} /> {country.timezone.split('/')[1]?.replace('_', ' ') || country.timezone}
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  <Building2 size={10} /> {country.broker_count} brokers
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Selection Result Summary */}
      {result && (
        <div style={{
          marginTop: 18, padding: '16px 18px', borderRadius: 'var(--r-md)',
          background: 'var(--surface-2)', border: '1px solid var(--line-2)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <CheckCircle2 size={16} color="var(--bull)" />
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)' }}>
              {result.country_name} ({result.primary_exchange}) selected
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <InfoRow icon={<Clock size={11} />} label="Timezone" value={result.timezone} />
            <InfoRow icon={<Banknote size={11} />} label="Currency" value={`${result.currency_symbol} ${result.currency}`} />
            <InfoRow icon={<MapPin size={11} />} label="Market Hours" value={`${result.sessions.market_open} – ${result.sessions.market_close}`} />
            <InfoRow icon={<Globe size={11} />} label="Settlement" value={result.settlement_cycle} />
            <InfoRow icon={<Building2 size={11} />} label="Benchmark" value={result.benchmark_index} />
            <InfoRow icon={<Building2 size={11} />} label="Brokers" value={`${result.available_brokers.length} available`} />
          </div>

          {/* Tax summary */}
          <div style={{
            marginTop: 12, padding: '10px 12px', borderRadius: 'var(--r-sm)',
            background: 'var(--surface-3)', border: '1px solid var(--line-2)',
            fontSize: 11, color: 'var(--fg-muted)',
          }}>
            <span style={{ fontWeight: 700, color: 'var(--fg-secondary)' }}>Tax Profile: </span>
            Short-term CGT {result.tax_profile.short_term_cgt_pct}% · Long-term CGT {result.tax_profile.long_term_cgt_pct}%
            {result.tax_profile.wash_sale_rule && ' · Wash sale rule applies'}
            {' · '}{result.tax_profile.transaction_taxes_count} transaction taxes
            <p style={{ margin: '6px 0 0', fontSize: 10, fontStyle: 'italic' }}>
              {result.tax_profile.disclaimer}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
      <span style={{ color: 'var(--fg-muted)' }}>{icon}</span>
      <span style={{ color: 'var(--fg-muted)', fontWeight: 600 }}>{label}:</span>
      <span style={{ color: 'var(--fg-primary)', fontWeight: 500 }}>{value}</span>
    </div>
  );
}

export default CountrySelectionStep;
