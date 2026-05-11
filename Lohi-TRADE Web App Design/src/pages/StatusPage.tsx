import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import {
  Activity, Cpu, Database, Server, Shield, Wifi, Play, AlertTriangle,
} from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import ChartSwitcher from '../components/shared/ChartSwitcher';

/**
 * StatusPage — spec §2.18 /status
 * Process health, DB growth, broker heartbeat, error feed, diagnostics CTA.
 */

type ServiceName = 'web' | 'api' | 'engine' | 'worker' | 'db' | 'caddy';
interface ServiceHealth {
  name: ServiceName;
  status: 'ok' | 'warn' | 'err';
  uptimeHrs: number;
  memMb: number;
  cpuPct: number;
  lastRestart: string;
}

const SERVICE_ICONS: Record<ServiceName, React.ElementType> = {
  web: Server, api: Cpu, engine: Activity, worker: Shield, db: Database, caddy: Wifi,
};

export default function StatusPage() {
  const [services, setServices] = useState<ServiceHealth[]>([
    { name: 'web', status: 'ok', uptimeHrs: 142.6, memMb: 180, cpuPct: 2.1, lastRestart: '6d ago' },
    { name: 'api', status: 'ok', uptimeHrs: 142.6, memMb: 320, cpuPct: 4.8, lastRestart: '6d ago' },
    { name: 'engine', status: 'ok', uptimeHrs: 142.4, memMb: 610, cpuPct: 12.3, lastRestart: '6d ago' },
    { name: 'worker', status: 'ok', uptimeHrs: 142.6, memMb: 140, cpuPct: 1.4, lastRestart: '6d ago' },
    { name: 'db', status: 'warn', uptimeHrs: 142.6, memMb: 220, cpuPct: 3.9, lastRestart: '6d ago' },
    { name: 'caddy', status: 'ok', uptimeHrs: 142.6, memMb: 40, cpuPct: 0.3, lastRestart: '6d ago' },
  ]);

  const [dbSize] = useState(
    Array.from({ length: 30 }, (_, i) => ({ x: `D-${30 - i}`, y: 82 + i * 0.9 + Math.random() * 3 })),
  );

  useEffect(() => {
    const id = setInterval(() => {
      setServices((svc) => svc.map((s) => ({ ...s, cpuPct: +(s.cpuPct + (Math.random() - 0.5) * 0.8).toFixed(2), memMb: Math.max(20, s.memMb + (Math.random() - 0.5) * 6) })));
    }, 1500);
    return () => clearInterval(id);
  }, []);

  const brokers = [
    { name: 'Zerodha', lastOk: '3s ago', uptime24h: 99.94, latency: 48 },
    { name: 'Dhan', lastOk: '6s ago', uptime24h: 99.80, latency: 62 },
    { name: 'Upstox', lastOk: '4m ago', uptime24h: 96.50, latency: 120 },
  ];

  const errors = [
    { when: '12:14:02', service: 'engine', msg: 'WebSocket reconnect after heartbeat gap 9s' },
    { when: '11:58:10', service: 'worker', msg: 'Order reconciliation drift resolved for ID a2b...' },
    { when: '09:42:55', service: 'api', msg: 'Broker Upstox 401 → refreshed token' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<Activity size={16} />}
        title="System Status"
        subtitle="Process health, DB growth, broker heartbeats, recent errors"
        actions={
          <button style={primaryBtn}><Play size={12} /> Run diagnostics</button>
        }
      />

      {/* Service cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
        {services.map((s, i) => {
          const Icon = SERVICE_ICONS[s.name];
          const color = s.status === 'ok' ? 'var(--bull)' : s.status === 'warn' ? 'var(--warn)' : 'var(--bear)';
          return (
            <BentoCard key={s.name} accent={s.status === 'ok' ? 'none' : s.status === 'warn' ? 'none' : 'rose'}>
              <motion.div
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.24, delay: i * 0.03 }}
                style={{ padding: 18, minHeight: 128 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ display: 'grid', placeItems: 'center', width: 28, height: 28, borderRadius: 'var(--r-sm)', background: `color-mix(in srgb, ${color} 14%, transparent)`, color }}>
                      <Icon size={14} />
                    </span>
                    <strong style={{ fontSize: 13, color: 'var(--fg-primary)', fontWeight: 700, textTransform: 'capitalize' }}>{s.name}</strong>
                  </span>
                  <span style={{
                    fontSize: 9, fontWeight: 800, letterSpacing: '0.1em', padding: '3px 7px',
                    borderRadius: 6, textTransform: 'uppercase',
                    background: `color-mix(in srgb, ${color} 14%, transparent)`, color,
                  }}>{s.status}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 14 }}>
                  <StatCol label="Uptime" value={s.uptimeHrs} format={(v) => `${v.toFixed(1)}h`} />
                  <StatCol label="Memory" value={s.memMb} format={(v) => `${Math.round(v)} MB`} />
                  <StatCol label="CPU" value={s.cpuPct} format={(v) => `${v.toFixed(1)}%`} />
                </div>
              </motion.div>
            </BentoCard>
          );
        })}
      </div>

      {/* DB + broker + errors */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 16 }}>
        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={sideTitle}>Database size <span style={{ fontWeight: 500, color: 'var(--fg-muted)', marginLeft: 8 }}>last 30 days</span></h3>
            <ChartSwitcher
              id="status-db-size"
              height={200}
              defaultKind="area"
              allowedKinds={['area', 'line', 'bar']}
              seriesLabel="MB"
              color="var(--accent-2)"
              valueFormat={(v) => `${Math.round(v)} MB`}
              linearData={dbSize}
            />
          </div>
        </BentoCard>
        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={sideTitle}>Broker heartbeat</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
              {brokers.map((b) => (
                <div key={b.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)' }}>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>{b.name}</p>
                    <p style={{ fontSize: 10, color: 'var(--fg-muted)', margin: '2px 0 0' }}>Last OK {b.lastOk} · {b.latency}ms</p>
                  </div>
                  <span className="lt-tabular" style={{ fontSize: 12, fontWeight: 700, color: b.uptime24h >= 99 ? 'var(--bull)' : 'var(--warn)' }}>{b.uptime24h.toFixed(2)}%</span>
                </div>
              ))}
            </div>
          </div>
        </BentoCard>
      </div>

      <BentoCard reveal>
        <div style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--line-2)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={14} color="var(--warn)" />
            <h3 style={sideTitle}>Recent errors</h3>
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
            {errors.map((e, i) => (
              <li key={i} style={{ padding: '12px 24px', borderBottom: i < errors.length - 1 ? '1px solid var(--line-1)' : 'none', display: 'flex', gap: 12, alignItems: 'center', fontSize: 12 }}>
                <span style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--fg-muted)', fontSize: 11, minWidth: 72 }}>{e.when}</span>
                <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'var(--surface-3)', border: '1px solid var(--line-2)', color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{e.service}</span>
                <span style={{ color: 'var(--fg-secondary)' }}>{e.msg}</span>
              </li>
            ))}
          </ul>
        </div>
      </BentoCard>
    </div>
  );
}

function StatCol({ label, value, format }: { label: string; value: number; format: (v: number) => string }) {
  return (
    <div>
      <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, margin: 0 }}>{label}</p>
      <p className="lt-tabular" style={{ fontSize: 14, color: 'var(--fg-primary)', fontWeight: 600, margin: '3px 0 0' }}>
        <AnimatedNumber value={value} format={format} flash={false} />
      </p>
    </div>
  );
}

const sideTitle: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, letterSpacing: '0.08em',
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
  display: 'inline-flex', alignItems: 'center',
};
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  color: '#fff', fontSize: 11, fontWeight: 700, cursor: 'pointer',
};
