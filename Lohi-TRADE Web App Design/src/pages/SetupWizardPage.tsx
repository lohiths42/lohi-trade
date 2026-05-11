import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import {
  Check, ShieldCheck, KeyRound, Cog, Sparkles, Copy, AlertTriangle, ArrowRight, ArrowLeft,
  Zap, Eye, EyeOff, ExternalLink, SkipForward, CheckCircle2, XCircle, Loader2, Info, Globe,
} from 'lucide-react';
import { BentoCard } from '../components/shared/BentoCard';
import { useSetupStore } from '../stores/setup-store';
import { CREDENTIAL_GROUPS } from '../lib/setup-types';
import { CountrySelectionStep } from '../components/setup/CountrySelectionStep';
import type { MarketSelectionResult } from '../components/setup/CountrySelectionStep';
import type { TestResult } from '../lib/setup-types';

/**
 * SetupWizardPage — first-run onboarding (spec §2.0.2).
 * Locked after completion via `system_config.first_run = false` on the server.
 *
 * 7 steps:
 *   1. License + risk disclosure (two mandatory checkboxes)
 *   2. Admin account creation (username, password + strength, optional email,
 *      12-word BIP-39 recovery phrase)
 *   3. 2FA setup (QR, TOTP verify, backup codes PDF, mandatory checkbox)
 *   4. Market selection (pick your country — sets timezone, currency, brokers, tax)
 *   5. Environment defaults (risk defaults, mode = PAPER — values from selected market)
 *   6. Integrations (configure external service credentials)
 *   7. Completion summary
 */

type StepKey = 'license' | 'account' | 'twofa' | 'market' | 'defaults' | 'integrations' | 'done';
const STEPS: { key: StepKey; label: string; icon: React.ElementType; blurb: string }[] = [
  { key: 'license', label: 'License & Disclosure', icon: ShieldCheck, blurb: 'Acknowledge open-source license and trading risks' },
  { key: 'account', label: 'Admin Account', icon: KeyRound, blurb: 'Create your single admin identity' },
  { key: 'twofa', label: 'Two-Factor Auth', icon: ShieldCheck, blurb: 'Mandatory TOTP for live-mode activation' },
  { key: 'market', label: 'Market', icon: Globe, blurb: 'Select your country and exchange' },
  { key: 'defaults', label: 'Defaults & Safety', icon: Cog, blurb: 'Risk caps and trading mode' },
  { key: 'integrations', label: 'Integrations', icon: Zap, blurb: 'Connect external services' },
  { key: 'done', label: 'All Set', icon: Sparkles, blurb: 'Review and head to login' },
];

function mockRecoveryPhrase(): string[] {
  // In production these come from server; mnemonic from BIP-39.
  const words = ['anchor', 'river', 'orbit', 'falcon', 'velvet', 'lantern', 'mosaic', 'harbor', 'pepper', 'glacier', 'nebula', 'canyon'];
  return words;
}

export default function SetupWizardPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<StepKey>('license');
  const stepIdx = STEPS.findIndex((s) => s.key === step);

  // Step 1
  const [acceptLicense, setAcceptLicense] = useState(false);
  const [acceptRisk, setAcceptRisk] = useState(false);

  // Step 2
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [email, setEmail] = useState('');
  const [phrase] = useState<string[]>(mockRecoveryPhrase);
  const [phraseConfirmed, setPhraseConfirmed] = useState(false);

  const passwordStrength = scorePassword(password);

  // Step 3
  const [totpCode, setTotpCode] = useState('');
  const [twoFactorConfirmed, setTwoFactorConfirmed] = useState(false);

  // Step 4 (defaults are read-only per spec: currency ₹ locked, mode PAPER locked)
  const [defaultsAck, setDefaultsAck] = useState(false);

  // Step: Market selection
  const [marketResult, setMarketResult] = useState<MarketSelectionResult | null>(null);

  const canAdvance = (() => {
    if (step === 'license') return acceptLicense && acceptRisk;
    if (step === 'account') return username.length >= 3 && password.length >= 10 && password === passwordConfirm && phraseConfirmed;
    if (step === 'twofa') return totpCode.length === 6 && twoFactorConfirmed;
    if (step === 'market') return marketResult !== null;
    if (step === 'defaults') return defaultsAck;
    if (step === 'integrations') return true; // Always allow advancing — all integrations are optional
    if (step === 'done') return true;
    return false;
  })();

  const onNext = () => {
    if (!canAdvance) return;
    const next = STEPS[stepIdx + 1]?.key;
    if (next) setStep(next);
  };
  const onBack = () => {
    const prev = STEPS[stepIdx - 1]?.key;
    if (prev) setStep(prev);
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: 'radial-gradient(ellipse at top, var(--surface-2) 0%, var(--surface-1) 55%, var(--surface-0) 100%)',
      padding: '40px 20px',
      display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
    }}>
      <div style={{ width: '100%', maxWidth: 820 }}>
        {/* Brand */}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <p style={{ fontSize: 10, letterSpacing: '0.24em', textTransform: 'uppercase', fontWeight: 800, color: 'var(--fg-muted)', margin: 0 }}>LOHI-TRADE · Community Edition</p>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: 'var(--fg-primary)', margin: '8px 0 4px', letterSpacing: '-0.025em' }}>First-run setup</h1>
          <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: 0 }}>Complete 6 steps to prepare your single-user trading stack.</p>
        </div>

        {/* Stepper */}
        <div style={{
          display: 'grid', gridTemplateColumns: `repeat(${STEPS.length}, 1fr)`, gap: 8, marginBottom: 20,
        }}>
          {STEPS.map((s, i) => {
            const isDone = i < stepIdx;
            const isActive = i === stepIdx;
            const Icon = s.icon;
            return (
              <div key={s.key} style={{
                display: 'flex', flexDirection: 'column', gap: 8,
                opacity: i > stepIdx ? 0.55 : 1,
              }}>
                <div style={{
                  height: 4, borderRadius: 2,
                  background: isDone ? 'var(--bull)' : isActive ? 'var(--accent)' : 'var(--line-2)',
                  transition: 'background 200ms var(--ease-out)',
                }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--fg-muted)' }}>
                  <Icon size={12} />
                  <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>{s.label}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Step body */}
        <BentoCard>
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
              style={{ padding: 28 }}
            >
              {step === 'license' && (
                <StepLicense
                  acceptLicense={acceptLicense} setAcceptLicense={setAcceptLicense}
                  acceptRisk={acceptRisk} setAcceptRisk={setAcceptRisk}
                />
              )}
              {step === 'account' && (
                <StepAccount
                  username={username} setUsername={setUsername}
                  password={password} setPassword={setPassword}
                  passwordConfirm={passwordConfirm} setPasswordConfirm={setPasswordConfirm}
                  email={email} setEmail={setEmail}
                  passwordStrength={passwordStrength}
                  phrase={phrase}
                  phraseConfirmed={phraseConfirmed} setPhraseConfirmed={setPhraseConfirmed}
                />
              )}
              {step === 'twofa' && (
                <StepTwoFA
                  totpCode={totpCode} setTotpCode={setTotpCode}
                  twoFactorConfirmed={twoFactorConfirmed} setTwoFactorConfirmed={setTwoFactorConfirmed}
                />
              )}
              {step === 'market' && (
                <CountrySelectionStep
                  selectedCountry={marketResult?.country ?? null}
                  onCountrySelected={(result) => setMarketResult(result)}
                />
              )}
              {step === 'defaults' && (
                <StepDefaults defaultsAck={defaultsAck} setDefaultsAck={setDefaultsAck} marketResult={marketResult} />
              )}
              {step === 'integrations' && <StepIntegrations />}
              {step === 'done' && <StepDone />}
            </motion.div>
          </AnimatePresence>
        </BentoCard>

        {/* Nav */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20 }}>
          {stepIdx > 0 && stepIdx < STEPS.length - 1 ? (
            <button onClick={onBack} style={btnGhost}>
              <ArrowLeft size={14} /> Back
            </button>
          ) : <span />}
          {step !== 'done' ? (
            <button onClick={onNext} disabled={!canAdvance} style={canAdvance ? btnPrimary : btnDisabled}>
              Continue <ArrowRight size={14} />
            </button>
          ) : (
            <button onClick={() => navigate('/login')} style={btnPrimary}>
              Go to Login <ArrowRight size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Steps ──────────────────────────────────────────────────────────── */

function StepLicense({
  acceptLicense, setAcceptLicense, acceptRisk, setAcceptRisk,
}: any) {
  return (
    <>
      <StepHeader title="License & Trading Risk" blurb="Read and acknowledge before you continue." />
      <div style={panel}>
        <h3 style={panelTitle}>AGPL-3.0-or-later</h3>
        <p style={panelText}>LOHI-TRADE Community Edition is released under AGPL-3.0. If you run a modified copy as a service, you must publish your changes. The core library and broker adapters are Apache-2.0.</p>
      </div>
      <div style={{ ...panel, background: 'var(--warn-soft)', borderColor: 'color-mix(in srgb, var(--warn) 30%, transparent)' }}>
        <h3 style={{ ...panelTitle, color: 'var(--warn)' }}>Trading risk disclosure</h3>
        <p style={panelText}>
          Algorithmic trading carries substantial risk of loss. You may lose all invested capital.
          The authors provide no investment advice and are not registered with SEBI. You are solely
          responsible for your trading decisions and compliance with applicable law.
        </p>
      </div>
      <Checkbox checked={acceptLicense} onChange={setAcceptLicense} label="I have read and accept the AGPL-3.0 license." />
      <Checkbox checked={acceptRisk} onChange={setAcceptRisk} label="I understand the trading risks and assume full responsibility." />
    </>
  );
}

function StepAccount({
  username, setUsername, password, setPassword, passwordConfirm, setPasswordConfirm,
  email, setEmail, passwordStrength, phrase, phraseConfirmed, setPhraseConfirmed,
}: any) {
  const copyPhrase = () => navigator.clipboard.writeText(phrase.join(' ')).catch(() => {});
  return (
    <>
      <StepHeader title="Admin account" blurb="This is the only user account. Keep credentials safe." />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <Field label="Username" value={username} onChange={setUsername} placeholder="admin" />
        <Field label="Email (optional)" value={email} onChange={setEmail} placeholder="[email]" />
        <Field label="Password" value={password} onChange={setPassword} type="password" placeholder="≥ 10 characters" />
        <Field label="Confirm password" value={passwordConfirm} onChange={setPasswordConfirm} type="password" />
      </div>

      {/* Strength meter */}
      <div style={{ marginTop: 12 }}>
        <div style={{ height: 6, borderRadius: 999, background: 'var(--surface-4)', overflow: 'hidden' }}>
          <motion.div
            animate={{ width: `${(passwordStrength.score / 4) * 100}%` }}
            style={{ height: '100%', background: passwordStrength.color, transition: 'width 300ms var(--ease-out)' }}
          />
        </div>
        <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 6 }}>{passwordStrength.hint}</p>
      </div>

      {/* Recovery phrase */}
      <div style={{ ...panel, marginTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <h3 style={panelTitle}>Recovery phrase</h3>
          <button onClick={copyPhrase} style={btnChip}><Copy size={11} /> Copy</button>
        </div>
        <p style={{ ...panelText, marginBottom: 12 }}>Write down these 12 words. They unlock TOTP reset if you lose your authenticator. <strong style={{ color: 'var(--warn)' }}>We will not show them again.</strong></p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
          {phrase.map((w: string, i: number) => (
            <div key={i} style={phraseWord}>
              <span style={{ fontSize: 10, color: 'var(--fg-muted)' }}>{String(i + 1).padStart(2, '0')}</span>
              <span style={{ fontFamily: 'ui-monospace, monospace', fontWeight: 600 }}>{w}</span>
            </div>
          ))}
        </div>
      </div>

      <Checkbox checked={phraseConfirmed} onChange={setPhraseConfirmed} label="I have safely stored my 12-word recovery phrase offline." />
    </>
  );
}

function StepTwoFA({ totpCode, setTotpCode, twoFactorConfirmed, setTwoFactorConfirmed }: any) {
  return (
    <>
      <StepHeader title="Two-factor authentication" blurb="Required. Live-mode activation is blocked without verified TOTP." />
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 28, alignItems: 'center' }}>
        <div style={{
          width: 168, height: 168,
          background: '#fff',
          borderRadius: 'var(--r-md)',
          display: 'grid', placeItems: 'center',
          border: '1px solid var(--line-2)',
        }}>
          {/* Placeholder QR — real QR rendered by qrcode lib on first run */}
          <div style={{
            width: 136, height: 136,
            backgroundImage: 'repeating-linear-gradient(45deg, #000 0 4px, transparent 4px 8px)',
            opacity: 0.85,
          }} />
        </div>
        <div>
          <p style={panelText}>Scan with Google Authenticator, 1Password, Raivo, or any RFC 6238 app.</p>
          <p style={{ ...panelText, fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--fg-muted)', marginTop: 10 }}>Or type secret: <span style={{ color: 'var(--fg-secondary)' }}>ABCD EFGH IJKL MNOP QRST UVWX</span></p>
          <Field
            label="Enter 6-digit code"
            value={totpCode}
            onChange={(v: string) => setTotpCode(v.replace(/\D/g, '').slice(0, 6))}
            placeholder="123 456"
          />
        </div>
      </div>

      <div style={{ ...panel, marginTop: 16 }}>
        <h3 style={panelTitle}>Backup codes</h3>
        <p style={panelText}>Download 10 single-use backup codes in case your authenticator is unavailable. Each code works once.</p>
        <button style={{ ...btnChip, marginTop: 10 }}>Download backup codes (PDF)</button>
      </div>

      <Checkbox checked={twoFactorConfirmed} onChange={setTwoFactorConfirmed} label="I have saved my backup codes and verified a code above." />
    </>
  );
}

function StepDefaults({ defaultsAck, setDefaultsAck, marketResult }: any) {
  // Use market selection result for dynamic values, fallback to India defaults
  const currency = marketResult?.currency_symbol ?? '₹';
  const currencyCode = marketResult?.currency ?? 'INR';
  const timezone = marketResult?.timezone ?? 'Asia/Kolkata';
  const squareOff = marketResult?.sessions?.square_off_time ?? '15:15';
  const countryName = marketResult?.country_name ?? 'India';

  return (
    <>
      <StepHeader title="Defaults & safety" blurb={`Conservative pre-configured values for ${countryName}. You can change risk limits later.`} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <ReadonlyField label="Timezone" value={timezone} />
        <ReadonlyField label="Currency" value={`${currencyCode} (${currency})`} locked />
        <ReadonlyField label="Trading mode" value="PAPER" locked />
        <ReadonlyField label="Max order value" value={`${currency}1,00,000`} />
        <ReadonlyField label="Max open positions" value="10" />
        <ReadonlyField label="Daily loss limit" value={`${currency}-10,000`} />
        <ReadonlyField label="Price sanity" value="5%" />
        <ReadonlyField label="Intraday square-off" value={`${squareOff} ${timezone.split('/')[1]?.replace('_', ' ') || ''}`} />
      </div>
      <Checkbox checked={defaultsAck} onChange={setDefaultsAck} label="These defaults look reasonable to start with." />
    </>
  );
}

function StepDone() {
  return (
    <div style={{ textAlign: 'center', padding: '20px 10px' }}>
      <motion.div
        initial={{ scale: 0.5, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 22 }}
        style={{
          width: 72, height: 72, borderRadius: '50%',
          display: 'grid', placeItems: 'center',
          background: 'var(--bull-soft)',
          color: 'var(--bull)',
          margin: '0 auto 18px',
          boxShadow: '0 0 0 8px color-mix(in srgb, var(--bull) 12%, transparent)',
        }}
      >
        <Check size={32} />
      </motion.div>
      <h2 style={{ fontSize: 22, fontWeight: 800, color: 'var(--fg-primary)', margin: 0 }}>You're all set</h2>
      <p style={{ fontSize: 13, color: 'var(--fg-muted)', marginTop: 8, maxWidth: 460, marginInline: 'auto' }}>
        Sign in with your admin credentials and TOTP. The system starts in <strong style={{ color: 'var(--warn)' }}>PAPER</strong> mode.
        Connect a broker from Settings → Brokers, run at least one paper session, then you can unlock LIVE mode.
      </p>
    </div>
  );
}

/* ─── Integrations Step ──────────────────────────────────────────────── */

const SERVICE_COLORS: Record<string, string> = {
  nvidia_nim: '#76b900',
  nubra: '#6366f1',
  broker_shoonya: '#10b981',
  broker_angelone: '#f59e0b',
  telegram: '#229ed9',
  ollama: '#ef4444',
};

function StepIntegrations() {
  const { services, loading, fetchStatus, submitCredentials, testConnection, skipGroup } = useSetupStore();

  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const getStatus = useCallback((groupId: string) => {
    return services.find((s) => s.group_id === groupId)?.status ?? 'unconfigured';
  }, [services]);

  return (
    <>
      <StepHeader title="Integrations" blurb="Connect external services. All are optional — skip any you don't need yet." />

      {loading && services.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
          <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} color="var(--fg-muted)" />
        </div>
      )}

      <div style={{ display: 'grid', gap: 10 }}>
        {CREDENTIAL_GROUPS.map((group) => {
          const status = getStatus(group.group_id);
          const color = SERVICE_COLORS[group.group_id] || 'var(--accent)';
          const isExpanded = expandedId === group.group_id;

          return (
            <div key={group.group_id} style={{
              borderRadius: 'var(--r-md)', border: '1px solid var(--line-2)',
              background: 'var(--surface-3)', overflow: 'hidden',
            }}>
              {/* Header row */}
              <button
                type="button"
                onClick={() => setExpandedId(isExpanded ? null : group.group_id)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  width: '100%', padding: '12px 14px', background: 'transparent', border: 'none',
                  cursor: 'pointer', textAlign: 'left' as const, gap: 10,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: `${color}18`, border: `1px solid ${color}30`,
                  }}>
                    <Zap size={14} color={color} />
                  </div>
                  <div>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)' }}>{group.name}</span>
                    <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '1px 0 0' }}>
                      {group.description.split('.')[0]}.
                    </p>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <IntegrationStatusPill status={status} />
                </div>
              </button>

              {/* Expanded form */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                    style={{ overflow: 'hidden' }}
                  >
                    <div style={{ borderTop: '1px solid var(--line-2)', padding: '14px' }}>
                      <InlineCredentialForm
                        group={group}
                        status={status}
                        onSubmit={async (creds) => {
                          await submitCredentials(group.group_id, creds);
                        }}
                        onTest={async () => await testConnection(group.group_id)}
                        onSkip={async () => { await skipGroup(group.group_id); }}
                      />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 14 }}>
        You can configure these later from Settings → Integrations.
      </p>
    </>
  );
}

function IntegrationStatusPill({ status }: { status: string }) {
  const color = status === 'configured' ? 'var(--bull)' : status === 'skipped' ? 'var(--warn)' : status === 'error' ? 'var(--bear)' : 'var(--fg-muted)';
  const label = status === 'configured' ? 'Done' : status === 'skipped' ? 'Skipped' : status === 'error' ? 'Error' : 'Pending';
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 6,
      background: `${color}12`, color, letterSpacing: '0.04em',
      border: `1px solid ${color}25`,
    }}>
      {label}
    </span>
  );
}

interface InlineCredentialFormProps {
  group: typeof CREDENTIAL_GROUPS[number];
  status: string;
  onSubmit: (credentials: Record<string, string>) => Promise<void>;
  onTest: () => Promise<TestResult>;
  onSkip: () => Promise<void>;
}

function InlineCredentialForm({ group, status, onSubmit, onTest, onSkip }: InlineCredentialFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(group.credential_keys.map((key) => [key, ''])),
  );
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const hasKeys = group.credential_keys.length > 0;

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {};
    for (const key of group.credential_keys) {
      const value = values[key] ?? '';
      const pattern = group.validation_patterns[key];
      if (!value.trim()) { newErrors[key] = 'Required'; }
      else if (pattern) {
        try { if (!new RegExp(pattern).test(value)) newErrors[key] = 'Invalid format'; } catch { /* skip */ }
      }
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [group.credential_keys, group.validation_patterns, values]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;
    setSubmitting(true);
    try { await onSubmit(values); } finally { setSubmitting(false); }
  }, [validate, onSubmit, values]);

  const handleTest = useCallback(async () => {
    setTesting(true); setTestResult(null);
    try { setTestResult(await onTest()); }
    catch { setTestResult({ success: false, response_time_ms: null, error: 'Test failed', suggestion: null }); }
    finally { setTesting(false); }
  }, [onTest]);

  return (
    <div>
      {/* Docs link */}
      <a
        href={group.documentation_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--accent-2)', fontWeight: 600, marginBottom: 12, textDecoration: 'none' }}
      >
        <ExternalLink size={11} /> Documentation
      </a>

      {/* Credential fields */}
      {hasKeys ? (
        <div style={{ display: 'grid', gap: 10, marginBottom: 12 }}>
          {group.credential_keys.map((key) => {
            const isRevealed = revealed[key] ?? false;
            const hint = group.tooltip_hints[key];
            return (
              <div key={key}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
                  <span style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 700, color: 'var(--fg-muted)' }}>
                    {key.replace(/_/g, ' ')}
                  </span>
                  {hint && <span title={hint} style={{ cursor: 'help', color: 'var(--fg-muted)' }}><Info size={10} /></span>}
                </div>
                <div style={{ position: 'relative' }}>
                  <input
                    type={isRevealed ? 'text' : 'password'}
                    value={values[key] ?? ''}
                    onChange={(e) => {
                      setValues((p) => ({ ...p, [key]: e.target.value }));
                      setErrors((p) => { const n = { ...p }; delete n[key]; return n; });
                    }}
                    placeholder={hint || `Enter ${key}`}
                    autoComplete="off"
                    style={{
                      ...inputStyle, width: '100%', paddingRight: 32,
                      borderColor: errors[key] ? 'var(--bear)' : 'var(--line-2)',
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setRevealed((p) => ({ ...p, [key]: !p[key] }))}
                    style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fg-muted)', padding: 2 }}
                    aria-label={isRevealed ? 'Hide' : 'Reveal'}
                  >
                    {isRevealed ? <EyeOff size={12} /> : <Eye size={12} />}
                  </button>
                </div>
                {errors[key] && <p style={{ fontSize: 10, color: 'var(--bear)', marginTop: 2 }}>{errors[key]}</p>}
              </div>
            );
          })}
        </div>
      ) : (
        <p style={{ fontSize: 12, color: 'var(--fg-secondary)', marginBottom: 12 }}>
          No credentials needed — runs locally on your machine.
        </p>
      )}

      {/* Test result */}
      {testResult && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', borderRadius: 'var(--r-sm)',
          marginBottom: 10,
          background: testResult.success ? 'var(--bull-soft)' : 'var(--bear-soft)',
        }}>
          {testResult.success ? <CheckCircle2 size={13} color="var(--bull)" /> : <XCircle size={13} color="var(--bear)" />}
          <span style={{ fontSize: 11, fontWeight: 600, color: testResult.success ? 'var(--bull)' : 'var(--bear)' }}>
            {testResult.success ? 'Connected' : (testResult.error ?? 'Failed')}
          </span>
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {hasKeys && (
          <button onClick={handleSubmit} disabled={submitting} style={{
            ...btnChip,
            background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
            border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
            color: '#fff', opacity: submitting ? 0.6 : 1,
          }}>
            {submitting && <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} />}
            {submitting ? 'Saving…' : 'Save'}
          </button>
        )}
        <button onClick={handleTest} disabled={testing || status === 'unconfigured'} style={{
          ...btnChip, opacity: (testing || status === 'unconfigured') ? 0.5 : 1,
        }}>
          {testing && <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} />}
          Test
        </button>
        {!group.required && status !== 'skipped' && (
          <button onClick={onSkip} style={btnChip}>
            <SkipForward size={11} /> Skip
          </button>
        )}
      </div>
    </div>
  );
}

/* ─── Atoms ──────────────────────────────────────────────────────────── */

function StepHeader({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.02em' }}>{title}</h2>
      <p style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 4 }}>{blurb}</p>
    </div>
  );
}

function Field({
  label, value, onChange, placeholder, type = 'text',
}: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={fieldLabel}>{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={inputStyle}
      />
    </label>
  );
}

function ReadonlyField({ label, value, locked }: { label: string; value: string; locked?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={fieldLabel}>{label}{locked && <span style={{ color: 'var(--fg-muted)', marginLeft: 6, fontWeight: 600 }}>· locked</span>}</span>
      <div style={{ ...inputStyle, color: 'var(--fg-primary)', background: 'var(--surface-4)', cursor: 'default' }}>{value}</div>
    </div>
  );
}

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, cursor: 'pointer', fontSize: 13, color: 'var(--fg-secondary)' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ width: 16, height: 16, accentColor: 'var(--accent)' }} />
      <span>{label}</span>
    </label>
  );
}

function scorePassword(pw: string): { score: number; color: string; hint: string } {
  if (!pw) return { score: 0, color: 'var(--line-2)', hint: 'Enter a password' };
  let s = 0;
  if (pw.length >= 10) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  const map = [
    { color: 'var(--bear)', hint: 'Very weak' },
    { color: 'var(--bear)', hint: 'Weak' },
    { color: 'var(--warn)', hint: 'Fair' },
    { color: 'var(--bull)', hint: 'Good' },
    { color: 'var(--bull)', hint: 'Strong' },
  ];
  return { score: s, ...map[s] };
}

/* ─── Styles ─────────────────────────────────────────────────────────── */

const fieldLabel: React.CSSProperties = {
  fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
  fontWeight: 700, color: 'var(--fg-muted)',
};
const inputStyle: React.CSSProperties = {
  padding: '10px 12px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  fontSize: 13, color: 'var(--fg-primary)', outline: 'none',
  fontFamily: 'inherit',
};
const panel: React.CSSProperties = {
  marginTop: 16, padding: '14px 16px', borderRadius: 'var(--r-md)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
};
const panelTitle: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 6px',
};
const panelText: React.CSSProperties = {
  fontSize: 12, color: 'var(--fg-secondary)', margin: 0, lineHeight: 1.55,
};
const phraseWord: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 2,
  padding: '8px 10px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-2)', border: '1px solid var(--line-2)',
  fontSize: 13, color: 'var(--fg-primary)',
};
const btnGhost: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '8px 14px', borderRadius: 'var(--r-sm)',
  background: 'transparent', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
};
const btnPrimary: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '8px 16px', borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
  boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
};
const btnDisabled: React.CSSProperties = { ...btnPrimary, opacity: 0.5, cursor: 'not-allowed', boxShadow: 'none' };
const btnChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  padding: '5px 10px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-4)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
};
