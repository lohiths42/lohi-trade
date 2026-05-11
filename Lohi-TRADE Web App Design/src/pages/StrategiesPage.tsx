import { useState, useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import {
  ArrowLeft, TrendingUp, TrendingDown, Activity, Minus, Plus,
  Save, ShoppingCart, Eye,
} from 'lucide-react';
import { motion } from 'motion/react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';

// ─── Types ──────────────────────────────────────────────────────────────────

type Sentiment = 'Bullish' | 'Bearish' | 'Neutral' | 'Volatile';
type FilterMode = 'All' | Sentiment;

interface StrategyLeg {
  side: 'B' | 'S';
  instrument: string;
  expiry: string;
  strike: number;
  optionType: 'CE' | 'PE';
  qty: number;
  ltp: number;
  price: number;
  premium: number;
}

interface OptionStrategy {
  id: string;
  name: string;
  sentiment: Sentiment;
  description: string;
  payoffPath: string; // SVG path for the mini payoff diagram
  legs: StrategyLeg[];
  maxProfit: number | null;
  maxLoss: number | null;
  breakeven: number;
  riskRewardRatio: string;
  probabilityOfProfit: number;
  marginBreakdown: {
    span: number;
    exposure: number;
    totalMargin: number;
    premiumPayable: number;
  };
}

// ─── Payoff SVG paths for each strategy type ────────────────────────────────

const PAYOFF_PATHS: Record<string, { path: string; fill: string }> = {
  'bull-call-spread': {
    path: 'M 10 70 L 40 70 L 55 25 L 90 25',
    fill: 'M 10 70 L 40 70 L 55 25 L 90 25 L 90 80 L 10 80 Z',
  },
  'bear-call-spread': {
    path: 'M 10 25 L 45 25 L 60 70 L 90 70',
    fill: 'M 10 25 L 45 25 L 60 70 L 90 70 L 90 80 L 10 80 Z',
  },
  'long-straddle': {
    path: 'M 10 25 L 50 75 L 90 25',
    fill: 'M 10 25 L 50 75 L 90 25 L 90 80 L 10 80 Z',
  },
  'short-straddle': {
    path: 'M 10 70 L 50 20 L 90 70',
    fill: 'M 10 70 L 50 20 L 90 70 L 90 80 L 10 80 Z',
  },
  'long-strangle': {
    path: 'M 10 25 L 35 75 L 65 75 L 90 25',
    fill: 'M 10 25 L 35 75 L 65 75 L 90 25 L 90 80 L 10 80 Z',
  },
  'short-strangle': {
    path: 'M 10 70 L 35 20 L 65 20 L 90 70',
    fill: 'M 10 70 L 35 20 L 65 20 L 90 70 L 90 80 L 10 80 Z',
  },
  'iron-condor': {
    path: 'M 10 50 L 25 70 L 45 20 L 55 20 L 75 70 L 90 50',
    fill: 'M 10 50 L 25 70 L 45 20 L 55 20 L 75 70 L 90 50 L 90 80 L 10 80 Z',
  },
  'butterfly-spread': {
    path: 'M 10 50 L 30 50 L 50 20 L 70 50 L 90 50',
    fill: 'M 10 50 L 30 50 L 50 20 L 70 50 L 90 50 L 90 80 L 10 80 Z',
  },
};

// ─── Pre-built strategies catalog ───────────────────────────────────────────

const NIFTY_SPOT = 22912.40;
const NIFTY_CHANGE = 399.75;
const NIFTY_CHANGE_PCT = 1.78;

const PRE_BUILT_STRATEGIES: OptionStrategy[] = [
  {
    id: 'bull-call-spread',
    name: 'Bull Call Spread',
    sentiment: 'Bullish',
    description: 'Profit from a moderate increase by buying a lower-strike call and selling a higher-strike call.',
    payoffPath: 'bull-call-spread',
    legs: [
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22950, optionType: 'CE', qty: 65, ltp: 348.60, price: 345.9, premium: 22483.5 },
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23050, optionType: 'CE', qty: 65, ltp: 292.20, price: 291.35, premium: 18937.75 },
    ],
    maxProfit: 2954.25,
    maxLoss: -3545.75,
    breakeven: 23004.55,
    riskRewardRatio: '1 : 0.83',
    probabilityOfProfit: 49.08,
    marginBreakdown: { span: 0, exposure: 29266.44, totalMargin: 51749.94, premiumPayable: 3545.75 },
  },
  {
    id: 'bear-call-spread',
    name: 'Bear Call Spread',
    sentiment: 'Bearish',
    description: 'Profit from neutral to bearish view by selling ATM/slightly OTM call & buying higher-strike OTM call.',
    payoffPath: 'bear-call-spread',
    legs: [
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22950, optionType: 'CE', qty: 65, ltp: 348.60, price: 345.9, premium: 22483.5 },
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23100, optionType: 'CE', qty: 65, ltp: 265.40, price: 262.8, premium: 17082.0 },
    ],
    maxProfit: 5401.50,
    maxLoss: -4348.50,
    breakeven: 23033.10,
    riskRewardRatio: '1 : 1.24',
    probabilityOfProfit: 55.2,
    marginBreakdown: { span: 0, exposure: 28100.0, totalMargin: 48500.0, premiumPayable: 0 },
  },
  {
    id: 'long-straddle',
    name: 'Long Straddle',
    sentiment: 'Volatile',
    description: 'Profit from significant price movements by buying ATM call and put simultaneously.',
    payoffPath: 'long-straddle',
    legs: [
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22900, optionType: 'CE', qty: 65, ltp: 375.20, price: 372.5, premium: 24212.5 },
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22900, optionType: 'PE', qty: 65, ltp: 310.80, price: 308.4, premium: 20046.0 },
    ],
    maxProfit: null,
    maxLoss: -44258.50,
    breakeven: 23580.90,
    riskRewardRatio: 'Unlimited',
    probabilityOfProfit: 38.5,
    marginBreakdown: { span: 0, exposure: 0, totalMargin: 44258.50, premiumPayable: 44258.50 },
  },
  {
    id: 'short-straddle',
    name: 'Short Straddle',
    sentiment: 'Volatile',
    description: 'Profit from limited movement or volatility contraction by selling ATM call and put simultaneously.',
    payoffPath: 'short-straddle',
    legs: [
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22900, optionType: 'CE', qty: 65, ltp: 375.20, price: 372.5, premium: 24212.5 },
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22900, optionType: 'PE', qty: 65, ltp: 310.80, price: 308.4, premium: 20046.0 },
    ],
    maxProfit: 44258.50,
    maxLoss: null,
    breakeven: 23580.90,
    riskRewardRatio: '1 : Unlimited risk',
    probabilityOfProfit: 61.5,
    marginBreakdown: { span: 85000, exposure: 32000, totalMargin: 117000, premiumPayable: 0 },
  },
  {
    id: 'long-strangle',
    name: 'Long Strangle',
    sentiment: 'Volatile',
    description: 'Profit from large moves in either direction by buying OTM call and OTM put.',
    payoffPath: 'long-strangle',
    legs: [
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23100, optionType: 'CE', qty: 65, ltp: 265.40, price: 262.8, premium: 17082.0 },
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22700, optionType: 'PE', qty: 65, ltp: 220.60, price: 218.2, premium: 14183.0 },
    ],
    maxProfit: null,
    maxLoss: -31265.0,
    breakeven: 23581.0,
    riskRewardRatio: 'Unlimited',
    probabilityOfProfit: 32.1,
    marginBreakdown: { span: 0, exposure: 0, totalMargin: 31265.0, premiumPayable: 31265.0 },
  },
  {
    id: 'short-strangle',
    name: 'Short Strangle',
    sentiment: 'Neutral',
    description: 'Profit from range-bound markets by selling OTM call and OTM put.',
    payoffPath: 'short-strangle',
    legs: [
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23100, optionType: 'CE', qty: 65, ltp: 265.40, price: 262.8, premium: 17082.0 },
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22700, optionType: 'PE', qty: 65, ltp: 220.60, price: 218.2, premium: 14183.0 },
    ],
    maxProfit: 31265.0,
    maxLoss: null,
    breakeven: 23181.0,
    riskRewardRatio: '1 : Unlimited risk',
    probabilityOfProfit: 67.9,
    marginBreakdown: { span: 92000, exposure: 35000, totalMargin: 127000, premiumPayable: 0 },
  },
  {
    id: 'iron-condor',
    name: 'Iron Condor',
    sentiment: 'Neutral',
    description: 'Profit from range-bound markets with limited risk using four legs at different strikes.',
    payoffPath: 'iron-condor',
    legs: [
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22600, optionType: 'PE', qty: 65, ltp: 155.30, price: 153.0, premium: 9945.0 },
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22700, optionType: 'PE', qty: 65, ltp: 220.60, price: 218.2, premium: 14183.0 },
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23100, optionType: 'CE', qty: 65, ltp: 265.40, price: 262.8, premium: 17082.0 },
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23200, optionType: 'CE', qty: 65, ltp: 218.50, price: 216.0, premium: 14040.0 },
    ],
    maxProfit: 7280.0,
    maxLoss: -6220.0,
    breakeven: 23212.0,
    riskRewardRatio: '1 : 1.17',
    probabilityOfProfit: 54.0,
    marginBreakdown: { span: 18000, exposure: 12000, totalMargin: 30000, premiumPayable: 0 },
  },
  {
    id: 'butterfly-spread',
    name: 'Butterfly Spread',
    sentiment: 'Neutral',
    description: 'Profit from minimal price movement around a central strike with limited risk on both sides.',
    payoffPath: 'butterfly-spread',
    legs: [
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22800, optionType: 'CE', qty: 65, ltp: 410.50, price: 408.0, premium: 26520.0 },
      { side: 'S', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 22900, optionType: 'CE', qty: 130, ltp: 375.20, price: 372.5, premium: 48425.0 },
      { side: 'B', instrument: 'NIFTY', expiry: '30 Mar 26', strike: 23000, optionType: 'CE', qty: 65, ltp: 320.10, price: 317.5, premium: 20637.5 },
    ],
    maxProfit: 5767.50,
    maxLoss: -1267.50,
    breakeven: 22919.50,
    riskRewardRatio: '1 : 4.55',
    probabilityOfProfit: 18.0,
    marginBreakdown: { span: 0, exposure: 0, totalMargin: 1267.50, premiumPayable: 1267.50 },
  },
];

// ─── Sentiment badge colors ─────────────────────────────────────────────────

const SENTIMENT_COLORS: Record<Sentiment, { bg: string; text: string; icon: typeof TrendingUp }> = {
  Bullish: { bg: 'var(--bull-soft)', text: 'var(--bull)', icon: TrendingUp },
  Bearish: { bg: 'var(--bear-soft)', text: 'var(--bear)', icon: TrendingDown },
  Neutral: { bg: 'color-mix(in srgb, var(--fg-muted) 14%, transparent)', text: 'var(--fg-secondary)', icon: Minus },
  Volatile: { bg: 'color-mix(in srgb, #a855f7 16%, transparent)', text: '#c084fc', icon: Activity },
};

// ─── Mini Payoff SVG ────────────────────────────────────────────────────────

function PayoffMiniChart({ strategyId }: { strategyId: string }) {
  const paths = PAYOFF_PATHS[strategyId];
  if (!paths) return null;

  return (
    <svg viewBox="0 0 100 90" className="w-full h-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`grad-${strategyId}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--bull)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--bull)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {/* Zero line */}
      <line x1="0" y1="50" x2="100" y2="50" stroke="color-mix(in srgb, var(--fg-muted) 40%, transparent)" strokeWidth="0.5" strokeDasharray="3 3" />
      {/* Fill area */}
      <path d={paths.fill} fill={`url(#grad-${strategyId})`} />
      {/* Profit line (green) */}
      <path d={paths.path} fill="none" stroke="var(--bull)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      {/* Loss portion in red */}
      <clipPath id={`clip-loss-${strategyId}`}>
        <rect x="0" y="50" width="100" height="40" />
      </clipPath>
      <path d={paths.path} fill="none" stroke="var(--bear)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" clipPath={`url(#clip-loss-${strategyId})`} />
    </svg>
  );
}

// ─── Strategy Card ──────────────────────────────────────────────────────────

function StrategyCard({
  strategy,
  onBuild,
  onViewLegs,
}: {
  strategy: OptionStrategy;
  onBuild: () => void;
  onViewLegs: () => void;
}) {
  const sentimentStyle = SENTIMENT_COLORS[strategy.sentiment];
  const SentimentIcon = sentimentStyle.icon;

  return (
    <motion.div
      whileHover={{ y: -3 }}
      transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
      className="lt-bento group relative overflow-hidden"
      style={{ padding: 0, display: 'flex', flexDirection: 'column' }}
    >
      {/* Payoff chart area */}
      <div
        style={{
          position: 'relative',
          height: 116,
          padding: '12px 14px 0',
          background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 6%, transparent) 0%, transparent 90%)',
          borderBottom: '1px solid var(--line-1)',
        }}
      >
        <button
          onClick={onViewLegs}
          className="absolute top-2 right-2 z-10"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '4px 9px', borderRadius: 6,
            fontSize: 10, fontWeight: 600,
            background: 'color-mix(in srgb, var(--surface-2) 85%, transparent)',
            backdropFilter: 'blur(8px)',
            border: '1px solid var(--line-2)',
            color: 'var(--fg-secondary)',
            cursor: 'pointer',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--fg-primary)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--fg-secondary)'; }}
        >
          <Eye size={10} />
          Legs
        </button>
        <PayoffMiniChart strategyId={strategy.payoffPath} />
      </div>

      {/* Info */}
      <div style={{ padding: '14px 16px 16px', display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.01em' }}>
            {strategy.name}
          </h3>
          <div
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '2px 7px', borderRadius: 999,
              fontSize: 10, fontWeight: 700,
              background: sentimentStyle.bg, color: sentimentStyle.text,
              flexShrink: 0,
            }}
          >
            <SentimentIcon size={10} />
            {strategy.sentiment}
          </div>
        </div>

        <p style={{ fontSize: 11, color: 'var(--fg-muted)', lineHeight: 1.55, margin: 0 }}>
          {strategy.description}
        </p>

        {/* Key metrics summary */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 6,
            padding: '8px 10px',
            borderRadius: 'var(--r-sm)',
            background: 'var(--surface-3)',
            border: '1px solid var(--line-2)',
          }}
        >
          <MiniStat label="Max P" value={strategy.maxProfit === null ? '∞' : `₹${Math.round(strategy.maxProfit).toLocaleString('en-IN')}`} color="var(--bull)" />
          <MiniStat label="Max L" value={strategy.maxLoss === null ? '∞' : `₹${Math.round(Math.abs(strategy.maxLoss)).toLocaleString('en-IN')}`} color="var(--bear)" />
          <MiniStat label="PoP" value={`${strategy.probabilityOfProfit.toFixed(0)}%`} />
        </div>

        {/* Build button */}
        <button
          onClick={onBuild}
          style={{
            width: '100%',
            padding: '10px 14px',
            borderRadius: 'var(--r-sm)',
            background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
            color: '#fff',
            border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
            fontSize: 12, fontWeight: 700, letterSpacing: '0.02em',
            cursor: 'pointer',
            boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 28%, transparent)',
            transition: 'transform 180ms var(--ease-out), box-shadow 180ms var(--ease-out)',
            marginTop: 'auto',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.boxShadow = '0 1px 0 rgba(255,255,255,0.15) inset, 0 6px 20px color-mix(in srgb, var(--accent) 40%, transparent)'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.boxShadow = '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 28%, transparent)'; e.currentTarget.style.transform = 'translateY(0)'; }}
        >
          Build strategy
        </button>
      </div>
    </motion.div>
  );
}

/** Tiny stat cell inside the strategy card summary row. */
function MiniStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <p style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0 }}>{label}</p>
      <p className="lt-tabular" style={{ fontSize: 11, fontWeight: 700, color: color ?? 'var(--fg-primary)', margin: '2px 0 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</p>
    </div>
  );
}

// ─── Strategy Detail / Builder View ─────────────────────────────────────────

function StrategyDetailView({
  strategy,
  onBack,
}: {
  strategy: OptionStrategy;
  onBack: () => void;
}) {
  const [lotMultiplier, setLotMultiplier] = useState(1);
  const [activeTab, setActiveTab] = useState<'payoff' | 'timeseries' | 'chain'>('payoff');

  // Generate payoff curve data
  const payoffData = useMemo(() => {
    const spotMin = NIFTY_SPOT * 0.9;
    const spotMax = NIFTY_SPOT * 1.1;
    const step = (spotMax - spotMin) / 100;
    const points: { spot: number; pnlTarget: number; pnlExpiry: number }[] = [];

    for (let spot = spotMin; spot <= spotMax; spot += step) {
      let pnlExpiry = 0;
      for (const leg of strategy.legs) {
        const mult = leg.side === 'B' ? 1 : -1;
        let intrinsic: number;
        if (leg.optionType === 'CE') {
          intrinsic = Math.max(0, spot - leg.strike);
        } else {
          intrinsic = Math.max(0, leg.strike - spot);
        }
        pnlExpiry += mult * (intrinsic - leg.price) * leg.qty * lotMultiplier;
      }
      const pnlTarget = pnlExpiry * 0.6;
      points.push({
        spot: Math.round(spot),
        pnlTarget: Math.round(pnlTarget),
        pnlExpiry: Math.round(pnlExpiry),
      });
    }
    return points;
  }, [strategy, lotMultiplier]);

  const totalPrice = strategy.legs.reduce((sum, l) => {
    const mult = l.side === 'B' ? -1 : 1;
    return sum + mult * l.price;
  }, 0) * lotMultiplier;

  const totalPremium = Math.abs(
    strategy.legs.reduce((sum, l) => {
      const mult = l.side === 'B' ? -1 : 1;
      return sum + mult * l.premium;
    }, 0)
  ) * lotMultiplier;

  const scaledMaxProfit = strategy.maxProfit !== null ? strategy.maxProfit * lotMultiplier : null;
  const scaledMaxLoss = strategy.maxLoss !== null ? strategy.maxLoss * lotMultiplier : null;

  // Mock Greeks data
  const greeksData = strategy.legs.map((leg) => ({
    ...leg,
    delta: leg.side === 'B' ? (leg.optionType === 'CE' ? 0.52 : -0.47) : (leg.optionType === 'CE' ? -0.47 : 0.52),
    theta: leg.side === 'B' ? -28.77 : 28.3,
    gamma: leg.side === 'B' ? 0.0005 : -0.0005,
    vega: leg.side === 'B' ? 11.73 : -11.73,
  }));

  const sentimentStyle = SENTIMENT_COLORS[strategy.sentiment];
  const SentimentIcon = sentimentStyle.icon;
  const totalMarginScaled = strategy.marginBreakdown.totalMargin * lotMultiplier;
  const marginBenefit = totalMarginScaled * 0.03;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<TrendingUp size={16} />}
        title={strategy.name}
        subtitle={strategy.description}
        actions={
          <>
            <div
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 5,
                padding: '5px 10px', borderRadius: 999,
                fontSize: 11, fontWeight: 700,
                background: sentimentStyle.bg, color: sentimentStyle.text,
              }}
            >
              <SentimentIcon size={11} />
              {strategy.sentiment}
            </div>
            <button onClick={onBack} style={btnGhost}>
              <ArrowLeft size={12} /> Back
            </button>
          </>
        }
      />

      {/* Instrument strip */}
      <div
        style={{
          display: 'inline-flex', alignItems: 'center', alignSelf: 'flex-start', gap: 10,
          padding: '8px 12px', borderRadius: 'var(--r-md)',
          background: 'var(--surface-2)', border: '1px solid var(--line-2)',
          boxShadow: 'var(--elev-1)',
        }}
      >
        <span style={{ fontSize: 10, letterSpacing: '0.08em', fontWeight: 800, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>NSE</span>
        <span style={{ width: 1, height: 14, background: 'var(--line-2)' }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)' }}>NIFTY</span>
        <span className="lt-tabular" style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', letterSpacing: '-0.02em' }}>
          {NIFTY_SPOT.toLocaleString('en-IN')}
        </span>
        <span
          className="lt-tabular"
          style={{
            fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999,
            color: 'var(--bull)', background: 'var(--bull-soft)',
          }}
        >
          +{NIFTY_CHANGE} ({NIFTY_CHANGE_PCT}%)
        </span>
      </div>

      {/* Metrics row (5 cards) */}
      <motion.div
        initial="hidden" animate="visible"
        variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.04 } } }}
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 14 }}
      >
        <MetricTile label="Max Profit" color="var(--bull)" value={scaledMaxProfit === null ? '∞' : `₹${Math.round(scaledMaxProfit).toLocaleString('en-IN')}`} sub={scaledMaxProfit === null ? 'Unlimited' : `+${((scaledMaxProfit / totalMarginScaled) * 100).toFixed(2)}% on margin`} />
        <MetricTile label="Max Loss" color="var(--bear)" value={scaledMaxLoss === null ? '∞' : `₹${Math.round(Math.abs(scaledMaxLoss)).toLocaleString('en-IN')}`} sub={scaledMaxLoss === null ? 'Unlimited' : `${((scaledMaxLoss / totalMarginScaled) * 100).toFixed(2)}% on margin`} />
        <MetricTile label="Breakeven" color="var(--accent-2)" value={strategy.breakeven.toLocaleString('en-IN', { maximumFractionDigits: 0 })} sub={`${(((strategy.breakeven - NIFTY_SPOT) / NIFTY_SPOT) * 100).toFixed(2)}% from spot`} />
        <MetricTile label="Risk / Reward" color="var(--warn)" value={strategy.riskRewardRatio} sub="Loss : profit" />
        <MetricTile label="Prob. of Profit" color="#c084fc" value={`${strategy.probabilityOfProfit.toFixed(0)}%`} sub="Implied from IV" />
      </motion.div>

      {/* Two-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }} className="strategy-detail-grid">
        {/* ─── LEFT: Legs builder + buttons + margin + greeks ─── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <BentoCard>
            <div style={{ padding: 0 }}>
              <SectionHeader title="Legs" right={
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 11, color: 'var(--fg-muted)' }}>Lots</span>
                  <Stepper value={lotMultiplier} onChange={(v) => setLotMultiplier(Math.max(1, v))} />
                </div>
              } />

              {/* Leg table */}
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line-2)' }}>
                      {['B/S', 'Expiry', 'Strike', 'Type', 'Qty', 'LTP', 'Price', 'Premium'].map((h) => (
                        <th key={h} style={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {strategy.legs.map((leg, i) => {
                      const sideColor = leg.side === 'B' ? 'var(--bull)' : 'var(--bear)';
                      const typeColor = leg.optionType === 'CE' ? 'var(--bull)' : 'var(--bear)';
                      return (
                        <tr key={i} style={{ borderBottom: i < strategy.legs.length - 1 ? '1px solid var(--line-1)' : 'none' }}>
                          <td style={tdTight}>
                            <span style={{
                              display: 'inline-flex', width: 24, height: 24, alignItems: 'center', justifyContent: 'center',
                              borderRadius: 6, fontSize: 10, fontWeight: 800,
                              background: leg.side === 'B' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                              color: sideColor,
                            }}>
                              {leg.side}
                            </span>
                          </td>
                          <td style={tdTight}>
                            <span style={{ fontSize: 11, color: 'var(--fg-primary)', fontWeight: 600 }}>{leg.expiry}</span>
                          </td>
                          <td className="lt-tabular" style={{ ...tdTight, fontWeight: 600, color: 'var(--fg-primary)' }}>
                            {leg.strike.toLocaleString('en-IN')}
                          </td>
                          <td style={tdTight}>
                            <span style={{
                              padding: '2px 7px', borderRadius: 6,
                              fontSize: 10, fontWeight: 700,
                              background: leg.optionType === 'CE' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                              color: typeColor,
                            }}>
                              {leg.optionType}
                            </span>
                          </td>
                          <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-primary)', fontWeight: 600 }}>
                            {leg.qty}
                          </td>
                          <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-secondary)' }}>
                            {leg.ltp.toFixed(2)}
                          </td>
                          <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-secondary)' }}>
                            {leg.price.toFixed(2)}
                          </td>
                          <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-primary)', fontWeight: 600, textAlign: 'right' }}>
                            ₹{(leg.premium * lotMultiplier).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Footer actions */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', borderTop: '1px solid var(--line-2)', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ display: 'inline-flex', gap: 8 }}>
                  <button style={btnChip}><Plus size={11} /> Option</button>
                  <button style={btnChip}><Plus size={11} /> Future</button>
                </div>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12, fontSize: 11, color: 'var(--fg-muted)' }}>
                  <span>Total price <strong className="lt-tabular" style={{ color: totalPrice >= 0 ? 'var(--bull)' : 'var(--bear)', marginLeft: 6, fontWeight: 700 }}>{Math.abs(totalPrice).toFixed(2)}</strong></span>
                  <span>Premium <strong className="lt-tabular" style={{ color: 'var(--fg-primary)', marginLeft: 6, fontWeight: 700 }}>₹{totalPremium.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</strong></span>
                </div>
              </div>

              <p style={{
                fontSize: 10, color: 'var(--fg-muted)',
                padding: '0 14px 12px', margin: 0, lineHeight: 1.5,
              }}>
                Negative total price indicates a net cash inflow on execution.
              </p>
            </div>
          </BentoCard>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 10 }}>
            <button style={btnOutline}><Save size={14} /> Save</button>
            <button style={btnPrimary}><ShoppingCart size={14} /> Trade strategy</button>
          </div>

          {/* Margin Breakdown */}
          <BentoCard>
            <div>
              <SectionHeader
                title="Margin breakdown"
                right={
                  <span
                    className="lt-tabular"
                    style={{
                      fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 999,
                      background: 'var(--bull-soft)', color: 'var(--bull)',
                    }}
                  >
                    Benefit ₹{marginBenefit.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </span>
                }
              />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, padding: '14px' }}>
                {[
                  { label: 'Span', value: strategy.marginBreakdown.span * lotMultiplier },
                  { label: 'Exposure', value: strategy.marginBreakdown.exposure * lotMultiplier },
                  { label: 'Total', value: strategy.marginBreakdown.totalMargin * lotMultiplier, highlight: true },
                  { label: 'Premium payable', value: strategy.marginBreakdown.premiumPayable * lotMultiplier },
                ].map((item) => (
                  <div key={item.label}
                    style={{
                      padding: '10px 12px', borderRadius: 'var(--r-sm)',
                      background: item.highlight ? 'color-mix(in srgb, var(--accent) 8%, var(--surface-3))' : 'var(--surface-3)',
                      border: '1px solid var(--line-2)',
                    }}
                  >
                    <p style={miniLabel}>{item.label}</p>
                    <p className="lt-tabular" style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '4px 0 0' }}>
                      ₹{item.value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </BentoCard>

          {/* Greeks */}
          <BentoCard>
            <div>
              <SectionHeader title="Greeks" />
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line-2)' }}>
                      {['B/S', 'Leg', 'Strike', 'Qty', 'Δ', 'Θ', 'Γ', 'ν'].map((h) => (
                        <th key={h} style={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {greeksData.map((g, i) => (
                      <tr key={i} style={{ borderBottom: i < greeksData.length - 1 ? '1px solid var(--line-1)' : 'none' }}>
                        <td style={tdTight}>
                          <span style={{
                            display: 'inline-flex', width: 22, height: 22, alignItems: 'center', justifyContent: 'center',
                            borderRadius: 6, fontSize: 10, fontWeight: 800,
                            background: g.side === 'B' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                            color: g.side === 'B' ? 'var(--bull)' : 'var(--bear)',
                          }}>
                            {g.side}
                          </span>
                        </td>
                        <td style={{ ...tdTight, color: 'var(--fg-primary)', fontWeight: 600 }}>
                          {g.expiry} <span style={{ color: 'var(--fg-muted)' }}>·</span> {g.optionType}
                        </td>
                        <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-primary)' }}>
                          {g.strike.toLocaleString('en-IN')}
                        </td>
                        <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-secondary)' }}>
                          {g.qty * lotMultiplier}
                        </td>
                        <td className="lt-tabular" style={{ ...tdTight, color: g.delta >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{g.delta.toFixed(2)}</td>
                        <td className="lt-tabular" style={{ ...tdTight, color: g.theta >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{g.theta.toFixed(2)}</td>
                        <td className="lt-tabular" style={{ ...tdTight, color: 'var(--fg-secondary)' }}>{g.gamma.toFixed(4)}</td>
                        <td className="lt-tabular" style={{ ...tdTight, color: g.vega >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{g.vega.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </BentoCard>
        </div>

        {/* ─── RIGHT: Payoff graph ─── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <BentoCard>
            <div>
              {/* Tabs + legend */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px',
                borderBottom: '1px solid var(--line-2)',
                gap: 10, flexWrap: 'wrap',
              }}>
                <div
                  role="tablist"
                  style={{
                    display: 'inline-flex', gap: 2, padding: 3,
                    borderRadius: 'var(--r-sm)',
                    background: 'var(--surface-4)', border: '1px solid var(--line-2)',
                  }}
                >
                  {(['payoff', 'timeseries', 'chain'] as const).map((tab) => {
                    const active = activeTab === tab;
                    return (
                      <button
                        key={tab}
                        role="tab"
                        aria-selected={active}
                        onClick={() => setActiveTab(tab)}
                        style={{
                          padding: '5px 10px', borderRadius: 6,
                          fontSize: 11, fontWeight: 600,
                          color: active ? 'var(--fg-primary)' : 'var(--fg-muted)',
                          background: active ? 'var(--surface-2)' : 'transparent',
                          border: active ? '1px solid var(--line-2)' : '1px solid transparent',
                          boxShadow: active ? 'var(--elev-1)' : 'none',
                          cursor: 'pointer',
                          transition: 'all 120ms var(--ease-out)',
                        }}
                      >
                        {tab === 'payoff' ? 'Payoff' : tab === 'timeseries' ? 'Time series' : 'Option chain'}
                      </button>
                    );
                  })}
                </div>

                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 14, fontSize: 10, color: 'var(--fg-muted)' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ display: 'inline-block', width: 12, height: 2, borderRadius: 2, background: '#c084fc', borderTop: '2px dashed #c084fc' }} />
                    At target
                  </span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ display: 'inline-block', width: 12, height: 6, borderRadius: 2, background: 'color-mix(in srgb, var(--accent) 35%, transparent)' }} />
                    At expiry
                  </span>
                </div>
              </div>

              {/* Tab body */}
              {activeTab === 'payoff' ? (
                <div style={{ padding: '12px 10px 8px', height: 360 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={payoffData} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
                      <defs>
                        <linearGradient id="payoffGradientPos" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="color-mix(in srgb, var(--fg-muted) 22%, transparent)" vertical={false} />
                      <XAxis
                        dataKey="spot"
                        tick={{ fontSize: 10, fill: 'var(--fg-muted)' }}
                        tickFormatter={(v: number) => v.toLocaleString('en-IN')}
                        tickLine={false} axisLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: 'var(--fg-muted)' }}
                        tickFormatter={(v: number) => v.toLocaleString('en-IN')}
                        tickLine={false} axisLine={false}
                      />
                      <Tooltip
                        contentStyle={{
                          background: 'color-mix(in srgb, var(--surface-3) 88%, transparent)',
                          backdropFilter: 'blur(12px)',
                          border: '1px solid var(--line-2)',
                          borderRadius: 'var(--r-sm)',
                          fontSize: 11,
                          color: 'var(--fg-primary)',
                        }}
                        formatter={(value: number, name: string) => [
                          `₹${value.toLocaleString('en-IN')}`,
                          name === 'pnlTarget' ? 'P/L at target' : 'P/L at expiry',
                        ]}
                        labelFormatter={(label: number) => `Spot: ${label.toLocaleString('en-IN')}`}
                      />
                      <ReferenceLine y={0} stroke="var(--fg-muted)" strokeWidth={1} />
                      <ReferenceLine
                        x={Math.round(NIFTY_SPOT)}
                        stroke="var(--accent)"
                        strokeDasharray="5 5"
                        label={{
                          value: NIFTY_SPOT.toLocaleString('en-IN', { maximumFractionDigits: 1 }),
                          position: 'top',
                          fill: 'var(--accent)',
                          fontSize: 11,
                          fontWeight: 700,
                        }}
                      />
                      <Area type="monotone" dataKey="pnlExpiry" stroke="var(--accent)" fill="url(#payoffGradientPos)" strokeWidth={2.25} />
                      <Area type="monotone" dataKey="pnlTarget" stroke="#c084fc" fill="none" strokeWidth={1.5} strokeDasharray="5 3" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div style={{ display: 'grid', placeItems: 'center', height: 360, color: 'var(--fg-muted)', fontSize: 12, padding: 20, textAlign: 'center' }}>
                  {activeTab === 'timeseries' ? 'Time-series plot lights up when the strategy has run data.' : 'Option chain view appears here when you select an expiry.'}
                </div>
              )}

              {/* Target date selector */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px', borderTop: '1px solid var(--line-2)',
                fontSize: 11, color: 'var(--fg-muted)',
              }}>
                <span>Target date · <strong style={{ color: 'var(--fg-primary)', fontWeight: 600 }}>6 days from expiry</strong></span>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <button style={btnIconSm}><Minus size={10} /></button>
                  <span className="lt-tabular" style={{ fontSize: 11, fontWeight: 700, color: 'var(--fg-primary)' }}>25 Mar 26</span>
                  <button style={btnIconSm}><Plus size={10} /></button>
                </div>
              </div>
            </div>
          </BentoCard>

          {/* SD markers */}
          <div
            style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6,
              padding: '10px 14px', borderRadius: 'var(--r-md)',
              background: 'var(--surface-2)', border: '1px solid var(--line-2)',
            }}
          >
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>Standard deviations</span>
            <div style={{ display: 'inline-flex', gap: 4 }}>
              {['-2σ', '-1σ', 'Spot', '+1σ', '+2σ', '+3σ'].map((sd) => {
                const isSpot = sd === 'Spot';
                return (
                  <span
                    key={sd}
                    style={{
                      padding: '3px 8px', borderRadius: 999,
                      fontSize: 10, fontWeight: 700,
                      background: isSpot ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'var(--surface-3)',
                      border: `1px solid ${isSpot ? 'color-mix(in srgb, var(--accent) 32%, transparent)' : 'var(--line-2)'}`,
                      color: isSpot ? 'var(--accent-2)' : 'var(--fg-muted)',
                    }}
                  >
                    {sd}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 1100px) {
          .strategy-detail-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

/* ─── Detail view atoms ─────────────────────────────────────────── */

function MetricTile({
  label, value, sub, color,
}: { label: string; value: string; sub?: string; color: string }) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 8 },
        visible: { opacity: 1, y: 0, transition: { duration: 0.24, ease: [0.22, 1, 0.36, 1] } },
      }}
      className="lt-bento"
      style={{ padding: '14px 16px' }}
    >
      <p style={miniLabel}>{label}</p>
      <p className="lt-tabular" style={{ fontSize: 18, fontWeight: 700, color, margin: '6px 0 0', letterSpacing: '-0.02em' }}>{value}</p>
      {sub && <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '2px 0 0' }}>{sub}</p>}
    </motion.div>
  );
}

function SectionHeader({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 14px', borderBottom: '1px solid var(--line-2)',
        gap: 10, flexWrap: 'wrap',
      }}
    >
      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)' }}>{title}</span>
      {right}
    </div>
  );
}

function Stepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 2, padding: 2,
        borderRadius: 'var(--r-sm)',
        background: 'var(--surface-4)', border: '1px solid var(--line-2)',
      }}
    >
      <button style={{ ...btnIconSm, background: 'transparent', border: 'none' }} onClick={() => onChange(value - 1)} aria-label="Decrease">
        <Minus size={10} />
      </button>
      <span className="lt-tabular" style={{ minWidth: 22, textAlign: 'center', fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)' }}>{value}</span>
      <button style={{ ...btnIconSm, background: 'transparent', border: 'none' }} onClick={() => onChange(value + 1)} aria-label="Increase">
        <Plus size={10} />
      </button>
    </div>
  );
}

/* ─── Detail view styles ────────────────────────────────────────── */
const miniLabel: React.CSSProperties = {
  fontSize: 9, fontWeight: 800, letterSpacing: '0.12em',
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
};
const th: React.CSSProperties = {
  padding: '10px 12px', textAlign: 'left',
  fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
  color: 'var(--fg-muted)',
};
const tdTight: React.CSSProperties = {
  padding: '10px 12px', fontSize: 12,
  color: 'var(--fg-primary)',
};
const btnChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  padding: '5px 10px', borderRadius: 'var(--r-sm)',
  fontSize: 11, fontWeight: 600, color: 'var(--fg-secondary)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  cursor: 'pointer',
};
const btnGhost: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '6px 12px', borderRadius: 'var(--r-sm)',
  fontSize: 11, fontWeight: 600, color: 'var(--fg-secondary)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  cursor: 'pointer',
};
const btnOutline: React.CSSProperties = {
  flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
  padding: '11px 14px', borderRadius: 'var(--r-sm)',
  fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  cursor: 'pointer',
};
const btnPrimary: React.CSSProperties = {
  flex: 2, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
  padding: '11px 16px', borderRadius: 'var(--r-sm)',
  fontSize: 12, fontWeight: 700, color: '#fff',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--bull) 95%, white 5%), var(--bull))',
  border: '1px solid color-mix(in srgb, var(--bull) 55%, transparent)',
  cursor: 'pointer',
  boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--bull) 28%, transparent)',
};
const btnIconSm: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 22, height: 22, borderRadius: 6,
  color: 'var(--fg-muted)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  cursor: 'pointer',
};

// ─── Main Strategies Page ───────────────────────────────────────────────────

export default function StrategiesPage() {
  const [tab, setTab] = useState<'prebuilt' | 'saved'>('prebuilt');
  const [filter, setFilter] = useState<FilterMode>('All');
  const [selectedStrategy, setSelectedStrategy] = useState<OptionStrategy | null>(null);

  const filtered = useMemo(() => {
    if (filter === 'All') return PRE_BUILT_STRATEGIES;
    return PRE_BUILT_STRATEGIES.filter((s) => s.sentiment === filter);
  }, [filter]);

  // If a strategy is selected, show the detail/builder view
  if (selectedStrategy) {
    return (
      <StrategyDetailView
        strategy={selectedStrategy}
        onBack={() => setSelectedStrategy(null)}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<TrendingUp size={16} />}
        title="Options Strategies"
        subtitle="Pre-built and saved multi-leg option strategy templates"
      />

      {/* Toolbar: Instrument + Tabs + Filters */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'auto 1fr auto',
          alignItems: 'center',
          gap: 14,
          padding: '12px 14px',
          borderRadius: 'var(--r-md)',
          background: 'var(--surface-2)',
          border: '1px solid var(--line-2)',
          boxShadow: 'var(--elev-1)',
        }}
        className="strategies-toolbar"
      >
        {/* Instrument pill */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 10,
            padding: '7px 12px',
            borderRadius: 'var(--r-sm)',
            background: 'var(--surface-3)',
            border: '1px solid var(--line-2)',
          }}
        >
          <span style={{ fontSize: 10, letterSpacing: '0.08em', fontWeight: 800, color: 'var(--fg-muted)', textTransform: 'uppercase' }}>NSE</span>
          <span style={{ width: 1, height: 14, background: 'var(--line-2)' }} />
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)' }}>NIFTY</span>
          <span className="lt-tabular" style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)', letterSpacing: '-0.02em' }}>
            {NIFTY_SPOT.toLocaleString('en-IN')}
          </span>
          <span
            className="lt-tabular"
            style={{
              fontSize: 11, fontWeight: 700,
              padding: '2px 7px', borderRadius: 6,
              color: 'var(--bull)', background: 'var(--bull-soft)',
            }}
          >
            +{NIFTY_CHANGE} ({NIFTY_CHANGE_PCT}%)
          </span>
        </div>

        {/* Segmented tabs */}
        <div
          role="tablist"
          aria-label="Strategy source"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 2, padding: 3,
            borderRadius: 'var(--r-sm)', background: 'var(--surface-4)',
            border: '1px solid var(--line-2)',
            justifySelf: 'start',
          }}
        >
          {(['prebuilt', 'saved'] as const).map((t) => {
            const active = tab === t;
            return (
              <button
                key={t}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t)}
                style={{
                  padding: '6px 14px', borderRadius: 6,
                  fontSize: 11, fontWeight: 600,
                  color: active ? 'var(--fg-primary)' : 'var(--fg-muted)',
                  background: active ? 'var(--surface-2)' : 'transparent',
                  border: active ? '1px solid var(--line-2)' : '1px solid transparent',
                  boxShadow: active ? 'var(--elev-1)' : 'none',
                  cursor: 'pointer',
                  transition: 'background 120ms var(--ease-out), color 120ms var(--ease-out)',
                }}
              >
                {t === 'prebuilt' ? 'Pre-built' : 'Saved'}
              </button>
            );
          })}
        </div>

        {/* Sentiment filter pills */}
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {(['All', 'Bullish', 'Bearish', 'Neutral', 'Volatile'] as FilterMode[]).map((f) => {
            const active = filter === f;
            const sc = f !== 'All' ? SENTIMENT_COLORS[f as Sentiment] : null;
            const Icon = sc?.icon;
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '6px 10px', borderRadius: 999,
                  fontSize: 11, fontWeight: 600,
                  color: active ? (sc?.text ?? 'var(--accent-2)') : 'var(--fg-muted)',
                  background: active
                    ? (sc?.bg ?? 'color-mix(in srgb, var(--accent) 14%, transparent)')
                    : 'var(--surface-3)',
                  border: active
                    ? `1px solid color-mix(in srgb, ${sc?.text ?? 'var(--accent)'} 32%, transparent)`
                    : '1px solid var(--line-2)',
                  cursor: 'pointer',
                  transition: 'all 120ms var(--ease-out)',
                }}
              >
                {Icon && <Icon size={11} />}
                <span>{f}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Result count */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11, color: 'var(--fg-muted)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          {tab === 'prebuilt' ? `${filtered.length} ${filter === 'All' ? 'strategies' : filter.toLowerCase() + ' strategies'}` : 'Saved library'}
        </span>
      </div>

      {/* Strategy Grid */}
      {tab === 'prebuilt' ? (
        filtered.length === 0 ? (
          <EmptyState
            icon={<TrendingUp size={24} />}
            title={`No ${filter === 'All' ? '' : filter + ' '}strategies match`}
            blurb="Try a different sentiment filter."
          />
        ) : (
          <motion.div
            initial="hidden"
            animate="visible"
            variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.04 } } }}
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: 14,
            }}
          >
            {filtered.map((strategy) => (
              <motion.div
                key={strategy.id}
                variants={{
                  hidden: { opacity: 0, y: 10 },
                  visible: { opacity: 1, y: 0, transition: { duration: 0.26, ease: [0.22, 1, 0.36, 1] } },
                }}
              >
                <StrategyCard
                  strategy={strategy}
                  onBuild={() => setSelectedStrategy(strategy)}
                  onViewLegs={() => setSelectedStrategy(strategy)}
                />
              </motion.div>
            ))}
          </motion.div>
        )
      ) : (
        <EmptyState
          icon={<Save size={24} />}
          title="No saved strategies yet"
          blurb="Build a strategy and save it to see it here."
        />
      )}

      <style>{`
        @media (max-width: 900px) {
          .strategies-toolbar {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}

/* ─── Empty state ─────────────────────────────────────────────────── */
function EmptyState({ icon, title, blurb }: { icon: React.ReactNode; title: string; blurb: string }) {
  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '48px 24px', textAlign: 'center',
        borderRadius: 'var(--r-lg)',
        background: 'var(--surface-2)',
        border: '1px dashed var(--line-2)',
      }}
    >
      <div style={{
        width: 52, height: 52, borderRadius: '50%',
        display: 'grid', placeItems: 'center',
        background: 'color-mix(in srgb, var(--fg-muted) 10%, transparent)',
        color: 'var(--fg-muted)',
        marginBottom: 12,
      }}>
        {icon}
      </div>
      <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg-primary)', margin: 0 }}>{title}</p>
      <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '4px 0 0' }}>{blurb}</p>
    </div>
  );
}
