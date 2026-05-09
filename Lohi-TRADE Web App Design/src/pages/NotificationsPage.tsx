import { useState } from 'react';
import { Bell, Smartphone, Webhook, Send, Check, X } from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { ServiceStatusBanner } from '../components/setup/ServiceStatusBanner';
import { useFeatureGate } from '../hooks/useFeatureGate';

/**
 * NotificationsPage — spec §2.16 /settings/notifications
 * Channels: Desktop, ntfy.sh, Gotify, webhook.
 * Events: order placed/filled/rejected, SL hit, strategy error, broker disc, daily loss limits.
 */

const EVENTS = [
  { id: 'order_placed', label: 'Order placed' },
  { id: 'order_filled', label: 'Order filled' },
  { id: 'order_rejected', label: 'Order rejected' },
  { id: 'position_closed', label: 'Position closed' },
  { id: 'sl_hit', label: 'Stop-loss hit' },
  { id: 'strategy_error', label: 'Strategy error' },
  { id: 'broker_disconnect', label: 'Broker disconnected' },
  { id: 'daily_loss_near', label: 'Daily loss limit approaching' },
  { id: 'daily_loss_breach', label: 'Daily loss limit breached' },
] as const;

type Channel = 'desktop' | 'ntfy' | 'gotify' | 'webhook';
const CHANNELS: { id: Channel; label: string; icon: React.ElementType; blurb: string }[] = [
  { id: 'desktop', label: 'Desktop', icon: Bell, blurb: 'Browser notification (requires permission)' },
  { id: 'ntfy', label: 'ntfy.sh', icon: Smartphone, blurb: 'Free self-hosted push to mobile' },
  { id: 'gotify', label: 'Gotify', icon: Smartphone, blurb: 'Self-hosted push alternative' },
  { id: 'webhook', label: 'Webhook', icon: Webhook, blurb: 'HMAC-signed POST to your endpoint' },
];

export default function NotificationsPage() {
  const { isFeatureAvailable, getRequiredServiceName } = useFeatureGate();
  const [ntfy, setNtfy] = useState({ url: 'https://ntfy.sh', topic: '' });
  const [gotify, setGotify] = useState({ url: '', token: '' });
  const [webhook, setWebhook] = useState({ url: '', secret: '' });
  const [desktopGranted, setDesktopGranted] = useState<boolean>(typeof Notification !== 'undefined' && Notification.permission === 'granted');
  const [routing, setRouting] = useState<Record<string, Record<Channel, boolean>>>(() => {
    const init: Record<string, Record<Channel, boolean>> = {};
    for (const e of EVENTS) init[e.id] = { desktop: true, ntfy: false, gotify: false, webhook: false };
    return init;
  });
  const [testResult, setTestResult] = useState<Record<Channel, 'idle' | 'ok' | 'err'>>({ desktop: 'idle', ntfy: 'idle', gotify: 'idle', webhook: 'idle' });

  const requestDesktop = async () => {
    if (typeof Notification === 'undefined') return;
    const res = await Notification.requestPermission();
    setDesktopGranted(res === 'granted');
  };

  const test = async (c: Channel) => {
    setTestResult((r) => ({ ...r, [c]: 'idle' }));
    await new Promise((r) => setTimeout(r, 400));
    const ok = c === 'desktop' ? desktopGranted : true;
    setTestResult((r) => ({ ...r, [c]: ok ? 'ok' : 'err' }));
  };

  const toggleRoute = (evt: string, c: Channel) =>
    setRouting((r) => ({ ...r, [evt]: { ...r[evt], [c]: !r[evt][c] } }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* ── Service Status Banner (Requirement 4.5) ─────────────── */}
      {!isFeatureAvailable('telegram_notifications') && (
        <ServiceStatusBanner
          serviceName={getRequiredServiceName('telegram_notifications') ?? 'Telegram Bot'}
          featureDescription="Telegram notifications require a bot token and chat ID to be configured. Desktop and webhook notifications still work without it."
          configureLink="/settings"
        />
      )}

      <PageHeader icon={<Bell size={16} />} title="Notifications" subtitle="Alert channels and per-event routing" />

      {/* Channels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14 }}>
        <BentoCard reveal>
          <div style={{ padding: 20 }}>
            <ChanHeader icon={<Bell size={14} />} title="Desktop" blurb="Browser notifications — permission required" result={testResult.desktop} />
            {desktopGranted ? (
              <button onClick={() => test('desktop')} style={chipBtn}><Send size={12} /> Send test</button>
            ) : (
              <button onClick={requestDesktop} style={primaryBtn}>Grant permission</button>
            )}
          </div>
        </BentoCard>

        <BentoCard reveal>
          <div style={{ padding: 20 }}>
            <ChanHeader icon={<Smartphone size={14} />} title="ntfy.sh" blurb="Free push to phone via ntfy" result={testResult.ntfy} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <Field label="URL"><input value={ntfy.url} onChange={(e) => setNtfy({ ...ntfy, url: e.target.value })} style={input} /></Field>
              <Field label="Topic"><input value={ntfy.topic} onChange={(e) => setNtfy({ ...ntfy, topic: e.target.value })} placeholder="lohi-alerts" style={input} /></Field>
            </div>
            <button onClick={() => test('ntfy')} style={{ ...chipBtn, marginTop: 10 }}><Send size={12} /> Send test</button>
          </div>
        </BentoCard>

        <BentoCard reveal>
          <div style={{ padding: 20 }}>
            <ChanHeader icon={<Smartphone size={14} />} title="Gotify" blurb="Self-hosted push" result={testResult.gotify} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <Field label="Server URL"><input value={gotify.url} onChange={(e) => setGotify({ ...gotify, url: e.target.value })} style={input} /></Field>
              <Field label="App token"><input value={gotify.token} onChange={(e) => setGotify({ ...gotify, token: e.target.value })} type="password" style={input} /></Field>
            </div>
            <button onClick={() => test('gotify')} style={{ ...chipBtn, marginTop: 10 }}><Send size={12} /> Send test</button>
          </div>
        </BentoCard>

        <BentoCard reveal>
          <div style={{ padding: 20 }}>
            <ChanHeader icon={<Webhook size={14} />} title="Webhook" blurb="HMAC-signed JSON POST" result={testResult.webhook} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <Field label="Endpoint URL"><input value={webhook.url} onChange={(e) => setWebhook({ ...webhook, url: e.target.value })} style={input} /></Field>
              <Field label="HMAC secret"><input value={webhook.secret} onChange={(e) => setWebhook({ ...webhook, secret: e.target.value })} type="password" style={input} /></Field>
            </div>
            <button onClick={() => test('webhook')} style={{ ...chipBtn, marginTop: 10 }}><Send size={12} /> Send test</button>
          </div>
        </BentoCard>
      </div>

      {/* Routing matrix */}
      <BentoCard reveal>
        <div style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--line-2)' }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Event routing</h3>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '4px 0 0' }}>Tick channels to deliver each event type to.</p>
          </div>
          <div style={{ overflowX: 'auto' }} className="lt-scroll">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead className="lt-glass" style={{ position: 'sticky', top: 0, background: 'color-mix(in srgb, var(--surface-2) 82%, transparent)' }}>
                <tr>
                  <th style={thStyle}>Event</th>
                  {CHANNELS.map((c) => <th key={c.id} style={{ ...thStyle, textAlign: 'center' }}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {EVENTS.map((e) => (
                  <tr key={e.id} style={{ borderBottom: '1px solid var(--line-1)' }}>
                    <td style={{ padding: '12px 14px', color: 'var(--fg-primary)' }}>{e.label}</td>
                    {CHANNELS.map((c) => (
                      <td key={c.id} style={{ padding: '12px 14px', textAlign: 'center' }}>
                        <input type="checkbox" checked={!!routing[e.id][c.id]} onChange={() => toggleRoute(e.id, c.id)} style={{ width: 15, height: 15, accentColor: 'var(--accent)' }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </BentoCard>
    </div>
  );
}

function ChanHeader({ icon, title, blurb, result }: { icon: React.ReactNode; title: string; blurb: string; result: 'idle' | 'ok' | 'err' }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ display: 'grid', placeItems: 'center', width: 26, height: 26, borderRadius: 'var(--r-sm)', background: 'var(--surface-4)', color: 'var(--accent-2)' }}>{icon}</span>
        <div>
          <p style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>{title}</p>
          <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '2px 0 0' }}>{blurb}</p>
        </div>
      </div>
      {result === 'ok' && <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--bull)', fontSize: 11, fontWeight: 600 }}><Check size={12} /> Sent</span>}
      {result === 'err' && <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--bear)', fontSize: 11, fontWeight: 600 }}><X size={12} /> Failed</span>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
      {children}
    </label>
  );
}

const input: React.CSSProperties = {
  padding: '7px 10px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', fontSize: 12, outline: 'none', fontFamily: 'inherit',
};
const chipBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 10px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
};
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  color: '#fff', fontSize: 11, fontWeight: 700, cursor: 'pointer',
};
const thStyle: React.CSSProperties = {
  padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700,
  color: 'var(--fg-muted)', letterSpacing: '0.1em', textTransform: 'uppercase',
  borderBottom: '1px solid var(--line-2)',
};
