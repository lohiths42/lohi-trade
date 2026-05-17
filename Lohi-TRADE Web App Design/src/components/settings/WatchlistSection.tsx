/**
 * Watchlist Manager section for SettingsPage.
 */

import { useEffect } from 'react';
import { X, Plus, Save, Eye } from 'lucide-react';
import { useWatchlistStore } from '../../stores/watchlist-store';
import { useThemeColors } from '../../hooks/use-theme-colors';
import { api } from '../../lib/api-client';

export default function WatchlistSection() {
  const symbols = useWatchlistStore((s) => s.symbols);
  const searchQuery = useWatchlistStore((s) => s.searchQuery);
  const suggestions = useWatchlistStore((s) => s.suggestions);
  const setSymbols = useWatchlistStore((s) => s.setSymbols);
  const addSymbol = useWatchlistStore((s) => s.addSymbol);
  const removeSymbol = useWatchlistStore((s) => s.removeSymbol);
  const setSearchQuery = useWatchlistStore((s) => s.setSearchQuery);
  const save = useWatchlistStore((s) => s.save);
  const t = useThemeColors();

  useEffect(() => {
    api.getConfig().then((cfg) => {
      if (cfg?.symbols) setSymbols(cfg.symbols);
    }).catch(() => {});
  }, [setSymbols]);

  const handleAdd = (symbol: string) => addSymbol(symbol);

  return (
    <div className="rounded-xl p-5" style={{ background: t.bgCard, border: `1px solid ${t.borderPrimary}` }}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <Eye size={16} color={t.accentText} />
          <h3 className="text-sm font-semibold" style={{ color: t.textPrimary }}>Watchlist</h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono"
            style={{ background: t.bgMuted, color: t.textMuted }}>
            {symbols.length} symbols
          </span>
        </div>
        <button onClick={save}
          className="flex items-center space-x-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium transition-colors">
          <Save size={12} /><span>Save</span>
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4 min-h-[32px]">
        {symbols.length === 0 ? (
          <p className="text-xs" style={{ color: t.textMuted }}>No symbols added yet</p>
        ) : symbols.map((s) => (
          <span key={s} className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-medium"
            style={{ background: t.bgMuted, border: `1px solid ${t.borderPrimary}`, color: t.textPrimary }}>
            <span>{s}</span>
            <button onClick={() => removeSymbol(s)} aria-label={`Remove ${s}`}
              style={{ color: t.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}>
              <X size={12} />
            </button>
          </span>
        ))}
      </div>

      <div className="relative">
        <input
          type="text" value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && searchQuery.trim()) handleAdd(searchQuery); }}
          placeholder="Search and add symbol…"
          className="w-full rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
          style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textPrimary }}
        />
        {suggestions.length > 0 && (
          <div className="absolute z-10 w-full mt-1 rounded-lg shadow-xl overflow-hidden"
            style={{ background: t.bgCard, border: `1px solid ${t.borderPrimary}` }}>
            {suggestions.map((s) => (
              <button key={s} onClick={() => handleAdd(s)}
                className="w-full flex items-center justify-between px-3 py-2 text-sm transition-colors"
                style={{ color: t.textSecondary, background: 'transparent', border: 'none', cursor: 'pointer' }}
                onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
                <span>{s}</span>
                <Plus size={14} style={{ color: t.textMuted }} />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
