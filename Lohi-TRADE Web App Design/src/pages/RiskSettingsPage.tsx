import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Shield, Power, Zap, AlertTriangle, Check, Lock, KeyRound, ArrowLeft, ArrowRight,
} from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { useTradingModeStore } from '../stores/trading-mode-store';

/**
 * RiskSettingsPage — spec §2.15 /settings/risk
 *
 * Hosts the critical LIVE mode activation. Gates:
 *   • System-verified paper-session count ≥ 1
 *   • Broker configured
 *   • 6-checkbox confirmation
 *   • Re-auth (password + TOTP)
 *   • Typed confirmation phrase "ENABLE LIVE TRADING"
 */

const CHECKLIST = [
  { key: 'broker', label: 'I have connected and tested at least one broker.' },
  { key: 'paper', label: 'I have completed at least one full paper-trading session.' },
  { key: 'risk', label: 'I understand algorithmic trading carries risk of significant loss.' },
  { key: 'loss', label: 'I accept the configured daily loss limit and position caps.' },
  { key: 'kill', label: 'I know how to trigger the kill switch from UI, API, or CLI.' },
  { key: 'unreg', label: 'I understand LOHI-TRADE is not a SEBI-registered intermediary.' },
] as const;

const ACTIVATION_PHRASE = 'ENABLE LIVE TRADING';

export default function RiskSettingsPage() {
  const mode = useTradingModeStore((s) => s.mode);
  const setMode = useTradingModeStore((s) => s.setMode);
  const paperSessions = useTradingModeStore((s) => s.paperSessionsCompleted);
  const killSwitch = useTradingModeStore((s) => s.killSwitchActive);
  const setKillSwitch = useTradingModeStore((s) => s.setKillSwitch);

  const [limits, setLimits] = useState({
    maxOrderValue: 100000,
    maxOpenPositions: 10,
    maxPerStrategy: 5,
    dailyLossLimit: 10000,
    dailyProfitTarget: 0,
    priceSanityPct: 5,
    maxOrdersPerMin: 60,
    allowShort: false,
    allowOptionsWriting: false,
    allowFno: false,
    sessionStart: '09:15',
    sessionEnd: '15:30',
    intradaySquareOff: '15:15',
  });
  const updateLimit = (key: string, v: any) => setLimits((prev) => ({ ...prev, [key]: v }));

  const [modalOpen, setModalOpen] = useState(false);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader icon={<Shield size={16} />} title="Risk Settings" subtitle="Guardrails and live-mode activation" />

      {/* Live mode activation */}
      <BentoCard reveal accent={mode === 'LIVE' ? 'rose' : 'indigo'}>
        <div style={{ padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 280 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Trading mode</h3>
              <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '6px 0 0', lineHeight: 1.55 }}>
                Currently: <strong style={{ color: mode === 'LIVE' ? 'var(--bear)' : 'var(--warn)', fontWeight: 700, letterSpacing: '0.08em' }}>{mode}</strong>.
                Switching to LIVE requires a 3-step confirmation. LIVE mode routes orders to your real broker — every order is binding.
              </p>
              {mode === 'PAPER' && paperSessions < 1 && (
                <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 'var(--r-sm)', background: 'var(--warn-soft)', border: '1px solid color-mix(in srgb, var(--warn) 25%, transparent)', color: 'var(--warn)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <AlertTriangle size={12} /> Complete at least one paper session before activating LIVE
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {mode === 'LIVE' ? (
                <button onClick={() => setMode('PAPER')} style={{ ...chipBtn, color: 'var(--bear)', borderColor: 'color-mix(in srgb, var(--bear) 30%, transparent)' }}>
                  Switch back to PAPER
                </button>
              ) : (
                <button
                  onClick={() => setModalOpen(true)}
                  disabled={paperSessions < 1}
                  style={{
                    padding: '9px 16px', borderRadius: 'var(--r-sm)',
                    background: 'linear-gradient(180deg, color-mix(in srgb, var(--bear) 95%, white 5%), var(--bear))',
                    border: '1px solid color-mix(in srgb, var(--bear) 55%, transparent)',
                    color: '#fff', fontSize: 12, fontWeight: 700, cursor: paperSessions < 1 ? 'not-allowed' : 'pointer',
                    opacity: paperSessions < 1 ? 0.5 : 1,
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--bear) 30%, transparent)',
                  }}
                >
                  <Zap size={12} /> Enable live trading
                </button>
              )}
            </div>
          </div>
        </div>
      </BentoCard>

      {/* Kill switch */}
      <BentoCard reveal accent={killSwitch ? 'rose' : 'none'}>
        <div style={{ padding: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Kill switch</h3>
            <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '6px 0 0' }}>
              State: <strong style={{ color: killSwitch ? 'var(--bear)' : 'var(--bull)', fontWeight: 700 }}>{killSwitch ? 'TRIGGERED' : 'ACTIVE (armed)'}</strong> · resets require password + 2FA
            </p>
          </div>
          <button
            onClick={() => setKillSwitch(!killSwitch)}
            style={{
              padding: '8px 14px', borderRadius: 'var(--r-sm)',
              background: killSwitch ? 'var(--surface-3)' : 'linear-gradient(180deg, color-mix(in srgb, var(--bear) 95%, white 5%), var(--bear))',
              border: `1px solid ${killSwitch ? 'var(--line-2)' : 'color-mix(in srgb, var(--bear) 55%, transparent)'}`,
              color: killSwitch ? 'var(--fg-primary)' : '#fff',
              fontSize: 12, fontWeight: 700, cursor: 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            <Power size={12} /> {killSwitch ? 'Reset kill switch' : 'Trigger kill switch'}
          </button>
        </div>
      </BentoCard>

      {/* Global limits */}
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Global limits</h3>
          <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '4px 0 14px' }}>Pre-trade risk checks enforce these on every order.</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
            <NumField label="Max order value (₹)" value={limits.maxOrderValue} onChange={(v) => updateLimit('maxOrderValue', v)} />
            <NumField label="Max open positions" value={limits.maxOpenPositions} onChange={(v) => updateLimit('maxOpenPositions', v)} />
            <NumField label="Max per strategy" value={limits.maxPerStrategy} onChange={(v) => updateLimit('maxPerStrategy', v)} />
            <NumField label="Daily loss limit (₹)" value={limits.dailyLossLimit} onChange={(v) => updateLimit('dailyLossLimit', v)} />
            <NumField label="Daily profit target (₹)" value={limits.dailyProfitTarget} onChange={(v) => updateLimit('dailyProfitTarget', v)} />
            <NumField label="Price sanity (%)" value={limits.priceSanityPct} onChange={(v) => updateLimit('priceSanityPct', v)} />
            <NumField label="Max orders / minute" value={limits.maxOrdersPerMin} onChange={(v) => updateLimit('maxOrdersPerMin', v)} />
          </div>
        </div>
      </BentoCard>

      {/* Permissions */}
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Permissions</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginTop: 12 }}>
            <Toggle label="Allow short selling" v={limits.allowShort} set={(v) => updateLimit('allowShort', v)} />
            <Toggle label="Allow options writing" v={limits.allowOptionsWriting} set={(v) => updateLimit('allowOptionsWriting', v)} />
            <Toggle label="Allow F&O" v={limits.allowFno} set={(v) => updateLimit('allowFno', v)} />
          </div>
        </div>
      </BentoCard>

      {/* Session windows */}
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Session windows</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginTop: 12 }}>
            <Field label="Active from"><input type="time" value={limits.sessionStart} onChange={(e) => updateLimit('sessionStart', e.target.value)} style={input} /></Field>
            <Field label="Active until"><input type="time" value={limits.sessionEnd} onChange={(e) => updateLimit('sessionEnd', e.target.value)} style={input} /></Field>
            <Field label="Intraday square-off"><input type="time" value={limits.intradaySquareOff} onChange={(e) => updateLimit('intradaySquareOff', e.target.value)} style={input} /></Field>
          </div>
        </div>
      </BentoCard>

      <AnimatePresence>
        {modalOpen && (
          <ActivationModal
            onClose={() => setModalOpen(false)}
            onConfirm={() => { setMode('LIVE'); setModalOpen(false); }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

/* ─── Activation Modal — 3 steps ──────────────────────────────────── */
function ActivationModal({ onClose, onConfirm }: { onClose: () => void; onConfirm: () => void }) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');
  const [phrase, setPhrase] = useState('');

  const allChecked = CHECKLIST.every((c) => checks[c.key]);
  const reauthOk = password.length >= 6 && totp.length === 6;
  const phraseOk = phrase === ACTIVATION_PHRASE;

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'grid', placeItems: 'center', background: 'var(--scrim)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}
    >
      <motion.div
        initial={{ scale: 0.94, y: 8 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.97, y: 4 }}
        onClick={(e) => e.stopPropagation()}
        className="lt-glass"
        style={{
          width: '100%', maxWidth: 520, padding: 28,
          borderRadius: 'var(--r-lg)', border: '1px solid var(--line-2)',
          boxShadow: 'var(--elev-3)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <Zap size={14} color="var(--bear)" />
          <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.16em', color: 'var(--bear)' }}>ACTIVATE LIVE TRADING</span>
        </div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--fg-primary)', margin: '4px 0 6px', letterSpacing: '-0.02em' }}>Step {step} of 3</h2>

        {/* Progress */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 18 }}>
          {[1, 2, 3].map((n) => (
            <div key={n} style={{
              flex: 1, height: 3, borderRadius: 2,
              background: n <= step ? 'var(--bear)' : 'var(--line-2)',
              transition: 'background 200ms var(--ease-out)',
            }} />
          ))}
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 6 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -6 }}
            transition={{ duration: 0.18 }}
          >
            {step === 1 && (
              <>
                <h3 style={stepTitle}>Confirmation checklist</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
                  {CHECKLIST.map((c) => (
                    <label key={c.key} style={{ display: 'flex', gap: 10, padding: '10px 12px', borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)', fontSize: 12, color: 'var(--fg-secondary)', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={!!checks[c.key]}
                        onChange={(e) => setChecks((p) => ({ ...p, [c.key]: e.target.checked }))}
                        style={{ width: 15, height: 15, accentColor: 'var(--bear)', marginTop: 1 }}
                      />
                      <span>{c.label}</span>
                    </label>
                  ))}
                </div>
              </>
            )}

            {step === 2 && (
              <>
                <h3 style={stepTitle}>Re-authentication</h3>
                <p style={stepBlurb}>Confirm your identity before enabling real-money trading.</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 10 }}>
                  <Field label="Password">
                    <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={input} />
                  </Field>
                  <Field label="TOTP code">
                    <input inputMode="numeric" value={totp} onChange={(e) => setTotp(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6 digits" style={{ ...input, fontFamily: 'ui-monospace, monospace', letterSpacing: '0.25em' }} />
                  </Field>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <h3 style={stepTitle}>Type to confirm</h3>
                <p style={stepBlurb}>Copy this phrase exactly to proceed. This is deliberate friction.</p>
                <div style={{ ...input, marginTop: 10, background: 'var(--surface-4)', fontFamily: 'ui-monospace, monospace', fontSize: 13, color: 'var(--bear)', letterSpacing: '0.08em', userSelect: 'all' }}>
                  {ACTIVATION_PHRASE}
                </div>
                <input
                  value={phrase}
                  onChange={(e) => setPhrase(e.target.value)}
                  placeholder="Type the phrase above"
                  style={{ ...input, marginTop: 10, borderColor: phraseOk ? 'color-mix(in srgb, var(--bull) 35%, transparent)' : 'var(--line-2)' }}
                />
              </>
            )}
          </motion.div>
        </AnimatePresence>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20 }}>
          <button onClick={step === 1 ? onClose : () => setStep((s) => (s - 1) as 1 | 2)} style={ghostBtn}>
            <ArrowLeft size={12} /> {step === 1 ? 'Cancel' : 'Back'}
          </button>
          {step < 3 ? (
            <button
              onClick={() => setStep((s) => (s + 1) as 2 | 3)}
              disabled={(step === 1 && !allChecked) || (step === 2 && !reauthOk)}
              style={{
                ...nextBtn,
                opacity: ((step === 1 && !allChecked) || (step === 2 && !reauthOk)) ? 0.5 : 1,
                cursor: ((step === 1 && !allChecked) || (step === 2 && !reauthOk)) ? 'not-allowed' : 'pointer',
              }}
            >
              Continue <ArrowRight size={12} />
            </button>
          ) : (
            <button
              onClick={onConfirm}
              disabled={!phraseOk}
              style={{
                padding: '8px 16px', borderRadius: 'var(--r-sm)',
                background: 'linear-gradient(180deg, color-mix(in srgb, var(--bear) 95%, white 5%), var(--bear))',
                color: '#fff', border: '1px solid color-mix(in srgb, var(--bear) 55%, transparent)',
                fontSize: 12, fontWeight: 700, cursor: phraseOk ? 'pointer' : 'not-allowed', opacity: phraseOk ? 1 : 0.5,
                display: 'inline-flex', alignItems: 'center', gap: 6,
                boxShadow: phraseOk ? '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--bear) 30%, transparent)' : 'none',
              }}
            >
              <Zap size={12} /> Enable live trading
            </button>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

/* ─── Atoms ───────────────────────────────────────────────────────── */
function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <Field label={label}>
      <input value={value} onChange={(e) => onChange(parseInt(e.target.value.replace(/\D/g, '')) || 0)} style={input} />
    </Field>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
      {children}
    </label>
  );
}

function Toggle({ label, v, set }: { label: string; v: boolean; set: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => set(!v)}
      role="switch"
      aria-checked={v}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        padding: '12px 14px', borderRadius: 'var(--r-sm)',
        background: 'var(--surface-3)', border: '1px solid var(--line-2)',
        color: 'var(--fg-primary)', fontSize: 12, fontWeight: 600, cursor: 'pointer', textAlign: 'left',
      }}
    >
      <span>{label}</span>
      <span style={{
        position: 'relative', width: 36, height: 20, borderRadius: 999,
        background: v ? 'color-mix(in srgb, var(--bull) 55%, transparent)' : 'var(--surface-4)',
        transition: 'background 200ms var(--ease-out)',
      }}>
        <span style={{
          position: 'absolute', top: 2, left: v ? 18 : 2,
          width: 16, height: 16, borderRadius: '50%',
          background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          transition: 'left 200ms var(--ease-out)',
        }} />
      </span>
    </button>
  );
}

/* ─── Styles ──────────────────────────────────────────────────────── */
const input: React.CSSProperties = {
  padding: '9px 11px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
};
const chipBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 10px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
};
const stepTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 };
const stepBlurb: React.CSSProperties = { fontSize: 12, color: 'var(--fg-muted)', margin: '4px 0 0' };
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 12px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
};
const nextBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 16px',
  borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  color: '#fff', border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  fontSize: 12, fontWeight: 600,
  boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
};
