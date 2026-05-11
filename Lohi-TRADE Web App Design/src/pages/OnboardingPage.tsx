import { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import {
  User, Link2, Gauge, Sparkles, ArrowRight, Check,
  Wallet, AlertTriangle, Target, Briefcase, Rocket,
} from 'lucide-react';
import OnboardingShell, { type OnboardingStep } from '../components/onboarding/OnboardingShell';
import LohiAvatar, { type LohiAction, type LohiMood } from '../components/onboarding/LohiAvatar';
import ProjectionWidget from '../components/onboarding/ProjectionWidget';
import '../styles/onboarding.css';

/**
 * OnboardingPage — /onboarding
 *
 * The "Wealth Architect" journey narrated by Lohi in first person.
 * Each step pairs with a Lohi gesture so the mascot actively helps:
 *   1. The Blueprint       — Lohi waves hello 👋
 *   2. Syncing the Engine  — Lohi points to the account list 👉
 *   3. The Stress Test     — Lohi thinks while you choose 🤔
 *   4. Activation          — Lohi celebrates with confetti 🎉
 */

const STEPS: OnboardingStep[] = [
  {
    key: 'blueprint',
    title: 'The Blueprint',
    quote:
      "Hey, I'm Lohi. Think of me as the quant in your corner. A couple of numbers and I'll sketch your first money map — no spreadsheets, promise.",
  },
  {
    key: 'sync',
    title: 'Syncing the Engine',
    quote:
      "Plug in a wallet or two and I'll show you where your capital actually sleeps. Read-only access. Nothing moves without you.",
  },
  {
    key: 'risk',
    title: 'The Stress Test',
    quote:
      "This is the one question everyone skips. Pick an appetite that you'd hold through a rough week — I'll tune every alert to it.",
  },
  {
    key: 'activate',
    title: 'Activation',
    quote:
      "We did it. Your first dashboard is ready. Hit the button and I'll walk you through the cockpit.",
  },
];

type RiskAppetite = 'conservative' | 'balanced' | 'aggressive';

export default function OnboardingPage() {
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);
  const [bomb, setBomb] = useState<{ title: string; tip: string } | null>(null);

  /* ── Lohi gesture orchestration ── */
  const [lohiAction, setLohiAction] = useState<LohiAction>('wave');
  const [lohiActionKey, setLohiActionKey] = useState(0);
  const [lohiMood, setLohiMood] = useState<LohiMood>('happy');

  const trigger = (a: LohiAction, mood: LohiMood = 'happy') => {
    setLohiAction(a);
    setLohiMood(mood);
    setLohiActionKey((k) => k + 1);
  };

  /* ── Step 1: Blueprint ── */
  const [fullName, setFullName] = useState('');
  const [monthlyIncome, setMonthlyIncome] = useState('');
  const [savingsGoal, setSavingsGoal] = useState('');

  /* ── Step 2: Sync ── */
  const [syncedAccounts, setSyncedAccounts] = useState<string[]>([]);
  const [syncingId, setSyncingId] = useState<string | null>(null);

  /* ── Step 3: Risk ── */
  const [risk, setRisk] = useState<RiskAppetite | null>(null);
  const [horizonYears, setHorizonYears] = useState(10);

  /* ── Integrity calculation (0–100 based on how much of the flow is done) ── */
  const integrity = useMemo(() => {
    let pct = 0;
    if (fullName.trim().length > 1) pct += 12;
    if (monthlyIncome && Number(monthlyIncome) > 0) pct += 9;
    if (savingsGoal && Number(savingsGoal) > 0) pct += 9;
    if (syncedAccounts.length >= 1) pct += 15;
    if (syncedAccounts.length >= 2) pct += 10;
    if (risk) pct += 20;
    pct += Math.min(25, stepIndex * 8); // bonus per step reached
    return Math.min(100, pct);
  }, [fullName, monthlyIncome, savingsGoal, syncedAccounts, risk, stepIndex]);

  /* ── Handlers ── */
  const goNext = () => {
    setStepIndex((i) => Math.min(STEPS.length - 1, i + 1));
  };
  const goBack = () => {
    setStepIndex((i) => Math.max(0, i - 1));
  };

  const popBomb = (title: string, tip: string) => setBomb({ title, tip });

  // Orchestrate Lohi's gesture per step + fire a knowledge bomb on arrival.
  useEffect(() => {
    if (stepIndex === 0) {
      trigger('wave', 'happy');
    } else if (stepIndex === 1) {
      trigger('point', 'neutral');
      popBomb(
        'Profile secured. Nice.',
        "The first 5 minutes of a plan are worth more than 5 years of regret. You just bought yourself 5 years.",
      );
    } else if (stepIndex === 2) {
      trigger('idle', 'focused');
      if (syncedAccounts.length >= 1) {
        popBomb(
          'Your capital is now visible.',
          "Most investors underestimate their idle cash by 23%. A good dashboard ends that illusion.",
        );
      }
    } else if (stepIndex === 3) {
      trigger('celebrate', 'happy');
      if (risk) {
        popBomb(
          'Risk profile locked in.',
          'A balanced portfolio loses less in bad years than a concentrated one — by definition. You just tilted the math in your favor.',
        );
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIndex]);

  const mockAccounts = [
    { id: 'hdfc', name: 'HDFC Savings', type: 'Savings Account', balance: '₹ 2,45,320' },
    { id: 'zerodha', name: 'Zerodha Demat', type: 'Demat', balance: '₹ 18,72,450' },
    { id: 'pf', name: 'EPFO', type: 'Provident Fund', balance: '₹ 4,30,108' },
  ];

  const handleSyncAccount = (id: string) => {
    if (syncedAccounts.includes(id) || syncingId) return;
    setSyncingId(id);
    trigger('idle', 'focused'); // Lohi watches carefully while the connection spins up
    setTimeout(() => {
      setSyncedAccounts((p) => [...p, id]);
      setSyncingId(null);
      trigger('thumbsUp', 'happy'); // Thumbs-up the moment it links
      if (syncedAccounts.length === 0) {
        popBomb(
          'First account linked. Nice work.',
          'Every account you connect sharpens the signal. Aim for all of them — even the one you forgot about.',
        );
      }
    }, 1400);
  };

  const handleComplete = () => {
    // In production: POST /api/v2/users/onboard-complete
    navigate('/', { replace: true });
  };

  return (
    <OnboardingShell
      steps={STEPS}
      currentIndex={stepIndex}
      integrityPct={integrity}
      onBack={stepIndex > 0 ? goBack : undefined}
      knowledgeBomb={bomb}
      onKnowledgeBombDismiss={() => setBomb(null)}
      lohiAction={lohiAction}
      lohiActionKey={lohiActionKey}
      lohiMood={lohiMood}
    >
      {stepIndex === 0 && (
        <BlueprintStep
          fullName={fullName}
          setFullName={setFullName}
          monthlyIncome={monthlyIncome}
          setMonthlyIncome={setMonthlyIncome}
          savingsGoal={savingsGoal}
          setSavingsGoal={setSavingsGoal}
          onNext={goNext}
        />
      )}
      {stepIndex === 1 && (
        <SyncStep
          accounts={mockAccounts}
          synced={syncedAccounts}
          syncingId={syncingId}
          onSync={handleSyncAccount}
          onNext={goNext}
        />
      )}
      {stepIndex === 2 && (
        <RiskStep
          risk={risk}
          setRisk={(r) => {
            setRisk(r);
            trigger('thumbsUp', 'happy');
          }}
          horizonYears={horizonYears}
          setHorizonYears={setHorizonYears}
          monthly={Number(monthlyIncome) ? Number(monthlyIncome) * 0.2 : 10000}
          onNext={goNext}
        />
      )}
      {stepIndex === 3 && (
        <ActivationStep
          fullName={fullName}
          syncedCount={syncedAccounts.length}
          risk={risk}
          horizonYears={horizonYears}
          monthly={Number(monthlyIncome) ? Number(monthlyIncome) * 0.2 : 10000}
          onComplete={handleComplete}
        />
      )}
    </OnboardingShell>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   STEP 1 · The Blueprint
   ══════════════════════════════════════════════════════════════════════════ */
function BlueprintStep({
  fullName, setFullName, monthlyIncome, setMonthlyIncome,
  savingsGoal, setSavingsGoal, onNext,
}: {
  fullName: string; setFullName: (s: string) => void;
  monthlyIncome: string; setMonthlyIncome: (s: string) => void;
  savingsGoal: string; setSavingsGoal: (s: string) => void;
  onNext: () => void;
}) {
  const monthly = Number(monthlyIncome) || 0;
  const ready = fullName.trim().length > 1 && monthly > 0;
  return (
    <StepContainer icon={<User size={18} />} headline="Let's lay the blueprint.">
      <p style={bodyText}>
        Single-task focus. Enter one value at a time. Your data is encrypted end-to-end
        and never leaves your machine.
      </p>

      <div style={{ display: 'grid', gap: 18, marginTop: 26 }}>
        <Field label="Your name">
          <input
            className="ob-field"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="e.g., Priya Sharma"
            autoFocus
          />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Field label="Monthly income (₹)">
            <input
              className="ob-field"
              value={monthlyIncome}
              onChange={(e) => setMonthlyIncome(e.target.value.replace(/\D/g, ''))}
              placeholder="1,50,000"
              inputMode="numeric"
            />
          </Field>
          <Field label="Savings goal this year (₹)">
            <input
              className="ob-field"
              value={savingsGoal}
              onChange={(e) => setSavingsGoal(e.target.value.replace(/\D/g, ''))}
              placeholder="5,00,000"
              inputMode="numeric"
            />
          </Field>
        </div>
      </div>

      {/* Live projection reacts to income */}
      {monthly > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          style={{ marginTop: 26 }}
        >
          <ProjectionWidget monthly={Math.max(500, monthly * 0.2)} annualReturnPct={12} years={10} />
        </motion.div>
      )}

      <NextButton disabled={!ready} onClick={onNext} label="Continue to sync" />
    </StepContainer>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   STEP 2 · Syncing the Engine
   ══════════════════════════════════════════════════════════════════════════ */
function SyncStep({
  accounts, synced, syncingId, onSync, onNext,
}: {
  accounts: { id: string; name: string; type: string; balance: string }[];
  synced: string[];
  syncingId: string | null;
  onSync: (id: string) => void;
  onNext: () => void;
}) {
  const ready = synced.length >= 1;
  return (
    <StepContainer icon={<Link2 size={18} />} headline="Plug in your accounts.">
      <p style={bodyText}>
        I&apos;ll run a diagnostic on each connection. No funds move. Read-only access only.
      </p>

      <div style={{ display: 'grid', gap: 10, marginTop: 24 }}>
        {accounts.map((acct) => {
          const isSynced = synced.includes(acct.id);
          const isSyncing = syncingId === acct.id;
          return (
            <motion.button
              key={acct.id}
              whileHover={{ y: isSynced || isSyncing ? 0 : -1 }}
              onClick={() => onSync(acct.id)}
              disabled={isSynced || isSyncing}
              className="ob-glass"
              style={{
                display: 'grid',
                gridTemplateColumns: '40px 1fr auto',
                alignItems: 'center',
                gap: 14,
                padding: '16px 20px',
                textAlign: 'left',
                cursor: isSynced || isSyncing ? 'default' : 'pointer',
                color: 'var(--ob-silver-text)',
                borderColor: isSynced
                  ? 'color-mix(in srgb, var(--ob-growth) 40%, transparent)'
                  : 'var(--ob-silver-1)',
              }}
            >
              <span
                style={{
                  display: 'grid',
                  placeItems: 'center',
                  width: 40,
                  height: 40,
                  borderRadius: 12,
                  background: isSynced ? 'var(--ob-growth-soft)' : 'var(--ob-silver-0)',
                  color: isSynced ? 'var(--ob-growth)' : 'var(--ob-silver-muted)',
                }}
              >
                {isSynced ? <Check size={16} strokeWidth={3} /> : <Wallet size={16} />}
              </span>
              <div>
                <p style={{ fontSize: 14, fontWeight: 700, margin: 0, color: 'var(--ob-silver-text)' }}>
                  {acct.name}
                </p>
                <p style={{ fontSize: 11, color: 'var(--ob-silver-muted)', margin: '2px 0 0' }}>
                  {acct.type} {isSynced && `· ${acct.balance}`}
                </p>
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: isSynced ? 'var(--ob-growth)' : 'var(--ob-silver-muted)' }}>
                {isSyncing ? (
                  <SyncingSpinner />
                ) : isSynced ? 'Linked' : 'Connect'}
              </span>
            </motion.button>
          );
        })}
      </div>

      <NextButton
        disabled={!ready}
        onClick={onNext}
        label={synced.length < accounts.length ? 'Continue (skip remaining)' : 'Continue to stress test'}
      />
    </StepContainer>
  );
}

function SyncingSpinner() {
  return (
    <motion.span
      aria-label="Syncing"
      animate={{ rotate: 360 }}
      transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
      style={{
        display: 'inline-block',
        width: 14,
        height: 14,
        borderRadius: '50%',
        border: '2px solid var(--ob-silver-2)',
        borderTopColor: 'var(--ob-growth)',
      }}
    />
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   STEP 3 · The Stress Test
   ══════════════════════════════════════════════════════════════════════════ */
function RiskStep({
  risk, setRisk, horizonYears, setHorizonYears, monthly, onNext,
}: {
  risk: RiskAppetite | null;
  setRisk: (r: RiskAppetite) => void;
  horizonYears: number;
  setHorizonYears: (y: number) => void;
  monthly: number;
  onNext: () => void;
}) {
  const ready = !!risk;
  const returnByRisk: Record<RiskAppetite, number> = {
    conservative: 8,
    balanced: 12,
    aggressive: 16,
  };
  const options: { id: RiskAppetite; label: string; sub: string; icon: React.ReactNode; color: string }[] = [
    {
      id: 'conservative',
      label: 'Conservative',
      sub: 'Protect capital first. ~8% expected return.',
      icon: <Briefcase size={16} />,
      color: '#5eead4',
    },
    {
      id: 'balanced',
      label: 'Balanced',
      sub: 'Steady growth with measured risk. ~12%.',
      icon: <Target size={16} />,
      color: 'var(--ob-growth)',
    },
    {
      id: 'aggressive',
      label: 'Aggressive',
      sub: 'Chase upside, accept volatility. ~16%.',
      icon: <AlertTriangle size={16} />,
      color: '#fbbf24',
    },
  ];

  return (
    <StepContainer icon={<Gauge size={18} />} headline="What's your comfort zone?">
      <p style={bodyText}>
        I&apos;ll tune every alert, every projection, and every signal to the appetite you
        pick here. No judgment — the best risk profile is the one you can actually stick to.
      </p>

      <div style={{ display: 'grid', gap: 10, marginTop: 24 }}>
        {options.map((o) => {
          const active = risk === o.id;
          return (
            <button
              key={o.id}
              onClick={() => setRisk(o.id)}
              className="ob-glass"
              style={{
                display: 'grid',
                gridTemplateColumns: '40px 1fr auto',
                alignItems: 'center',
                gap: 14,
                padding: '16px 20px',
                textAlign: 'left',
                cursor: 'pointer',
                color: 'var(--ob-silver-text)',
                borderColor: active
                  ? 'color-mix(in srgb, var(--ob-growth) 50%, transparent)'
                  : 'var(--ob-silver-1)',
                boxShadow: active
                  ? `0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 32px var(--ob-growth-glow), 0 0 0 1px var(--ob-growth-line)`
                  : undefined,
              }}
            >
              <span
                style={{
                  display: 'grid',
                  placeItems: 'center',
                  width: 40,
                  height: 40,
                  borderRadius: 12,
                  background: `color-mix(in srgb, ${o.color} 16%, transparent)`,
                  color: o.color,
                }}
              >
                {o.icon}
              </span>
              <div>
                <p style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>{o.label}</p>
                <p style={{ fontSize: 11, color: 'var(--ob-silver-muted)', margin: '2px 0 0' }}>
                  {o.sub}
                </p>
              </div>
              {active ? (
                <span style={{
                  display: 'grid', placeItems: 'center', width: 22, height: 22, borderRadius: '50%',
                  background: 'var(--ob-growth)', color: '#001f14',
                }}>
                  <Check size={12} strokeWidth={3} />
                </span>
              ) : (
                <span style={{
                  width: 22, height: 22, borderRadius: '50%',
                  border: '1.5px solid var(--ob-silver-2)',
                }} />
              )}
            </button>
          );
        })}
      </div>

      {/* Horizon slider */}
      <div style={{ marginTop: 28 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
          <span className="ob-field-label" style={{ marginBottom: 0 }}>Investment horizon</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--ob-growth)', fontVariantNumeric: 'tabular-nums' }}>
            {horizonYears} years
          </span>
        </div>
        <input
          type="range"
          min={1}
          max={30}
          value={horizonYears}
          onChange={(e) => setHorizonYears(parseInt(e.target.value))}
          style={{
            width: '100%',
            accentColor: 'var(--ob-growth)',
            height: 4,
          }}
        />
      </div>

      {/* Live projection */}
      <div style={{ marginTop: 22 }}>
        <ProjectionWidget
          monthly={monthly}
          annualReturnPct={risk ? returnByRisk[risk] : 12}
          years={horizonYears}
        />
      </div>

      <NextButton disabled={!ready} onClick={onNext} label="Review & activate" />
    </StepContainer>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   STEP 4 · Activation
   ══════════════════════════════════════════════════════════════════════════ */
function ActivationStep({
  fullName, syncedCount, risk, horizonYears, monthly, onComplete,
}: {
  fullName: string;
  syncedCount: number;
  risk: RiskAppetite | null;
  horizonYears: number;
  monthly: number;
  onComplete: () => void;
}) {
  return (
    <StepContainer icon={<Sparkles size={18} />} headline={`${fullName.split(' ')[0] || 'You'}, everything looks solid.`}>
      <p style={bodyText}>
        I&apos;ve compiled your first insights. One click launches your personalized dashboard.
      </p>

      <div className="ob-glass" style={{ padding: 24, marginTop: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 20 }}>
          <LohiAvatar size="xl" speaking action="celebrate" actionKey={1} mood="happy" />
          <div>
            <p style={{ fontSize: 10, fontWeight: 800, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--ob-silver-muted)', margin: 0 }}>
              Your Wealth Architect
            </p>
            <p style={{ fontSize: 26, fontWeight: 700, color: 'var(--ob-silver-text)', margin: '6px 0 0', letterSpacing: '-0.02em' }}>
              First diagnostic complete.
            </p>
            <p style={{ fontSize: 13, color: 'var(--ob-silver-muted)', margin: '6px 0 0', lineHeight: 1.55, maxWidth: 420 }}>
              Great teamwork. I&apos;ve wired up your inputs, calibrated your risk dials, and drafted your first projection. One tap and we&apos;re live.
            </p>
          </div>
        </div>

        <dl
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '14px 24px',
            margin: 0,
            paddingTop: 20,
            borderTop: '1px solid var(--ob-silver-1)',
          }}
        >
          <SummaryRow label="Profile" value={fullName || '—'} />
          <SummaryRow label="Accounts linked" value={`${syncedCount}`} />
          <SummaryRow label="Risk profile" value={risk ? risk[0].toUpperCase() + risk.slice(1) : '—'} />
          <SummaryRow label="Horizon" value={`${horizonYears} years`} />
        </dl>
      </div>

      <ProjectionWidget
        monthly={monthly}
        annualReturnPct={risk === 'aggressive' ? 16 : risk === 'conservative' ? 8 : 12}
        years={horizonYears}
      />

      <motion.button
        onClick={onComplete}
        whileHover={{ y: -1 }}
        className="ob-growth-btn"
        style={{ marginTop: 28, padding: '14px 28px', fontSize: 14 }}
      >
        <Rocket size={14} />
        Step into the driver&apos;s seat
        <ArrowRight size={14} />
      </motion.button>
    </StepContainer>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt
        style={{
          fontSize: 10,
          fontWeight: 800,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--ob-silver-muted)',
        }}
      >
        {label}
      </dt>
      <dd
        style={{
          fontSize: 15,
          fontWeight: 700,
          color: 'var(--ob-silver-text)',
          margin: '4px 0 0',
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </dd>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Shared atoms
   ══════════════════════════════════════════════════════════════════════════ */
function StepContainer({
  icon, headline, children,
}: { icon: React.ReactNode; headline: string; children: React.ReactNode }) {
  return (
    <div className="ob-glass" style={{ padding: '32px 36px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <span
          style={{
            display: 'grid',
            placeItems: 'center',
            width: 30,
            height: 30,
            borderRadius: 10,
            background: 'var(--ob-growth-soft)',
            color: 'var(--ob-growth)',
          }}
        >
          {icon}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--ob-growth)',
          }}
        >
          Focus Screen
        </span>
      </div>
      <h1
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: 'var(--ob-silver-text)',
          margin: '12px 0 0',
          letterSpacing: '-0.025em',
          lineHeight: 1.15,
        }}
      >
        {headline}
      </h1>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'block' }}>
      <span className="ob-field-label">{label}</span>
      {children}
    </label>
  );
}

function NextButton({
  onClick, disabled, label,
}: { onClick: () => void; disabled?: boolean; label: string }) {
  return (
    <div style={{ marginTop: 32, display: 'flex', justifyContent: 'flex-end' }}>
      <button className="ob-growth-btn" onClick={onClick} disabled={disabled}>
        {label}
        <ArrowRight size={14} />
      </button>
    </div>
  );
}

const bodyText: React.CSSProperties = {
  fontSize: 14,
  color: 'var(--ob-silver-muted)',
  margin: '10px 0 0',
  lineHeight: 1.65,
  maxWidth: 560,
};
