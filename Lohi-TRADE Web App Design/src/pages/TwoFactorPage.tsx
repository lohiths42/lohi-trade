import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ShieldCheck, ArrowLeft, AlertTriangle, KeyRound } from 'lucide-react';
import { BentoCard } from '../components/shared/BentoCard';
import { useAuthStore } from '../stores/auth-store';

/**
 * TwoFactorPage — spec §2.0.4 /login/2fa.
 *
 * Behavior:
 *   • 6-digit numeric field auto-submits on completion.
 *   • "Use backup code" swaps to 8-character input.
 *   • 5 failures ⇒ 15-min lockout.
 *   • On success ⇒ redirect to ?next= or /dashboard.
 *
 * Wire to real backend: POST /api/auth/2fa with { code | backup_code }.
 */

const MAX_ATTEMPTS = 5;

export default function TwoFactorPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const nextUrl = params.get('next') || '/';
  const setAuth = useAuthStore((s) => s.setAuth);

  const [mode, setMode] = useState<'totp' | 'backup'>('totp');
  const [code, setCode] = useState('');
  const [backup, setBackup] = useState('');
  const [err, setErr] = useState('');
  const [attempts, setAttempts] = useState(0);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const totpRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (mode === 'totp') setTimeout(() => totpRef.current?.focus(), 40);
  }, [mode]);

  // Auto-submit on 6 digits (TOTP) — matches spec UX.
  useEffect(() => {
    if (mode === 'totp' && code.length === 6 && !loading && !lockedUntil) {
      void submit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const remaining = lockedUntil ? Math.max(0, Math.ceil((lockedUntil - Date.now()) / 1000)) : 0;

  async function submit() {
    setLoading(true);
    setErr('');
    // Mock backend check — real impl: POST /api/auth/2fa
    await new Promise((r) => setTimeout(r, 350));
    const input = mode === 'totp' ? code : backup;
    const ok = input === '123456' || input === 'BACKUP01';
    setLoading(false);

    if (ok) {
      setAuth('mock-token-' + Date.now(), { username: 'admin', role: 'admin' });
      navigate(nextUrl, { replace: true });
      return;
    }

    const nextAttempts = attempts + 1;
    setAttempts(nextAttempts);
    setErr('Invalid code. Try again.');
    if (nextAttempts >= MAX_ATTEMPTS) {
      setLockedUntil(Date.now() + 15 * 60 * 1000);
      setErr('Too many attempts. Locked for 15 minutes.');
    }
    setCode('');
    setBackup('');
  }

  const locked = !!lockedUntil && remaining > 0;

  return (
    <div style={{
      minHeight: '100vh',
      background: 'radial-gradient(ellipse at top, var(--surface-2) 0%, var(--surface-1) 55%, var(--surface-0) 100%)',
      display: 'grid', placeItems: 'center', padding: 20,
    }}>
      <div style={{ width: '100%', maxWidth: 440 }}>
        <div style={{ textAlign: 'center', marginBottom: 18 }}>
          <motion.div
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 280, damping: 20 }}
            style={{
              width: 56, height: 56, borderRadius: '50%',
              display: 'grid', placeItems: 'center',
              background: 'color-mix(in srgb, var(--accent) 14%, transparent)',
              color: 'var(--accent-2)',
              margin: '0 auto 12px',
              boxShadow: '0 0 0 8px color-mix(in srgb, var(--accent) 10%, transparent)',
            }}
          >
            <ShieldCheck size={24} />
          </motion.div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.02em' }}>Two-factor authentication</h1>
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '6px 0 0' }}>
            {mode === 'totp'
              ? 'Enter the 6-digit code from your authenticator app.'
              : 'Enter one of your 8-character backup codes.'}
          </p>
        </div>

        <BentoCard>
          <div style={{ padding: 24 }}>
            <AnimatePresence mode="wait">
              {mode === 'totp' ? (
                <motion.div
                  key="totp"
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 6 }}
                  transition={{ duration: 0.18 }}
                >
                  <label style={fieldLabel}>TOTP code</label>
                  <input
                    ref={totpRef}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={code}
                    disabled={locked || loading}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="• • •   • • •"
                    style={{ ...input, fontSize: 24, letterSpacing: '0.5em', textAlign: 'center', fontFamily: 'ui-monospace, monospace' }}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="backup"
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 6 }}
                  transition={{ duration: 0.18 }}
                >
                  <label style={fieldLabel}>Backup code</label>
                  <input
                    autoComplete="one-time-code"
                    value={backup}
                    disabled={locked || loading}
                    onChange={(e) => setBackup(e.target.value.toUpperCase().slice(0, 8))}
                    placeholder="XXXX-XXXX"
                    style={{ ...input, textTransform: 'uppercase', fontFamily: 'ui-monospace, monospace', letterSpacing: '0.2em', textAlign: 'center' }}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {err && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                style={errBox}
              >
                <AlertTriangle size={14} /> {err}
              </motion.div>
            )}

            {mode === 'backup' && (
              <button onClick={submit} disabled={locked || loading || backup.length < 8} style={{ ...btnPrimary, width: '100%', marginTop: 14, justifyContent: 'center' }}>
                {loading ? 'Verifying…' : 'Verify'}
              </button>
            )}

            <button
              type="button"
              onClick={() => { setMode(mode === 'totp' ? 'backup' : 'totp'); setErr(''); }}
              style={{ ...linkBtn, marginTop: 14 }}
            >
              <KeyRound size={12} />
              {mode === 'totp' ? 'Use backup code instead' : 'Back to authenticator'}
            </button>
          </div>
        </BentoCard>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14, fontSize: 11, color: 'var(--fg-muted)' }}>
          <button onClick={() => navigate('/login')} style={{ ...linkBtn, fontSize: 11 }}>
            <ArrowLeft size={12} /> Back to login
          </button>
          <span>Attempts: {attempts} / {MAX_ATTEMPTS}{locked && ` · Locked ${remaining}s`}</span>
        </div>
      </div>
    </div>
  );
}

/* ─── styles ─────────────────────────────────────────────────────────── */
const fieldLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
  textTransform: 'uppercase', color: 'var(--fg-muted)',
  display: 'block', marginBottom: 8,
};
const input: React.CSSProperties = {
  width: '100%', padding: '14px 12px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', outline: 'none',
};
const errBox: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6,
  marginTop: 12, padding: '8px 12px', borderRadius: 'var(--r-sm)',
  background: 'var(--bear-soft)', color: 'var(--bear)',
  border: '1px solid color-mix(in srgb, var(--bear) 30%, transparent)',
  fontSize: 12,
};
const btnPrimary: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '10px 16px', borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
  boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
};
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  background: 'transparent', border: 'none', padding: 0,
  color: 'var(--accent-2)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
};
