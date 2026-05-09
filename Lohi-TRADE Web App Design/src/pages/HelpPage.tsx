import { useMemo, useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  BookOpen, Search, ExternalLink, ChevronRight, Copy, Check,
  Rocket, Building2, Zap, FlaskConical, ShieldAlert, FileArchive,
  IndianRupee, Users, Info,
} from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';

/**
 * HelpPage — spec §2.22 /help
 *
 * Offline-first documentation bundled with the app. Each article is written
 * inline so it renders instantly with no network. Sections are grouped by
 * intent, every heading is anchor-linkable, and the search filters across
 * titles + blurbs + full body text.
 */

/* ─── Content types ──────────────────────────────────────────────────── */
type ContentBlock =
  | { type: 'para'; text: string }
  | { type: 'heading'; text: string }
  | { type: 'code'; lang?: string; code: string }
  | { type: 'list'; items: string[] }
  | { type: 'kvs'; items: { k: string; v: string }[] }
  | { type: 'callout'; tone: 'info' | 'warn' | 'danger'; title?: string; text: string };

interface Article {
  id: string;
  section: string;
  title: string;
  blurb: string;
  icon: React.ElementType;
  body: ContentBlock[];
}

/* ─── Sections ───────────────────────────────────────────────────────── */
const SECTIONS = [
  { id: 'start', label: 'Getting Started', icon: Rocket },
  { id: 'broker', label: 'Broker Setup', icon: Building2 },
  { id: 'strat', label: 'Strategies', icon: Zap },
  { id: 'back', label: 'Backtesting', icon: FlaskConical },
  { id: 'live', label: 'Going Live', icon: ShieldAlert },
  { id: 'ops', label: 'Operations', icon: FileArchive },
  { id: 'india', label: 'India-specific', icon: IndianRupee },
  { id: 'comm', label: 'Community & Legal', icon: Users },
] as const;

/* ─── Full article content ───────────────────────────────────────────── */
const ARTICLES: Article[] = [
  // ═════ Getting Started ═════
  {
    id: 'qs',
    section: 'start',
    icon: Rocket,
    title: '5-minute quickstart',
    blurb: 'Install, connect a broker, run your first paper strategy.',
    body: [
      { type: 'para', text: 'LOHI-TRADE is a self-hosted algorithmic trading platform for Indian markets. You run it on your own machine or VPS; it connects to your broker using your own API credentials. Nothing runs on our servers.' },
      { type: 'heading', text: 'Prerequisites' },
      { type: 'list', items: [
        'Linux, macOS, or Windows with Docker installed',
        'A broker account with API access (Zerodha, Dhan, Upstox, Fyers, or Angel One)',
        '2 vCPU / 4 GB RAM / 20 GB disk minimum',
      ] },
      { type: 'heading', text: 'Install' },
      { type: 'code', lang: 'bash', code: `git clone https://github.com/lohi-trade/lohi-trade-oss
cd lohi-trade-oss
cp .env.example .env
# edit .env — set DOMAIN and MASTER_ENCRYPTION_KEY
openssl rand -base64 32  # use this for MASTER_ENCRYPTION_KEY
docker compose up -d` },
      { type: 'para', text: 'Open https://your-domain in a browser. The setup wizard walks you through creating the admin account, enabling 2FA, and setting safety defaults.' },
      { type: 'heading', text: 'First paper strategy' },
      { type: 'list', items: [
        'Navigate to Settings → Brokers and add your broker credentials',
        'Go to Strategies and pick a bundled template (e.g., SMA Crossover)',
        'Click Configure, pick a symbol, then Save & Start',
        'Orders and fills show up under Positions and Orders in real time',
      ] },
      { type: 'callout', tone: 'info', title: 'You start in PAPER mode', text: 'Every new install starts in PAPER mode. Live trading must be explicitly enabled via a 3-step gated flow in Risk Settings.' },
    ],
  },
  {
    id: 'arch',
    section: 'start',
    icon: Info,
    title: 'Architecture overview',
    blurb: 'Modular monolith, containers, data flow.',
    body: [
      { type: 'para', text: 'LOHI-TRADE is a modular monolith: four main services communicate over a local network inside a Docker Compose stack. There is no SaaS component.' },
      { type: 'kvs', items: [
        { k: 'web', v: 'Next.js 14 frontend (React 18, Tailwind, shadcn/ui)' },
        { k: 'api', v: 'FastAPI REST + WebSocket — auth, CRUD, session, order routing' },
        { k: 'engine', v: 'Strategy runtime, tick handler, pre-trade risk, broker adapters' },
        { k: 'worker', v: 'APScheduler — token refresh, reconciliation, backups, square-off' },
        { k: 'db', v: 'SQLite 3.45 (default) or PostgreSQL 16 (opt-in)' },
        { k: 'caddy', v: 'Reverse proxy with automatic HTTPS via Let\'s Encrypt' },
      ] },
      { type: 'heading', text: 'Data flow (market data)' },
      { type: 'para', text: 'Broker WebSocket → engine tick handler → in-memory bus → strategy instances → optional Parquet tick storage → web socket fan-out to the browser.' },
      { type: 'heading', text: 'Data flow (orders)' },
      { type: 'para', text: 'Strategy or manual ticket → pre-trade risk gate → broker adapter → broker REST API → order event → orders table → web socket push to UI.' },
    ],
  },

  // ═════ Broker Setup ═════
  {
    id: 'zer',
    section: 'broker',
    icon: Building2,
    title: 'Zerodha Kite',
    blurb: 'API key, TOTP seed, daily token exchange.',
    body: [
      { type: 'para', text: 'Zerodha uses Kite Connect for API access. Requires an API subscription (~₹2,000/month). Token must be refreshed daily via a login flow.' },
      { type: 'heading', text: 'What you need' },
      { type: 'list', items: [
        'API Key and API Secret from developers.kite.trade',
        'Your Kite user ID (the short code like ZA1234)',
        'Your Kite password',
        'TOTP seed (exposed when you enable 2FA in Kite web)',
      ] },
      { type: 'heading', text: 'Steps' },
      { type: 'list', items: [
        'Create a new app at https://developers.kite.trade/apps/new',
        'Set redirect URL to https://your-domain/api/brokers/zerodha/callback',
        'Copy the API key + secret; paste them in Settings → Brokers → Zerodha',
        'Enter your user ID, password, and TOTP seed',
        'Click Test Connection — you should see your profile',
      ] },
      { type: 'callout', tone: 'warn', title: 'Daily login', text: 'Kite tokens expire at 6 AM IST every day. The worker container performs the login automatically; keep your TOTP seed encrypted and available.' },
      { type: 'heading', text: 'Rate limits' },
      { type: 'kvs', items: [
        { k: 'Orders', v: '10 requests/second' },
        { k: 'Other REST', v: '3 requests/second' },
        { k: 'WebSocket', v: '1 connection per API key, up to 3000 symbols' },
      ] },
    ],
  },
  {
    id: 'dhn',
    section: 'broker',
    icon: Building2,
    title: 'Dhan',
    blurb: 'Long-lived access token flow.',
    body: [
      { type: 'para', text: 'Dhan provides a simple access-token flow — no daily refresh, no OAuth redirect. The token is valid for months. Free API access.' },
      { type: 'heading', text: 'What you need' },
      { type: 'list', items: [
        'Access token from https://dhanhq.co/api',
        'Your Dhan client ID',
      ] },
      { type: 'heading', text: 'Steps' },
      { type: 'list', items: [
        'Log in to web.dhan.co and open Profile → DhanHQ Access',
        'Generate a long-lived token; copy it immediately',
        'Settings → Brokers → Dhan: paste the token and client ID',
        'Test Connection',
      ] },
      { type: 'kvs', items: [
        { k: 'Orders', v: '25 requests/second' },
        { k: 'Cost', v: 'Free' },
      ] },
    ],
  },
  {
    id: 'ups',
    section: 'broker',
    icon: Building2,
    title: 'Upstox',
    blurb: 'OAuth 2.0 with 24h access token.',
    body: [
      { type: 'para', text: 'Upstox uses OAuth 2.0 Authorization Code flow. The app opens a popup for consent; after the redirect, LOHI-TRADE exchanges the code for a 24-hour access token.' },
      { type: 'heading', text: 'Steps' },
      { type: 'list', items: [
        'Create an app at https://account.upstox.com/developer/apps',
        'Set redirect URL: https://your-domain/api/brokers/upstox/callback',
        'Copy API key + secret into Settings → Brokers → Upstox',
        'Click Connect — a popup opens; log in and grant access',
        'Upstox redirects back; the token is stored encrypted',
      ] },
      { type: 'kvs', items: [
        { k: 'Orders', v: '50 requests/second' },
        { k: 'Cost', v: 'Free' },
      ] },
    ],
  },
  {
    id: 'fys',
    section: 'broker',
    icon: Building2,
    title: 'Fyers',
    blurb: 'OAuth 2.0 with PIN entry.',
    body: [
      { type: 'para', text: 'Fyers uses OAuth 2.0 plus a 4-digit trading PIN. The access token lasts through the trading day.' },
      { type: 'heading', text: 'Steps' },
      { type: 'list', items: [
        'Create app at https://myapi.fyers.in',
        'Set redirect URI: https://your-domain/api/brokers/fyers/callback',
        'Copy App ID + Secret Key',
        'Settings → Brokers → Fyers: paste credentials + your 4-digit PIN',
        'Click Connect; login popup appears',
      ] },
    ],
  },
  {
    id: 'ang',
    section: 'broker',
    icon: Building2,
    title: 'Angel One SmartAPI',
    blurb: 'Daily TOTP-based login.',
    body: [
      { type: 'para', text: 'Angel One regenerates the session daily using your MPIN + TOTP, similar to Zerodha. Free API access.' },
      { type: 'heading', text: 'What you need' },
      { type: 'list', items: [
        'API Key from smartapi.angelbroking.com',
        'Client code (the short alphanumeric ID)',
        'MPIN (4-digit)',
        'TOTP seed from SmartAPI dashboard',
      ] },
      { type: 'heading', text: 'Steps' },
      { type: 'list', items: [
        'Register an app on SmartAPI',
        'Whitelist your redirect URL',
        'Enter credentials in Settings → Brokers → Angel One',
        'Test Connection',
      ] },
    ],
  },

  // ═════ Strategies ═════
  {
    id: 'strat',
    section: 'strat',
    icon: Zap,
    title: 'Writing your first strategy',
    blurb: 'Base class, parameters, lifecycle hooks.',
    body: [
      { type: 'para', text: 'Strategies are Python classes placed in the strategies/ directory. They are auto-discovered on startup and hot-reloaded in dev mode.' },
      { type: 'heading', text: 'Minimal example' },
      { type: 'code', lang: 'python', code: `from lohi_core import Strategy, Tick, Bar, OrderEvent

class SmaCrossover(Strategy):
    name = "sma_crossover"
    symbols = ["RELIANCE", "TCS"]

    parameters = {
        "fast": 20,
        "slow": 50,
        "quantity": 1,
    }

    def on_start(self):
        self.fast_sma = []
        self.slow_sma = []

    def on_bar(self, bar: Bar):
        # called on every 1-minute bar close
        self.fast_sma.append(bar.close)
        self.slow_sma.append(bar.close)
        if len(self.slow_sma) < self.parameters["slow"]:
            return
        fast = sum(self.fast_sma[-self.parameters["fast"]:]) / self.parameters["fast"]
        slow = sum(self.slow_sma[-self.parameters["slow"]:]) / self.parameters["slow"]
        if fast > slow and self.position(bar.symbol) == 0:
            self.buy(bar.symbol, self.parameters["quantity"])
        elif fast < slow and self.position(bar.symbol) > 0:
            self.sell(bar.symbol, self.position(bar.symbol))` },
      { type: 'heading', text: 'Lifecycle hooks' },
      { type: 'kvs', items: [
        { k: 'on_start', v: 'Called once when the strategy starts' },
        { k: 'on_tick', v: 'Called on every market tick (high-frequency)' },
        { k: 'on_bar', v: 'Called on each bar close (1m/5m/15m/1h/1D)' },
        { k: 'on_order_event', v: 'Called when your order changes state' },
        { k: 'on_stop', v: 'Called once when the strategy stops' },
      ] },
      { type: 'heading', text: 'Two strategy styles' },
      { type: 'list', items: [
        'Soldier — single-symbol, parameter-driven unit (most strategies are soldiers)',
        'Commander — orchestrates multiple soldiers with portfolio allocation and risk rules',
      ] },
    ],
  },

  // ═════ Backtesting ═════
  {
    id: 'bt',
    section: 'back',
    icon: FlaskConical,
    title: 'Backtesting guide',
    blurb: 'Data sources, slippage, walk-forward.',
    body: [
      { type: 'para', text: 'The backtester runs strategies against historical data with semantics identical to live trading. A strategy that passes backtest will behave the same way in paper and live mode.' },
      { type: 'heading', text: 'Data sources' },
      { type: 'kvs', items: [
        { k: 'User CSV', v: 'Upload your own OHLCV files (Kite/Dhan compatible)' },
        { k: 'NSE Bhavcopy', v: 'Auto-downloaded from NSE\'s public archive — free, official' },
        { k: 'Yahoo Finance', v: 'Via yfinance — educational only, may rate-limit' },
      ] },
      { type: 'heading', text: 'Execution settings' },
      { type: 'list', items: [
        'Starting capital and lot multiplier',
        'Slippage model (fixed bps, percentage, or market-impact linear)',
        'Commission model (Zerodha, Dhan, Upstox, or custom)',
        'Fill policy: next-bar-open or current-bar-close',
      ] },
      { type: 'heading', text: 'Optimization' },
      { type: 'list', items: [
        'Single run — one set of parameters',
        'Grid search — sweep parameter ranges in parallel',
        'Walk-forward — train on a window, test on the next, roll forward',
      ] },
      { type: 'callout', tone: 'warn', title: 'Overfitting warning', text: 'A strategy tuned to historical data can look perfect on backtest and lose money in live. Always validate with out-of-sample data and at least one paper session before going live.' },
    ],
  },

  // ═════ Going Live ═════
  {
    id: 'live',
    section: 'live',
    icon: ShieldAlert,
    title: 'Pre-flight checklist',
    blurb: 'Risk caps, kill switch, paper validation, activation flow.',
    body: [
      { type: 'callout', tone: 'danger', title: 'Before enabling LIVE', text: 'Live mode routes every order to your real broker. Losses are real. LOHI-TRADE ships paper-first by design; overriding that is a deliberate, multi-gate action.' },
      { type: 'heading', text: 'Non-negotiable steps' },
      { type: 'list', items: [
        'Connect and test at least one broker',
        'Run at least one full paper-trading session end-to-end',
        'Review risk caps (max order value, max positions, daily loss)',
        'Verify the kill switch works (Settings → Risk → Trigger kill switch → Reset)',
        'Confirm 2FA is enabled — LOHI-TRADE refuses to enable live without it',
      ] },
      { type: 'heading', text: 'Activation flow' },
      { type: 'list', items: [
        'Step 1 — tick 6 confirmation boxes',
        'Step 2 — re-authenticate with password + current TOTP',
        'Step 3 — type ENABLE LIVE TRADING exactly',
      ] },
      { type: 'para', text: 'After activation, the app banner turns red, an audit-log entry is recorded, and every subsequent order is real.' },
    ],
  },
  {
    id: 'risk',
    section: 'live',
    icon: ShieldAlert,
    title: 'Risk controls explained',
    blurb: 'How pre-trade checks, kill switch, and reconciliation interact.',
    body: [
      { type: 'heading', text: 'Pre-trade checks' },
      { type: 'para', text: 'Every order — manual or automated — passes through a check pipeline before the broker adapter is invoked:' },
      { type: 'list', items: [
        'Kill switch state (reject if active)',
        'Trading mode gate (paper orders never reach real broker)',
        'Max order value (notional cap)',
        'Max open positions (total and per-strategy)',
        'Price sanity (reject if price is ±5% from last tick)',
        'Rate limit (max orders/minute)',
        'Product-specific checks (short selling, F&O, options writing)',
        'Session window (only during configured hours)',
      ] },
      { type: 'heading', text: 'Kill switch triggers' },
      { type: 'list', items: [
        'UI button in the navbar (2-click confirm)',
        'API endpoint: POST /api/kill-switch',
        'Unix signal SIGUSR1 on the engine container (CLI-friendly)',
        'Automatic on daily loss limit breach',
        'Automatic after 3 consecutive broker auth failures',
      ] },
      { type: 'heading', text: 'Reconciliation' },
      { type: 'para', text: 'A worker job every 30 seconds compares local orders and positions with broker truth. Any discrepancy creates an audit entry and alerts the user.' },
    ],
  },

  // ═════ Operations ═════
  {
    id: 'back',
    section: 'ops',
    icon: FileArchive,
    title: 'Backup & restore',
    blurb: 'lohi backup, restic, borgbackup, rotating DB.',
    body: [
      { type: 'para', text: 'LOHI-TRADE ships a CLI backup tool. We strongly recommend pairing it with restic or borgbackup for encrypted off-site copies.' },
      { type: 'code', lang: 'bash', code: `# Create an encrypted timestamped archive
docker compose exec api lohi backup
# → data/backups/lohi-20260427-143022.tar.gz

# Off-site encrypted backup with restic
restic -r s3:s3.amazonaws.com/my-bucket backup ./data/backups
restic -r s3:s3.amazonaws.com/my-bucket prune

# Restore
docker compose exec api lohi restore data/backups/lohi-20260427-143022.tar.gz` },
      { type: 'callout', tone: 'info', title: 'Sample cron entry', text: '0 2 * * * cd /opt/lohi-trade-oss && docker compose exec -T api lohi backup && restic -r s3:... backup ./data/backups > /dev/null' },
    ],
  },
  {
    id: 'doc',
    section: 'ops',
    icon: FileArchive,
    title: 'Troubleshooting · lohi doctor',
    blurb: 'Local diagnostic bundle — never transmitted.',
    body: [
      { type: 'para', text: 'lohi doctor runs a health check and produces a redacted diagnostic bundle. The bundle is saved locally only; LOHI-TRADE never transmits it anywhere. You decide whether to share it when asking for support.' },
      { type: 'code', lang: 'bash', code: `docker compose exec api lohi doctor --since=1h
# → data/diagnostics/lohi-diag-20260427-144530.tar.gz` },
      { type: 'heading', text: 'What the bundle contains' },
      { type: 'list', items: [
        'Recent structured logs from every service (last N hours)',
        'Audit log entries relevant to recent orders',
        'System metrics snapshot (CPU, memory, DB size)',
        'Broker heartbeat history',
        'Configuration (with all secrets redacted)',
      ] },
    ],
  },

  // ═════ India-specific ═════
  {
    id: 'tax',
    section: 'india',
    icon: IndianRupee,
    title: 'Taxes & charges',
    blurb: 'STT, GST, stamp duty, capital gains, STCG vs business income.',
    body: [
      { type: 'para', text: 'LOHI-TRADE computes order-level charges at the time of review so you see the real cost before confirming. It does NOT file taxes — that remains your responsibility.' },
      { type: 'heading', text: 'Per-order charges (equity)' },
      { type: 'kvs', items: [
        { k: 'STT (sell side)', v: '0.025% — delivery/intraday equity sell' },
        { k: 'Stamp duty (buy side)', v: '0.015% — capped at ₹1,500/day' },
        { k: 'GST', v: '18% on (brokerage + exchange txn fees)' },
        { k: 'Exchange txn charges', v: '0.00345% NSE, similar on BSE' },
        { k: 'SEBI fees', v: '0.0001%' },
        { k: 'Brokerage', v: 'Varies by broker — typically ₹0–20/order' },
      ] },
      { type: 'heading', text: 'Tax treatment' },
      { type: 'list', items: [
        'Delivery equity: STCG @ 20% if sold < 1 year, LTCG @ 12.5% above ₹1.25L/year otherwise',
        'Intraday equity & F&O: treated as business income, taxed at slab rates',
        'Audit required if turnover exceeds thresholds or if declaring loss',
      ] },
      { type: 'callout', tone: 'warn', text: 'Consult a CA. This page is a starting point, not tax advice. Thresholds and rates change annually — always verify against current Income-Tax Act provisions.' },
    ],
  },
  {
    id: 'sebi',
    section: 'india',
    icon: IndianRupee,
    title: 'SEBI algo-trading notes',
    blurb: 'What to verify with your broker before enabling automation.',
    body: [
      { type: 'para', text: 'SEBI\'s algorithmic trading framework for retail is still evolving. The practical requirements vary by broker — always verify with yours before enabling LIVE mode.' },
      { type: 'heading', text: 'Common questions to ask your broker' },
      { type: 'list', items: [
        'Does the broker require pre-approval of algo strategies?',
        'Is there a high-frequency threshold beyond which exchange registration is needed?',
        'Are retail algo users allowed to co-locate or use low-latency connections?',
        'What audit-trail records does the broker require you to maintain?',
      ] },
      { type: 'callout', tone: 'info', text: 'LOHI-TRADE is not a SEBI-registered intermediary. It is software that connects to your broker using your credentials. All regulatory obligations (KYC, tax, algo approvals if required) rest with you and your broker.' },
    ],
  },

  // ═════ Community & Legal ═════
  {
    id: 'contrib',
    section: 'comm',
    icon: Users,
    title: 'Contributing',
    blurb: 'Good-first-issues, governance, code of conduct.',
    body: [
      { type: 'para', text: 'Contributions are welcome under the AGPL-3.0 license for platform code and Apache-2.0 for the core library.' },
      { type: 'heading', text: 'Where to start' },
      { type: 'list', items: [
        'Browse issues tagged good-first-issue on GitHub',
        'Read CONTRIBUTING.md and CODE_OF_CONDUCT.md in the repo',
        'Join the community Discord for real-time questions',
        'Open GitHub Discussions for larger design proposals',
      ] },
      { type: 'heading', text: 'Governance' },
      { type: 'para', text: 'Benevolent-dictator model initially, transitioning to a meritocratic committer model after 50+ contributors have merged pull requests.' },
    ],
  },
  {
    id: 'faq',
    section: 'comm',
    icon: Users,
    title: 'FAQ',
    blurb: 'Common install, broker, and mode questions.',
    body: [
      { type: 'heading', text: 'Does LOHI-TRADE ever touch my money?' },
      { type: 'para', text: 'No. All funds stay in your broker account. LOHI-TRADE reads your margin and routes orders using your broker credentials. It never acts as a custodian. This is a deliberate architectural choice to keep you out of SEBI intermediary territory.' },
      { type: 'heading', text: 'Can I run multiple brokers at once?' },
      { type: 'para', text: 'Yes. Configure each broker under Settings → Brokers. Route strategies or manual orders to a specific broker in the order ticket.' },
      { type: 'heading', text: 'How do I change the admin password?' },
      { type: 'para', text: 'Settings → Profile → Change password. Requires current password + TOTP.' },
      { type: 'heading', text: 'I lost my TOTP authenticator.' },
      { type: 'para', text: 'Use your 12-word recovery phrase: Login → "Use backup code" → proceed to Settings → Profile → Reset TOTP. If you lost the phrase too, recovery requires CLI access: docker compose exec api lohi reset-password.' },
      { type: 'heading', text: 'How do I update LOHI-TRADE?' },
      { type: 'code', lang: 'bash', code: `cd lohi-trade-oss
git pull
docker compose pull
docker compose up -d
# migrations run automatically` },
    ],
  },
  {
    id: 'legal',
    section: 'comm',
    icon: Users,
    title: 'License, disclaimers, warranty',
    blurb: 'AGPL-3.0, no investment advice, user responsibility.',
    body: [
      { type: 'callout', tone: 'danger', title: 'Trading risk disclosure', text: 'Algorithmic trading carries substantial risk of loss. You may lose all invested capital. The authors provide no investment advice and are not registered with SEBI. You are solely responsible for your trading decisions and compliance with applicable law.' },
      { type: 'heading', text: 'Licensing' },
      { type: 'kvs', items: [
        { k: 'Platform (apps/*)', v: 'AGPL-3.0-or-later' },
        { k: 'Core library (lohi-core, broker-adapters)', v: 'Apache-2.0' },
        { k: 'UI components', v: 'MIT' },
        { k: 'Documentation', v: 'CC-BY-4.0' },
      ] },
      { type: 'heading', text: 'Warranty' },
      { type: 'para', text: 'Provided "AS IS" without warranty of any kind. The authors are not liable for trading losses, data loss, or misuse. See LICENSE and SECURITY.md in the repo for full terms and responsible-disclosure guidelines.' },
    ],
  },
];

/* ─── Main component ─────────────────────────────────────────────────── */
export default function HelpPage() {
  const [query, setQuery] = useState('');
  const [activeId, setActiveId] = useState<string>(ARTICLES[0].id);
  const [copiedBlock, setCopiedBlock] = useState<string | null>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);

  /* ── Full-text search ── */
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ARTICLES;
    return ARTICLES.filter((a) => {
      if (a.title.toLowerCase().includes(q)) return true;
      if (a.blurb.toLowerCase().includes(q)) return true;
      const bodyText = a.body.map((b) => {
        if (b.type === 'para' || b.type === 'heading') return b.text;
        if (b.type === 'code') return b.code;
        if (b.type === 'list') return b.items.join(' ');
        if (b.type === 'kvs') return b.items.map((i) => `${i.k} ${i.v}`).join(' ');
        if (b.type === 'callout') return (b.title ?? '') + ' ' + b.text;
        return '';
      }).join(' ').toLowerCase();
      return bodyText.includes(q);
    });
  }, [query]);

  const bySection = useMemo(() => {
    const groups: Record<string, Article[]> = {};
    for (const a of filtered) (groups[a.section] ??= []).push(a);
    return groups;
  }, [filtered]);

  // If search removes the current article, auto-switch.
  useEffect(() => {
    if (filtered.length && !filtered.find((a) => a.id === activeId)) {
      setActiveId(filtered[0].id);
    }
  }, [filtered, activeId]);

  const activeArticle = ARTICLES.find((a) => a.id === activeId);

  /* ── Cmd/Ctrl+K focuses the search ── */
  const searchInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        // cmd-K opens the global palette already; don't fight it.
        return;
      }
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const copyCode = (code: string, id: string) => {
    navigator.clipboard.writeText(code).then(() => {
      setCopiedBlock(id);
      setTimeout(() => setCopiedBlock(null), 1500);
    }).catch(() => {});
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<BookOpen size={16} />}
        title="Help & Docs"
        subtitle="Offline-first documentation · bundled with the app, no network required"
        actions={
          <a href="https://github.com/lohi-trade/lohi-trade-oss" target="_blank" rel="noreferrer" style={linkBtn}>
            <ExternalLink size={12} /> GitHub
          </a>
        }
      />

      {/* Search */}
      <div style={{ position: 'relative' }}>
        <Search size={14} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-muted)' }} />
        <input
          ref={searchInputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search docs — try 'broker', 'kill switch', 'backtest', 'tax'"
          style={{
            width: '100%', padding: '12px 80px 12px 40px', borderRadius: 'var(--r-md)',
            background: 'var(--surface-3)', border: '1px solid var(--line-2)',
            color: 'var(--fg-primary)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
          }}
        />
        <kbd style={{
          position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
          fontSize: 10, padding: '3px 7px', borderRadius: 4,
          background: 'var(--surface-4)', border: '1px solid var(--line-2)',
          color: 'var(--fg-muted)', fontFamily: 'ui-monospace, monospace',
        }}>/</kbd>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 18 }} className="help-grid">
        {/* ─── Index sidebar ─── */}
        <BentoCard>
          <div ref={sidebarRef} style={{ padding: 14, maxHeight: '70vh', overflowY: 'auto' }} className="lt-scroll">
            {Object.keys(bySection).length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: 0, padding: 8 }}>
                No articles match <strong style={{ color: 'var(--fg-primary)' }}>&quot;{query}&quot;</strong>.
              </p>
            ) : (
              SECTIONS.filter((s) => bySection[s.id]?.length).map((section) => {
                const Icon = section.icon;
                return (
                  <div key={section.id} style={{ marginBottom: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px 8px' }}>
                      <Icon size={12} style={{ color: 'var(--fg-muted)' }} />
                      <h4 style={{
                        fontSize: 10, fontWeight: 800, letterSpacing: '0.12em',
                        textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
                      }}>
                        {section.label}
                      </h4>
                    </div>
                    <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {bySection[section.id]?.map((a) => {
                        const selected = a.id === activeId;
                        return (
                          <li key={a.id}>
                            <button
                              onClick={() => setActiveId(a.id)}
                              style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                width: '100%', padding: '8px 10px', borderRadius: 'var(--r-sm)',
                                textAlign: 'left', cursor: 'pointer', border: 'none',
                                background: selected ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
                                color: selected ? 'var(--fg-primary)' : 'var(--fg-secondary)',
                                fontSize: 12, fontWeight: selected ? 600 : 500,
                                transition: 'background 120ms var(--ease-out), color 120ms var(--ease-out)',
                              }}
                              onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = 'var(--surface-4)'; }}
                              onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = 'transparent'; }}
                            >
                              <span>{a.title}</span>
                              <ChevronRight size={12} style={{ opacity: selected ? 1 : 0.4, color: selected ? 'var(--accent-2)' : 'inherit' }} />
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })
            )}
          </div>
        </BentoCard>

        {/* ─── Article reader ─── */}
        <BentoCard accent="indigo">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeId}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              style={{ padding: '28px 32px 36px', maxWidth: 780 }}
            >
              {activeArticle ? (
                <article>
                  <p style={{ fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', fontWeight: 800, color: 'var(--fg-muted)', margin: 0 }}>
                    {SECTIONS.find((s) => s.id === activeArticle.section)?.label}
                  </p>
                  <h2 style={{
                    fontSize: 26, fontWeight: 700, color: 'var(--fg-primary)',
                    margin: '8px 0 8px', letterSpacing: '-0.02em', lineHeight: 1.15,
                  }}>
                    {activeArticle.title}
                  </h2>
                  <p style={{ fontSize: 14, color: 'var(--fg-secondary)', lineHeight: 1.65, margin: '0 0 24px' }}>
                    {activeArticle.blurb}
                  </p>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    {activeArticle.body.map((block, i) => (
                      <BlockRenderer
                        key={i}
                        block={block}
                        copyCode={copyCode}
                        copied={copiedBlock === `${activeId}-${i}`}
                        blockId={`${activeId}-${i}`}
                      />
                    ))}
                  </div>

                  {/* Prev / next */}
                  <ArticleNav
                    articles={ARTICLES}
                    activeId={activeId}
                    onPick={setActiveId}
                  />
                </article>
              ) : (
                <div style={{ padding: 60, textAlign: 'center', color: 'var(--fg-muted)' }}>
                  Select an article from the left.
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </BentoCard>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .help-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

/* ─── Content block renderer ─────────────────────────────────────────── */
function BlockRenderer({
  block, copyCode, copied, blockId,
}: {
  block: ContentBlock; copyCode: (code: string, id: string) => void;
  copied: boolean; blockId: string;
}) {
  if (block.type === 'para') {
    return (
      <p style={{
        fontSize: 14, lineHeight: 1.7, color: 'var(--fg-secondary)', margin: 0,
      }}>
        {block.text}
      </p>
    );
  }

  if (block.type === 'heading') {
    return (
      <h3 style={{
        fontSize: 17, fontWeight: 700, color: 'var(--fg-primary)',
        margin: '10px 0 2px', letterSpacing: '-0.015em',
      }}>
        {block.text}
      </h3>
    );
  }

  if (block.type === 'code') {
    return (
      <div
        style={{
          position: 'relative',
          background: 'var(--surface-0)',
          border: '1px solid var(--line-2)',
          borderRadius: 'var(--r-md)',
          overflow: 'hidden',
        }}
      >
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '8px 12px', borderBottom: '1px solid var(--line-2)',
          background: 'var(--surface-1)',
        }}>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
            textTransform: 'uppercase', color: 'var(--fg-muted)',
            fontFamily: 'ui-monospace, monospace',
          }}>
            {block.lang ?? 'text'}
          </span>
          <button
            onClick={() => copyCode(block.code, blockId)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '3px 8px', borderRadius: 'var(--r-sm)',
              background: copied ? 'var(--bull-soft)' : 'var(--surface-4)',
              border: '1px solid var(--line-2)',
              color: copied ? 'var(--bull)' : 'var(--fg-muted)',
              fontSize: 10, fontWeight: 600, cursor: 'pointer',
              transition: 'all 120ms var(--ease-out)',
            }}
          >
            {copied ? <><Check size={10} /> Copied</> : <><Copy size={10} /> Copy</>}
          </button>
        </div>
        <pre style={{
          margin: 0, padding: '14px 16px',
          fontSize: 12.5, lineHeight: 1.65,
          fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
          color: 'var(--fg-primary)', background: 'transparent',
          overflowX: 'auto', whiteSpace: 'pre',
        }}
        className="lt-scroll"
        >
          <code>{block.code}</code>
        </pre>
      </div>
    );
  }

  if (block.type === 'list') {
    return (
      <ul style={{
        margin: 0, paddingLeft: 0, listStyle: 'none',
        display: 'flex', flexDirection: 'column', gap: 8,
      }}>
        {block.items.map((item, i) => (
          <li key={i} style={{
            display: 'flex', gap: 10, fontSize: 14, lineHeight: 1.65,
            color: 'var(--fg-secondary)',
          }}>
            <span aria-hidden style={{
              flexShrink: 0, width: 6, height: 6, borderRadius: '50%',
              background: 'var(--accent-2)', marginTop: 9,
            }} />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (block.type === 'kvs') {
    return (
      <dl style={{
        margin: 0,
        display: 'grid', gridTemplateColumns: 'max-content 1fr',
        gap: '10px 22px',
        padding: '12px 14px',
        background: 'var(--surface-3)',
        border: '1px solid var(--line-2)',
        borderRadius: 'var(--r-md)',
      }}>
        {block.items.map((kv, i) => (
          <div key={i} style={{ display: 'contents' }}>
            <dt style={{
              fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)',
              whiteSpace: 'nowrap',
            }}>
              {kv.k}
            </dt>
            <dd style={{
              fontSize: 13, color: 'var(--fg-secondary)', margin: 0, lineHeight: 1.55,
            }}>
              {kv.v}
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  if (block.type === 'callout') {
    const toneColor = block.tone === 'danger' ? 'var(--bear)'
      : block.tone === 'warn' ? 'var(--warn)'
      : 'var(--accent-2)';
    const toneSoft = block.tone === 'danger' ? 'var(--bear-soft)'
      : block.tone === 'warn' ? 'var(--warn-soft)'
      : 'color-mix(in srgb, var(--accent-2) 10%, transparent)';
    return (
      <div
        role="note"
        style={{
          display: 'flex', gap: 12,
          padding: '12px 14px', borderRadius: 'var(--r-md)',
          background: toneSoft,
          border: `1px solid color-mix(in srgb, ${toneColor} 28%, transparent)`,
        }}
      >
        <Info size={14} style={{ color: toneColor, marginTop: 3, flexShrink: 0 }} />
        <div>
          {block.title && (
            <p style={{ fontSize: 12, fontWeight: 700, color: toneColor, margin: '0 0 4px', letterSpacing: '0.02em' }}>
              {block.title}
            </p>
          )}
          <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--fg-secondary)', margin: 0 }}>
            {block.text}
          </p>
        </div>
      </div>
    );
  }

  return null;
}

/* ─── Prev / next ─────────────────────────────────────────────────── */
function ArticleNav({
  articles, activeId, onPick,
}: { articles: Article[]; activeId: string; onPick: (id: string) => void }) {
  const idx = articles.findIndex((a) => a.id === activeId);
  const prev = idx > 0 ? articles[idx - 1] : null;
  const next = idx < articles.length - 1 ? articles[idx + 1] : null;

  if (!prev && !next) return null;

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10,
      marginTop: 36, paddingTop: 20, borderTop: '1px solid var(--line-2)',
    }}>
      {prev ? (
        <button onClick={() => onPick(prev.id)} style={{ ...navBtn, textAlign: 'left' }}>
          <ChevronRight size={14} style={{ transform: 'rotate(180deg)', color: 'var(--fg-muted)' }} />
          <div>
            <p style={navBtnLabel}>Previous</p>
            <p style={navBtnTitle}>{prev.title}</p>
          </div>
        </button>
      ) : <span />}
      {next ? (
        <button onClick={() => onPick(next.id)} style={{ ...navBtn, textAlign: 'right', flexDirection: 'row-reverse' }}>
          <ChevronRight size={14} style={{ color: 'var(--fg-muted)' }} />
          <div>
            <p style={navBtnLabel}>Next</p>
            <p style={navBtnTitle}>{next.title}</p>
          </div>
        </button>
      ) : <span />}
    </div>
  );
}

/* ─── Styles ───────────────────────────────────────────────────────── */
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 11, fontWeight: 600, textDecoration: 'none',
};
const navBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10,
  padding: '12px 16px', borderRadius: 'var(--r-md)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', cursor: 'pointer',
  transition: 'background 160ms var(--ease-out), border-color 160ms var(--ease-out)',
};
const navBtnLabel: React.CSSProperties = {
  fontSize: 10, letterSpacing: '0.1em', fontWeight: 700,
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
};
const navBtnTitle: React.CSSProperties = {
  fontSize: 13, fontWeight: 600, color: 'var(--fg-primary)', margin: '3px 0 0',
};
