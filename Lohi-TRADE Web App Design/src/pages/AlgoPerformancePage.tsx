import { useState } from 'react';
import {
  TrendingUp, BarChart3, Clock, Activity, Waves, Compass, Target,
  Layers, GitBranch, Zap, Volume2, Gauge, ArrowUpDown, Filter,
} from 'lucide-react';
import { motion, AnimatePresence, LayoutGroup } from 'motion/react';
import PageHeader from '../components/shared/PageHeader';
import { useStrategyPerformance } from '../hooks/use-analytics';
import type { StrategyMetrics } from '../lib/types';

// ─── Strategy display config ────────────────────────────────────────────────

interface StrategyDisplay {
  label: string;
  description: string;
  iconColor: string;
  iconBg: string;
  icon: typeof TrendingUp;
}

const STRATEGY_MAP: Record<string, StrategyDisplay> = {
  MEAN_REVERSION: { label: 'Mean Reversion', description: 'Trades price deviations from moving averages with Bollinger Band signals', iconColor: 'text-blue-400', iconBg: 'bg-blue-500/10', icon: BarChart3 },
  MeanReversion: { label: 'Mean Reversion', description: 'Trades price deviations from moving averages with Bollinger Band signals', iconColor: 'text-blue-400', iconBg: 'bg-blue-500/10', icon: BarChart3 },
  TREND_FOLLOWING: { label: 'Trend Following', description: 'Captures momentum using EMA crossovers and ADX trend strength', iconColor: 'text-purple-400', iconBg: 'bg-purple-500/10', icon: TrendingUp },
  TrendFollowing: { label: 'Trend Following', description: 'Captures momentum using EMA crossovers and ADX trend strength', iconColor: 'text-purple-400', iconBg: 'bg-purple-500/10', icon: TrendingUp },
  ORB: { label: 'Opening Range Breakout', description: 'Trades breakouts from the first 15-minute range with volume confirmation', iconColor: 'text-amber-400', iconBg: 'bg-amber-500/10', icon: Clock },
  OpeningRangeBreakout: { label: 'Opening Range Breakout', description: 'Trades breakouts from the first 15-minute range with volume confirmation', iconColor: 'text-amber-400', iconBg: 'bg-amber-500/10', icon: Clock },
  VWAPBounce: { label: 'VWAP Bounce', description: 'Trades bounces off VWAP with volume confirmation and RSI filter', iconColor: 'text-cyan-400', iconBg: 'bg-cyan-500/10', icon: Activity },
  StochasticRSI: { label: 'Stochastic RSI', description: 'Combines Stochastic oscillator with RSI for overbought/oversold entries', iconColor: 'text-pink-400', iconBg: 'bg-pink-500/10', icon: Waves },
  ADXTrend: { label: 'ADX Trend', description: 'Uses ADX strength and directional indicators for strong trend entries', iconColor: 'text-emerald-400', iconBg: 'bg-emerald-500/10', icon: Compass },
  BollingerSqueeze: { label: 'Bollinger Squeeze', description: 'Detects low-volatility squeezes for breakout entries with band width analysis', iconColor: 'text-orange-400', iconBg: 'bg-orange-500/10', icon: Target },
  PivotPoint: { label: 'Pivot Point', description: 'Trades support/resistance levels using classic pivot point calculations', iconColor: 'text-indigo-400', iconBg: 'bg-indigo-500/10', icon: Layers },
  IchimokuCloud: { label: 'Ichimoku Cloud', description: 'Uses Ichimoku Cloud components for trend direction and momentum signals', iconColor: 'text-violet-400', iconBg: 'bg-violet-500/10', icon: GitBranch },
  MACDDivergence: { label: 'MACD Divergence', description: 'Detects bullish/bearish divergences between price and MACD histogram', iconColor: 'text-rose-400', iconBg: 'bg-rose-500/10', icon: ArrowUpDown },
  ParabolicSARTrend: { label: 'Parabolic SAR Trend', description: 'Follows trend reversals using Parabolic SAR with EMA trend confirmation', iconColor: 'text-teal-400', iconBg: 'bg-teal-500/10', icon: Zap },
  VolumeBreakout: { label: 'Volume Breakout', description: 'Identifies breakouts confirmed by unusual volume spikes above moving average', iconColor: 'text-lime-400', iconBg: 'bg-lime-500/10', icon: Volume2 },
  MultiMomentum: { label: 'Multi-Timeframe Momentum', description: 'Combines RSI, Stochastic, and CCI across timeframes for confluence signals', iconColor: 'text-sky-400', iconBg: 'bg-sky-500/10', icon: Gauge },
};

type FilterMode = 'all' | 'active' | 'profitable';

// ─── Strategy Card ──────────────────────────────────────────────────────────

function AlgoStrategyCard({ metrics }: { metrics: StrategyMetrics }) {
  const display = STRATEGY_MAP[metrics.strategy] ?? {
    label: metrics.strategy.replace(/_/g, ' '),
    description: '',
    iconColor: 'text-slate-400',
    iconBg: 'bg-slate-500/10',
    icon: TrendingUp,
  };

  const Icon = display.icon;
  const isActive = metrics.tradesCount > 0;
  const isProfitable = metrics.totalPnl >= 0;

  return (
    <motion.div
      layout
      layoutId={`algo-strategy-${metrics.strategy}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="lt-bento"
      style={{ padding: 20 }}
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center space-x-3">
          <div className={`w-10 h-10 rounded-lg ${display.iconBg} flex items-center justify-center`}>
            <Icon size={20} className={display.iconColor} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-200">{display.label}</h3>
            <p className="text-xs text-slate-500 mt-0.5">{display.description}</p>
          </div>
        </div>
        <span
          className={`text-[10px] px-2 py-0.5 rounded font-bold ${
            isActive
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'bg-slate-500/20 text-slate-400'
          }`}
        >
          {isActive ? 'ACTIVE' : 'INACTIVE'}
        </span>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Total P&L</p>
          <p className={`text-lg font-bold font-mono mt-1 ${isProfitable ? 'text-emerald-400' : 'text-red-400'}`}>
            {isProfitable ? '+' : ''}₹{metrics.totalPnl.toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Win Rate</p>
          <p className="text-lg font-bold font-mono mt-1 text-slate-200">
            {metrics.winRate.toFixed(1)}%
          </p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Avg Profit</p>
          <p className={`text-lg font-bold font-mono mt-1 ${metrics.avgProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {metrics.avgProfit >= 0 ? '+' : ''}₹{metrics.avgProfit.toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Trades</p>
          <p className="text-lg font-bold font-mono mt-1 text-slate-200">
            {metrics.tradesCount}
          </p>
        </div>
      </div>

      {/* Max Drawdown */}
      <div className="mt-3 flex items-center justify-between text-xs">
        <span className="text-slate-500">Max Drawdown</span>
        <span className="text-red-400 font-mono font-medium">
          {metrics.maxDrawdown.toFixed(2)}%
        </span>
      </div>
    </motion.div>
  );
}

// ─── Algo Performance Page ──────────────────────────────────────────────────

export default function AlgoPerformancePage() {
  const { data: strategies, isLoading, error } = useStrategyPerformance();
  const [filter, setFilter] = useState<FilterMode>('all');

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">Algo Performance</h2>
          <p className="text-xs text-slate-500 mt-0.5">Strategy performance overview</p>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-slate-900 border border-slate-800 rounded-xl p-5 animate-pulse">
              <div className="h-10 bg-slate-800 rounded w-3/4 mb-4" />
              <div className="grid grid-cols-4 gap-3">
                <div className="h-16 bg-slate-800 rounded" />
                <div className="h-16 bg-slate-800 rounded" />
                <div className="h-16 bg-slate-800 rounded" />
                <div className="h-16 bg-slate-800 rounded" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">Algo Performance</h2>
        </div>
        <div className="bg-slate-900 border border-red-800/50 rounded-xl p-8 text-center">
          <p className="text-red-400 text-sm">Failed to load strategy data</p>
          <p className="text-xs text-slate-500 mt-1">{error.message}</p>
        </div>
      </div>
    );
  }

  const totalPnl = strategies.reduce((sum, s) => sum + s.totalPnl, 0);
  const totalTrades = strategies.reduce((sum, s) => sum + s.tradesCount, 0);
  const activeCount = strategies.filter((s) => s.tradesCount > 0).length;
  const profitableCount = strategies.filter((s) => s.totalPnl > 0).length;

  const filtered = strategies.filter((s) => {
    if (filter === 'active') return s.tradesCount > 0;
    if (filter === 'profitable') return s.totalPnl > 0;
    return true;
  });

  return (
    <div className="space-y-6">
      <PageHeader
        icon={<Gauge size={16} />}
        title="Algo Performance"
        subtitle="Performance metrics for all trading algorithms"
      />

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Total P&L</p>
          <p className={`text-lg font-bold font-mono mt-1 ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {totalPnl >= 0 ? '+' : ''}₹{totalPnl.toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Total Trades</p>
          <p className="text-lg font-bold font-mono mt-1 text-slate-200">{totalTrades}</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Active</p>
          <p className="text-lg font-bold font-mono mt-1 text-blue-400">{activeCount} / {strategies.length}</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Profitable</p>
          <p className="text-lg font-bold font-mono mt-1 text-emerald-400">{profitableCount}</p>
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center space-x-2">
        <Filter size={14} className="text-slate-500" />
        {(['all', 'active', 'profitable'] as FilterMode[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === f
                ? 'bg-blue-500/15 text-blue-400 border border-blue-500/25'
                : 'bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:text-slate-200'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <span className="text-xs text-slate-500 ml-2">{filtered.length} strategies</span>
      </div>

      {/* Strategy grid */}
      <LayoutGroup>
        <motion.div layout className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <AnimatePresence mode="popLayout">
            {filtered.length === 0 ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-8 text-center"
              >
                <p className="text-slate-500 text-sm">No strategies match the current filter</p>
              </motion.div>
            ) : (
              filtered.map((s) => <AlgoStrategyCard key={s.strategy} metrics={s} />)
            )}
          </AnimatePresence>
        </motion.div>
      </LayoutGroup>
    </div>
  );
}
