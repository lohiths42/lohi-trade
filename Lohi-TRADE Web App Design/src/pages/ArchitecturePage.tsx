/**
 * `/architecture` — interactive DAG walkthrough of the Trade agentic
 * architecture.
 *
 * Graph shape:
 *
 *   Ingestion (ticks)  ─┐
 *   Ingestion (news)   ─┴─► Event Bus ─┬─► Soldier · technicals ─┐
 *                                      ├─► Commander · sentiment ┤
 *                                      └─► Research signal bridge┤  (optional
 *                                                                 │   veto/boost
 *                                                                 │   from Research)
 *                                                                 ▼
 *                     Risk Management System ──► Position Sizer ──► OMS ──► Broker
 *                            ▲    ▲                                    │
 *                            │    │                                    ▼
 *                            │    └─ KillSwitch ◄──── PnL / Volatility ────── State
 *                            └──── Research Signal filter (sideband feedback)
 *
 * Parallel branches:
 *   • Soldier and Commander both consume the event bus independently.
 *     Soldier emits Signals; Commander emits Bias. They never block each
 *     other; the RMS fans them in.
 *   • OMS fill events stream back into State, which publishes PnL ticks
 *     that feed the KillSwitch — a true feedback cycle on the PnL side.
 *   • The Research surface publishes ResearchSignal on its own Redis
 *     stream; the strategy adapter reads it as a sideband into RMS.
 *
 * Sideband channels the canvas also visualises:
 *   • Event Bus → everywhere (stream edges, muted dashed)
 *   • Fill → State → PnL → KillSwitch (feedback, coral dashed)
 *   • Research → RMS (memory/cache tone cyan — cross-surface channel)
 *   • Telemetry writes into State (audit log)
 */

import LohiAvatar from '../components/onboarding/LohiAvatar';
import WorkflowSimulator, {
  type WorkflowStep,
} from '../components/shared/WorkflowSimulator';

// Fixed indices so cross-references stay stable as the array is edited.
const IDX = {
  ING_TICKS: 0,
  ING_NEWS: 1,
  BUS: 2,
  SOLDIER: 3,
  COMMANDER: 4,
  RESEARCH_BRIDGE: 5,
  RMS: 6,
  SIZER: 7,
  OMS: 8,
  BROKER: 9,
  STATE: 10,
  KILL: 11,
  UI: 12,
};

const STEPS: WorkflowStep[] = [
  // 0 — Ingestion · ticks (runs in parallel with news)
  {
    role: 'Ingestion · ticks',
    responsibility:
      'WebSocket clients to Shoonya / Angel One. Streams raw per-symbol ticks; hash-dedupes and publishes to the event bus.',
    incoming: null,
    outgoing: {
      name: 'TickBatch',
      shape: '{ symbol, ts, ltp, volume }',
    },
    upstreams: [],
    parallelGroup: 'Ingestion',
    sidebands: [
      { to: IDX.BUS, kind: 'stream', label: 'ticks' },
    ],
    details: (
      <p>
        Non-blocking: the ingestion layer never waits on downstream consumers. If
        Soldier or Commander falls behind, Redis Streams absorb the backlog.
      </p>
    ),
  },

  // 1 — Ingestion · news
  {
    role: 'Ingestion · news',
    responsibility:
      'RSS / NSE announcement feeds. Publishes raw news onto news_raw, deduplicated by content hash.',
    incoming: null,
    outgoing: {
      name: 'NewsBatch',
      shape: '{ source, url, title, body }',
    },
    upstreams: [],
    parallelGroup: 'Ingestion',
    sidebands: [
      { to: IDX.BUS, kind: 'stream', label: 'news_raw' },
    ],
    details: (
      <p>
        Ticks and news ingestion are peers — they run in separate tasks and never
        block each other. Together they are the only write-path into the event bus.
      </p>
    ),
  },

  // 2 — Event Bus
  {
    role: 'Event Bus · Redis Streams',
    responsibility:
      'The system\'s backbone: ticks · news_raw · news_clean · sentiment · bias · indicators · signals · orders · fills. Consumer groups allow Soldier and Commander to scale horizontally.',
    incoming: {
      name: 'TickBatch | NewsBatch',
      shape: '{ source, payload }',
    },
    outgoing: {
      name: 'Stream entries',
      shape: 'XADD · XREADGROUP',
    },
    upstreams: [IDX.ING_TICKS, IDX.ING_NEWS],
    sidebands: [
      { to: IDX.SOLDIER, kind: 'stream', label: 'ticks' },
      { to: IDX.COMMANDER, kind: 'stream', label: 'news_raw' },
      { to: IDX.STATE, kind: 'telemetry', label: 'stream stats' },
    ],
    details: (
      <p>
        Stream lengths are capped with <code>XTRIM</code>. Every downstream
        consumer (Soldier, Commander, Research News_Sentiment, Research
        Technicals) reads off the same bus — no point-to-point coupling.
      </p>
    ),
  },

  // 3 — Soldier (parallel with Commander)
  {
    role: 'Soldier · technicals',
    responsibility:
      'Aggregates ticks into candles, runs the indicator engine (RSI / MACD / Bollinger / ATR), executes the strategy set. Emits a Signal when strategy confidence crosses the threshold.',
    incoming: {
      name: 'Candle[]',
      shape: '{ symbol, o, h, l, c, v, ts }',
    },
    outgoing: {
      name: 'Signal',
      shape: "{ strategy, symbol, side, confidence, reason }",
    },
    upstreams: [IDX.BUS],
    parallelGroup: 'Parallel analysis',
    sidebands: [
      { to: IDX.BUS, kind: 'stream', label: 'indicators stream' },
    ],
    details: (
      <p>
        Strategies are pure functions of candles + config — no shared state, no
        order placement. Backtests and paper-trading are the *same code path* as
        live, just with a different tick source.
      </p>
    ),
  },

  // 4 — Commander (parallel with Soldier)
  {
    role: 'Commander · sentiment',
    responsibility:
      'Entity-resolves news via spaCy NER, scores sentiment with FinBERT, time-decays per-symbol Bias. Runs concurrently with Soldier; they both feed the RMS.',
    incoming: {
      name: 'NewsItem',
      shape: '{ symbol?, title, body }',
    },
    outgoing: {
      name: 'Bias',
      shape: '{ symbol, bias: -1..1, half_life_h }',
    },
    upstreams: [IDX.BUS],
    parallelGroup: 'Parallel analysis',
    sidebands: [
      { to: IDX.BUS, kind: 'stream', label: 'bias stream' },
    ],
    details: (
      <p>
        Commander never places an order. It only publishes a rolling bias, which
        the RMS can optionally weight. The same stream feeds the Research News
        agent — one sentiment pipeline, two consumers.
      </p>
    ),
  },

  // 5 — Research signal bridge (cross-surface)
  {
    role: 'Research signal bridge',
    responsibility:
      'Subscribes to the research_signal Redis stream published by Lohi Research. Adapts each ResearchSignal into a boost/veto input for the RMS filter chain.',
    incoming: {
      name: 'ResearchSignal',
      shape: '{ symbol, direction, conviction }',
    },
    outgoing: {
      name: 'FilterHint',
      shape: '{ symbol, boost?, veto_reason? }',
    },
    upstreams: [IDX.BUS],
    parallelGroup: 'Parallel analysis',
    sidebands: [
      { to: IDX.RMS, kind: 'memory', label: 'cross-surface hint' },
    ],
    details: (
      <p>
        Opt-in per strategy. When the research-derived conviction for a symbol is
        ≥ the strategy's configured floor <em>and</em> the direction matches, the
        bridge boosts the trade signal's weight; a conflicting research view
        vetoes it. The bridge only publishes hints — the RMS still makes the
        final call.
      </p>
    ),
  },

  // 6 — RMS (fans in Signal + Bias + Research hint)
  {
    role: 'Risk Management System',
    responsibility:
      'Nine deterministic pre-order checks: max open, max orders/day, per-trade risk %, per-position size %, trading-hours gate, volatility guard, kill-switch, cooldown-after-loss, position-direction conflict. A single failure rejects.',
    deterministic: true,
    incoming: {
      name: 'Signal + Bias + FilterHint?',
      shape: '{ signal, bias?, research? }',
    },
    outgoing: {
      name: 'ValidatedOrder | RejectedOrder',
      shape: '{ side, qty, entry, stop, target } | { rule_id, reason }',
    },
    upstreams: [IDX.SOLDIER, IDX.COMMANDER, IDX.RESEARCH_BRIDGE],
    sidebands: [
      { to: IDX.STATE, kind: 'telemetry', label: 'rms_decisions' },
    ],
    details: (
      <p>
        Every rejection is logged with the rule_id that fired. The volatility
        guard checks Nifty rolling drop within its configured window — when
        breached, every new entry is blocked but existing stops/targets still
        execute, so positions fail closed, not cascaded.
      </p>
    ),
  },

  // 7 — Position Sizer
  {
    role: 'Position Sizer',
    responsibility:
      'ATR-based sizing. Turns a validated signal into (qty, stop, target) such that stop-loss equals exactly the configured per-trade risk budget. Pure function of config + order.',
    deterministic: true,
    incoming: {
      name: 'ValidatedOrder',
      shape: '{ symbol, side, entry, stop }',
    },
    outgoing: {
      name: 'SizedOrder',
      shape: '{ symbol, side, qty, entry, stop, target }',
    },
    upstreams: [IDX.RMS],
    details: (
      <p>
        <code>qty = floor((capital × risk%) ÷ |entry − stop|)</code>. If the
        resulting position exceeds max_position_size_pct, it is clamped. Both
        paths are pure functions — backtest and live match bit-for-bit.
      </p>
    ),
  },

  // 8 — OMS
  {
    role: 'Order Management System',
    responsibility:
      'Routes orders to the primary broker; fails over to the backup on error. Tracks bracket-order state, stop/target modifications. Every state change publishes to the bus.',
    incoming: {
      name: 'SizedOrder',
      shape: '{ symbol, side, qty, entry, stop, target }',
    },
    outgoing: {
      name: 'OrderState',
      shape: "{ order_id, state }",
    },
    upstreams: [IDX.SIZER],
    sidebands: [
      { to: IDX.BUS, kind: 'stream', label: 'orders / fills stream' },
      { to: IDX.STATE, kind: 'feedback', label: 'reconcile' },
    ],
    details: (
      <p>
        Treats the broker as an unreliable counterparty: every API call has a
        retry policy, every fill is reconciled against the local book, and any
        disagreement fires a reconcile alert. The coral feedback edge you see
        here is the reconcile path: State disagrees → OMS replays.
      </p>
    ),
  },

  // 9 — Broker (terminal boundary)
  {
    role: 'Broker',
    responsibility:
      'Exchange connection. The only node outside the system\'s trust boundary — treated as untrusted by the OMS. Fills flow back through the bus into State.',
    incoming: {
      name: 'OrderPayload',
      shape: 'per-broker JSON',
    },
    outgoing: {
      name: 'Fill',
      shape: '{ order_id, qty, price, ts }',
    },
    upstreams: [IDX.OMS],
    sidebands: [
      { to: IDX.BUS, kind: 'stream', label: 'fills' },
    ],
    details: (
      <p>
        Every fill is re-entered into the bus as a first-class event so State can
        rebuild deterministically from the stream alone. Paper trading short-
        circuits this node with a deterministic simulator.
      </p>
    ),
  },

  // 10 — State
  {
    role: 'State · SQLite · DuckDB',
    responsibility:
      'SQLite for transactional state (orders, fills, positions, audit), DuckDB for historical tick and candle archives. Every transition is idempotent; replay after crash converges.',
    incoming: {
      name: 'Fill | OrderState | Decision',
      shape: 'transactional events',
    },
    outgoing: {
      name: 'PnLTick | View',
      shape: '{ symbol, pnl, view_ts }',
    },
    upstreams: [IDX.BROKER, IDX.OMS, IDX.RMS],
    sidebands: [
      { to: IDX.KILL, kind: 'feedback', label: 'PnL tick' },
      { to: IDX.UI, kind: 'stream', label: 'view refresh' },
    ],
    details: (
      <p>
        Materialised views feed the dashboard so the UI is always within a tick
        of ground truth. The PnL tick also flows into the KillSwitch — the
        system's own daily-loss circuit breaker.
      </p>
    ),
  },

  // 11 — KillSwitch (feeds back into RMS)
  {
    role: 'Kill Switch · Volatility Guard',
    responsibility:
      'Daily-PnL circuit breaker + Nifty volatility guard + operator override. Trips the RMS into reject-all on breach. Re-arming requires explicit operator acknowledgement.',
    deterministic: true,
    incoming: {
      name: 'PnLTick | MarketTick | OperatorEvent',
      shape: '{ kind, payload }',
    },
    outgoing: {
      name: 'KillSwitchState',
      shape: '{ active, reason }',
    },
    upstreams: [IDX.STATE],
    sidebands: [
      { to: IDX.RMS, kind: 'feedback', label: 'halt / resume' },
      { to: IDX.UI, kind: 'stream', label: 'notification' },
    ],
    details: (
      <p>
        This is the tightest feedback loop in the system: a fill → State → PnL
        → KillSwitch → RMS cycle completes in under 200 ms. Once armed, the
        switch never auto-resumes — an operator has to clear it.
      </p>
    ),
  },

  // 12 — UI
  {
    role: 'UI · Notifications · Telegram',
    responsibility:
      'Dashboard (Socket.IO), Command Palette, Telegram bot. All consume the same publish stream so every signal / fill / kill-switch event shows up in real time.',
    incoming: {
      name: 'State + events',
      shape: 'aggregated',
    },
    outgoing: null,
    upstreams: [IDX.STATE, IDX.KILL],
    details: (
      <p>
        The web UI and the Telegram bot share the same event stream with
        different adapters, so a user alerted on Telegram sees the same fill
        in the dashboard at the same moment.
      </p>
    ),
  },
];

export default function ArchitecturePage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <header
        style={{
          paddingBottom: 20,
          borderBottom: '1px solid var(--line-2)',
          display: 'flex',
          gap: 20,
          alignItems: 'flex-start',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <p
            style={{
              margin: 0,
              fontSize: 10,
              fontWeight: 800,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--accent-2)',
            }}
          >
            How it works
          </p>
          <h1
            style={{
              margin: '8px 0 10px',
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: '-0.02em',
              color: 'var(--fg-primary)',
            }}
          >
            Trade architecture
          </h1>
          <p
            style={{
              margin: 0,
              fontSize: 14,
              lineHeight: 1.55,
              color: 'var(--fg-secondary)',
              maxWidth: 760,
            }}
          >
            A deterministic trading DAG on top of a Redis stream backbone.
            Soldier and Commander run in parallel on the same event bus.
            Research signals drop in as a sideband. Fills → State → PnL →
            KillSwitch closes a tight feedback loop on risk. Walk through the
            graph to see every edge's data shape and the cubes that visualise
            what's moving where.
          </p>
        </div>
        <div
          aria-hidden
          style={{
            flexShrink: 0,
            width: 96,
            height: 96 * 1.35,
            marginTop: -8,
          }}
        >
          <LohiAvatar size="md" mood="focused" action="point" actionKey={1} />
        </div>
      </header>

      <WorkflowSimulator steps={STEPS} />

      <footer
        style={{
          paddingTop: 12,
          borderTop: '1px solid var(--line-2)',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 18,
          fontSize: 12,
          color: 'var(--fg-muted)',
        }}
      >
        <div>
          <p
            style={{
              margin: '0 0 4px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-primary)',
            }}
          >
            Parallelism
          </p>
          <p style={{ margin: 0, lineHeight: 1.55 }}>
            Soldier, Commander, and the Research bridge all consume the same
            event bus in parallel. The RMS fans them in; no consumer blocks
            another.
          </p>
        </div>
        <div>
          <p
            style={{
              margin: '0 0 4px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-primary)',
            }}
          >
            Feedback loops
          </p>
          <p style={{ margin: 0, lineHeight: 1.55 }}>
            Two real cycles: Fill → State → OMS reconcile, and PnL → KillSwitch
            → RMS halt. Everything else is forward-only.
          </p>
        </div>
        <div>
          <p
            style={{
              margin: '0 0 4px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-primary)',
            }}
          >
            Cross-surface bridge
          </p>
          <p style={{ margin: 0, lineHeight: 1.55 }}>
            Commander publishes sentiment / bias streams that Research's News
            agent reuses. In return, Research publishes ResearchSignal back
            into the event bus for the RMS filter chain.
          </p>
        </div>
      </footer>
    </div>
  );
}
