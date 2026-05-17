/**
 * Mini Chart Widget — sparkline for a single symbol on the Dashboard.
 */

import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import { TrendingUp, TrendingDown, WifiOff } from 'lucide-react';
import { useThemeColors } from '../../hooks/use-theme-colors';
import type { MiniChartWidgetProps } from '../../lib/types';

interface ExtendedProps extends MiniChartWidgetProps { stale?: boolean; }

export default function MiniChartWidget({ symbol, priceTicks, lastPrice, changePercent, onClick, stale }: ExtendedProps) {
  const t = useThemeColors();
  const isPositive = changePercent >= 0;
  const color = isPositive ? '#34d399' : '#f87171';
  const chartData = priceTicks.map((price, i) => ({ i, price }));

  return (
    <button
      onClick={onClick}
      className="rounded-xl p-4 transition-all text-left w-full relative card-hover"
      style={{ background: t.bgCard, border: `1px solid ${t.borderPrimary}` }}
    >
      {stale && (
        <div className="absolute top-2 right-2">
          <WifiOff size={12} className="text-amber-500" />
        </div>
      )}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold" style={{ color: t.textPrimary }}>{symbol}</span>
        {isPositive ? <TrendingUp size={14} color={color} /> : <TrendingDown size={14} color={color} />}
      </div>

      {priceTicks.length === 0 ? (
        <div className="h-12 flex items-center justify-center text-[10px]" style={{ color: t.textMuted }}>No data</div>
      ) : (
        <div className="h-12">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id={`grad-${symbol}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="price" stroke={color} strokeWidth={1.5} fill={`url(#grad-${symbol})`} dot={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="flex items-center justify-between mt-2">
        <span className="text-sm font-mono font-bold" style={{ color: t.textPrimary }}>
          ₹{lastPrice.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
        </span>
        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ color, background: `${color}15` }}>
          {isPositive ? '+' : ''}{changePercent.toFixed(2)}%
        </span>
      </div>
    </button>
  );
}
