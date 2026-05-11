import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity, Lock, User, AlertCircle,
  TrendingUp, Shield, Zap, Eye, EyeOff, BarChart3, ArrowLeft,
  Mail, Phone, UserPlus,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { api } from '../lib/api-client';
import { useAuthStore } from '../stores/auth-store';
import { useThemeStore } from '../stores/theme-store';
import LohiAvatar from '../components/onboarding/LohiAvatar';
import '../styles/onboarding.css';

type Step = 'credentials' | 'totp' | 'register';

/* ── Animated loading spinner (modern pulse-ring) ───────────────────── */
function LoadingSpinner({ size = 20, color = '#3b82f6' }: { size?: number; color?: string }) {
  return (
    <div style={{ width: size, height: size, position: 'relative' }}>
      <motion.div
        style={{
          position: 'absolute', inset: 0, borderRadius: '50%',
          border: `2px solid ${color}33`,
        }}
      />
      <motion.div
        style={{
          position: 'absolute', inset: 0, borderRadius: '50%',
          border: `2px solid transparent`, borderTopColor: color,
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
      />
    </div>
  );
}

/* ── Full-screen loading overlay with modern animation ──────────────── */
function AuthLoadingOverlay({ message }: { message: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(12px)',
      }}
    >
      <div style={{ position: 'relative', width: 64, height: 64, marginBottom: 24 }}>
        <motion.div
          style={{
            position: 'absolute', inset: 0, borderRadius: '50%',
            border: '3px solid rgba(59,130,246,0.15)',
          }}
        />
        <motion.div
          style={{
            position: 'absolute', inset: 0, borderRadius: '50%',
            border: '3px solid transparent', borderTopColor: '#3b82f6', borderRightColor: '#3b82f6',
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
        />
        <motion.div
          style={{
            position: 'absolute', inset: 12, borderRadius: '50%',
            background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
          }}
          animate={{ scale: [1, 1.15, 1], opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
        />
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Activity size={18} color="white" />
        </div>
      </div>
      <motion.p
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0', letterSpacing: '0.02em' }}
      >
        {message}
      </motion.p>
      <motion.div
        style={{ marginTop: 12, height: 3, width: 120, borderRadius: 2, background: 'rgba(59,130,246,0.15)', overflow: 'hidden' }}
      >
        <motion.div
          style={{ height: '100%', borderRadius: 2, background: 'linear-gradient(90deg, #3b82f6, #6366f1)' }}
          animate={{ x: ['-100%', '100%'] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
        />
      </motion.div>
    </motion.div>
  );
}

/* ── Scrolling ticker strip ─────────────────────────────────────────── */
const TICKERS = [
  { symbol: 'RELIANCE', price: 1398.45, change: +1.23 },
  { symbol: 'TCS', price: 2430.10, change: -0.45 },
  { symbol: 'HDFCBANK', price: 1652.80, change: +0.87 },
  { symbol: 'INFY', price: 1485.25, change: +2.14 },
  { symbol: 'ICICIBANK', price: 1124.60, change: -0.32 },
  { symbol: 'HINDUNILVR', price: 2345.90, change: +0.56 },
  { symbol: 'SBIN', price: 628.35, change: +1.78 },
  { symbol: 'BHARTIARTL', price: 1567.20, change: -0.91 },
];

function TickerStrip({ isLight }: { isLight: boolean }) {
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setOffset((o) => o - 0.5), 30);
    return () => clearInterval(id);
  }, []);
  const doubled = [...TICKERS, ...TICKERS];
  return (
    <div style={{
      position: 'absolute', top: 0, left: 0, right: 0, height: 36, overflow: 'hidden',
      borderBottom: isLight ? '1px solid #e2e8f0' : '1px solid rgba(30,41,59,0.8)',
      zIndex: 20,
      background: isLight ? 'rgba(255,255,255,0.92)' : 'rgba(2,6,23,0.9)',
      backdropFilter: 'blur(8px)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', height: '100%', whiteSpace: 'nowrap',
        transform: `translateX(${offset}px)`,
      }}>
        {doubled.map((t, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 20px' }}>
            <span style={{ fontSize: 10, fontFamily: 'monospace', color: isLight ? '#64748b' : '#64748b', fontWeight: 600 }}>
              {t.symbol}
            </span>
            <span style={{ fontSize: 10, fontFamily: 'monospace', color: isLight ? '#334155' : '#cbd5e1' }}>
              ₹{t.price.toLocaleString()}
            </span>
            <span style={{
              fontSize: 10, fontFamily: 'monospace', fontWeight: 700,
              color: t.change >= 0 ? '#10b981' : '#ef4444',
            }}>
              {t.change >= 0 ? '+' : ''}{t.change}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Mini candlestick chart ─────────────────────────────────────────── */
function MiniChart() {
  const bars = useMemo(() => {
    const data = [];
    let price = 100;
    for (let i = 0; i < 50; i++) {
      const open = price;
      price += (Math.random() - 0.47) * 3.5;
      const close = price;
      const high = Math.max(open, close) + Math.random() * 1.5;
      const low = Math.min(open, close) - Math.random() * 1.5;
      data.push({ open, close, high, low, bullish: close >= open });
    }
    return data;
  }, []);
  const allP = bars.flatMap((b) => [b.high, b.low]);
  const min = Math.min(...allP), max = Math.max(...allP), range = max - min || 1;
  const h = 140;
  const toY = (v: number) => h - ((v - min) / range) * h;
  return (
    <svg viewBox={`0 0 ${bars.length * 7} ${h}`} style={{ width: '100%', height: '100%' }} preserveAspectRatio="none">
      {bars.map((b, i) => {
        const x = i * 7 + 3.5;
        const bodyTop = toY(Math.max(b.open, b.close));
        const bodyBot = toY(Math.min(b.open, b.close));
        return (
          <g key={i}>
            <line x1={x} y1={toY(b.high)} x2={x} y2={toY(b.low)}
              stroke={b.bullish ? '#10b981' : '#ef4444'} strokeWidth={0.7} opacity={0.6} />
            <rect x={x - 2} y={bodyTop} width={4}
              height={Math.max(bodyBot - bodyTop, 0.8)}
              fill={b.bullish ? '#10b981' : '#ef4444'} opacity={0.5} rx={0.4} />
          </g>
        );
      })}
    </svg>
  );
}

/* ── Feature pill ───────────────────────────────────────────────────── */
function FeaturePill({ icon: Icon, label, color, isLight }: { icon: any; label: string; color: string; isLight: boolean }) {
  const colors: Record<string, { bg: string; bgL: string; border: string; borderL: string; text: string; textL: string }> = {
    blue:   { bg: 'rgba(59,130,246,0.08)',  bgL: 'rgba(59,130,246,0.06)',  border: 'rgba(59,130,246,0.25)',  borderL: 'rgba(59,130,246,0.2)',  text: '#60a5fa', textL: '#2563eb' },
    green:  { bg: 'rgba(16,185,129,0.08)',  bgL: 'rgba(16,185,129,0.06)',  border: 'rgba(16,185,129,0.25)',  borderL: 'rgba(16,185,129,0.2)',  text: '#34d399', textL: '#059669' },
    amber:  { bg: 'rgba(245,158,11,0.08)',  bgL: 'rgba(245,158,11,0.06)',  border: 'rgba(245,158,11,0.25)',  borderL: 'rgba(245,158,11,0.2)',  text: '#fbbf24', textL: '#d97706' },
    purple: { bg: 'rgba(168,85,247,0.08)',  bgL: 'rgba(168,85,247,0.06)',  border: 'rgba(168,85,247,0.25)',  borderL: 'rgba(168,85,247,0.2)',  text: '#c084fc', textL: '#7c3aed' },
  };
  const c = colors[color] || colors.blue;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderRadius: 12,
      border: `1px solid ${isLight ? c.borderL : c.border}`,
      background: isLight ? c.bgL : c.bg,
    }}>
      <Icon size={15} style={{ color: isLight ? c.textL : c.text }} />
      <span style={{ fontSize: 12, fontWeight: 600, color: isLight ? c.textL : c.text }}>{label}</span>
    </div>
  );
}

/* ── OTP Input (individual boxes like Groww) ─────────────────────────── */
function OTPInput({ value, onChange, length = 6, isLight }: {
  value: string; onChange: (v: string) => void; length?: number; isLight: boolean;
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.padEnd(length, '').split('').slice(0, length);

  const handleChange = (idx: number, char: string) => {
    const d = char.replace(/\D/g, '');
    if (!d && char !== '') return;
    const arr = [...digits];
    arr[idx] = d;
    const newVal = arr.join('').replace(/ /g, '');
    onChange(newVal);
    if (d && idx < length - 1) refs.current[idx + 1]?.focus();
  };

  const handleKeyDown = (idx: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !digits[idx]?.trim() && idx > 0) {
      refs.current[idx - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, length);
    onChange(pasted);
    const focusIdx = Math.min(pasted.length, length - 1);
    refs.current[focusIdx]?.focus();
  };

  return (
    <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
      {digits.map((d, i) => (
        <motion.input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          type="text"
          inputMode="numeric"
          maxLength={1}
          value={d?.trim() || ''}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          autoFocus={i === 0}
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: i * 0.05 }}
          style={{
            width: 48, height: 56, textAlign: 'center', fontSize: 22,
            fontFamily: 'ui-monospace, monospace', fontWeight: 700,
            borderRadius: 12,
            border: d?.trim()
              ? (isLight ? '2px solid #3b82f6' : '2px solid #60a5fa')
              : (isLight ? '1.5px solid #cbd5e1' : '1.5px solid #334155'),
            background: isLight ? '#f8fafc' : '#0f172a',
            color: isLight ? '#1e293b' : '#f1f5f9',
            outline: 'none',
            transition: 'border-color 0.2s, box-shadow 0.2s',
            boxShadow: d?.trim()
              ? '0 0 0 3px rgba(59,130,246,0.1)'
              : 'none',
          }}
          onFocus={(e) => {
            e.target.style.borderColor = isLight ? '#3b82f6' : '#60a5fa';
            e.target.style.boxShadow = '0 0 0 3px rgba(59,130,246,0.15)';
          }}
          onBlur={(e) => {
            if (!d?.trim()) {
              e.target.style.borderColor = isLight ? '#cbd5e1' : '#334155';
              e.target.style.boxShadow = 'none';
            }
          }}
        />
      ))}
    </div>
  );
}

/* ── TOTP Timer Ring ─────────────────────────────────────────────────── */
function TOTPTimer({ isLight }: { isLight: boolean }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const now = Math.floor(Date.now() / 1000);
    setSeconds(30 - (now % 30));
    const id = setInterval(() => {
      const n = Math.floor(Date.now() / 1000);
      setSeconds(30 - (n % 30));
    }, 1000);
    return () => clearInterval(id);
  }, []);
  const pct = seconds / 30;
  const r = 16, c = 2 * Math.PI * r;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <svg width={40} height={40} viewBox="0 0 40 40">
        <circle cx={20} cy={20} r={r} fill="none"
          stroke={isLight ? '#e2e8f0' : '#1e293b'} strokeWidth={3} />
        <circle cx={20} cy={20} r={r} fill="none"
          stroke={seconds <= 5 ? '#ef4444' : (isLight ? '#3b82f6' : '#60a5fa')}
          strokeWidth={3} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
          transform="rotate(-90 20 20)"
          style={{ transition: 'stroke-dashoffset 1s linear, stroke 0.3s' }} />
        <text x={20} y={21} textAnchor="middle" dominantBaseline="middle"
          style={{
            fontSize: 11, fontWeight: 700, fontFamily: 'ui-monospace, monospace',
            fill: seconds <= 5 ? '#ef4444' : (isLight ? '#334155' : '#94a3b8'),
          }}>
          {seconds}
        </text>
      </svg>
      <span style={{ fontSize: 11, color: isLight ? '#64748b' : '#475569', fontWeight: 500 }}>
        Code refreshes in {seconds}s
      </span>
    </div>
  );
}

/* ── Google SVG Icon ─────────────────────────────────────────────────── */
function GoogleIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  );
}

/* ── Apple SVG Icon ──────────────────────────────────────────────────── */
function AppleIcon({ size = 20, color = 'currentColor' }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
      <path d="M17.05 20.28c-.98.95-2.05.88-3.08.4-1.09-.5-2.08-.48-3.24 0-1.44.62-2.2.44-3.06-.4C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"/>
    </svg>
  );
}

/* ── Main Login Page ────────────────────────────────────────────────── */
export default function LoginPage() {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const theme = useThemeStore((s) => s.theme);
  const isLight = theme === 'light';

  const [step, setStep] = useState<Step>('credentials');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Registration fields
  const [regName, setRegName] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirmPassword, setRegConfirmPassword] = useState('');
  const [regPhone, setRegPhone] = useState('');
  const [showRegPassword, setShowRegPassword] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.login({ username, password });
      if (res.totpRequired) {
        setStep('totp');
      } else {
        setAuth(res.token, res.user);
        navigate('/', { replace: true });
      }
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Invalid credentials');
    } finally {
      setLoading(false);
    }
  };

  const handleTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.verifyTotp({ username, code: totpCode });
      setAuth(res.token, res.user);
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Invalid TOTP code');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    setError('');
    setLoading(true);
    try {
      // In production, this would use Google Identity Services to get an id_token.
      // For now, trigger the backend endpoint with a placeholder flow.
      const mockIdToken = 'google-id-token-placeholder';
      const res = await api.loginGoogle({ id_token: mockIdToken });
      setAuth(res.access_token, { username: 'google-user', role: 'TRADER' });
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Google login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleAppleLogin = async () => {
    setError('');
    setLoading(true);
    try {
      // In production, this would use Apple Sign-In JS to get an auth_code.
      const mockAuthCode = 'apple-auth-code-placeholder';
      const res = await api.loginApple({ auth_code: mockAuthCode });
      setAuth(res.access_token, { username: 'apple-user', role: 'TRADER' });
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Apple login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (regPassword !== regConfirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (regPassword.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    if (!/^\d{10}$/.test(regPhone)) {
      setError('Enter a valid 10-digit Indian mobile number');
      return;
    }
    setLoading(true);
    try {
      await api.registerEmail({
        email: regEmail,
        password: regPassword,
        phone: regPhone,
        name: regName,
      });
      // After registration, auto-login
      const loginRes = await api.loginEmailV2(regEmail, regPassword);
      setAuth(loginRes.access_token, { username: regEmail, role: 'TRADER' });
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  // Auto-submit when 6 digits entered
  useEffect(() => {
    if (step === 'totp' && totpCode.length === 6 && !loading) {
      handleTotp({ preventDefault: () => {} } as React.FormEvent);
    }
  }, [totpCode]);

  // Theme-aware colors
  const bg = isLight
    ? 'radial-gradient(ellipse at top, #ffffff 0%, #f1f5f9 55%, #e2e8f0 100%)'
    : 'radial-gradient(ellipse at top, #0f1012 0%, #0a0a0b 55%, #000000 100%)';
  const cardBg = isLight ? '#ffffff' : 'var(--surface-2)';
  const cardBorder = isLight ? '#e2e8f0' : 'var(--line-2)';
  const textPrimary = isLight ? '#0f172a' : 'var(--fg-primary)';
  const textSecondary = isLight ? '#475569' : 'var(--fg-secondary)';
  const textMuted = isLight ? '#64748b' : 'var(--fg-muted)';
  const inputBg = isLight ? '#f8fafc' : 'var(--surface-3)';
  const inputBorder = isLight ? '#cbd5e1' : 'var(--line-2)';
  const inputFocusBorder = 'var(--accent)';

  const inputStyle: React.CSSProperties = {
    width: '100%', borderRadius: 12, paddingLeft: 44, paddingRight: 16,
    paddingTop: 14, paddingBottom: 14, fontSize: 14, outline: 'none',
    background: inputBg, border: `1.5px solid ${inputBorder}`,
    color: textPrimary, transition: 'border-color 0.2s, box-shadow 0.2s',
    colorScheme: isLight ? 'light' : 'dark',
  };

  const inputStylePassword: React.CSSProperties = { ...inputStyle, paddingRight: 44 };

  const labelStyle: React.CSSProperties = {
    display: 'block', fontSize: 13, color: textSecondary,
    marginBottom: 8, fontWeight: 600,
  };

  const handleInputFocus = (e: React.FocusEvent<HTMLInputElement>) => {
    e.target.style.borderColor = inputFocusBorder;
    e.target.style.boxShadow = '0 0 0 3px rgba(59,130,246,0.1)';
  };
  const handleInputBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    e.target.style.borderColor = inputBorder;
    e.target.style.boxShadow = 'none';
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', position: 'relative', overflow: 'hidden',
      background: bg,
      fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      color: textPrimary,
    }}>
      {/* Grid background */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: isLight
          ? 'linear-gradient(rgba(59,130,246,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.03) 1px, transparent 1px)'
          : 'linear-gradient(rgba(59,130,246,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.04) 1px, transparent 1px)',
        backgroundSize: '48px 48px',
      }} />

      {/* Glow orbs */}
      <div style={{
        position: 'absolute', top: -200, left: -200, width: 600, height: 600, borderRadius: '50%',
        background: isLight
          ? 'radial-gradient(circle, rgba(59,130,246,0.06) 0%, transparent 70%)'
          : 'radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', bottom: -200, right: -200, width: 600, height: 600, borderRadius: '50%',
        background: isLight
          ? 'radial-gradient(circle, rgba(16,185,129,0.04) 0%, transparent 70%)'
          : 'radial-gradient(circle, rgba(16,185,129,0.06) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />

      <TickerStrip isLight={isLight} />

      {/* Loading overlay */}
      <AnimatePresence>
        {loading && (
          <AuthLoadingOverlay message={
            step === 'credentials' ? 'Authenticating...'
            : step === 'totp' ? 'Verifying code...'
            : 'Creating account...'
          } />
        )}
      </AnimatePresence>

      {/* ── Left panel (desktop) ──────────────────────────────────────── */}
      <div id="login-left-panel" style={{
        display: 'none', position: 'relative', zIndex: 10,
        flexDirection: 'column', justifyContent: 'space-between',
        padding: '96px 64px 48px', width: '52%',
        overflow: 'hidden',
      }}>
        {/* Ambient aurora orbs that drift behind Lohi */}
        <motion.div
          aria-hidden
          animate={{ x: [0, 30, 0], y: [0, -20, 0] }}
          transition={{ duration: 14, repeat: Infinity, ease: 'easeInOut' }}
          style={{
            position: 'absolute', top: '-10%', left: '-20%',
            width: 560, height: 560, borderRadius: '50%',
            background: isLight
              ? 'radial-gradient(circle, rgba(0,214,127,0.10) 0%, transparent 70%)'
              : 'radial-gradient(circle, rgba(0,214,127,0.22) 0%, transparent 70%)',
            filter: 'blur(50px)', pointerEvents: 'none',
          }}
        />
        <motion.div
          aria-hidden
          animate={{ x: [0, -40, 0], y: [0, 30, 0] }}
          transition={{ duration: 18, repeat: Infinity, ease: 'easeInOut' }}
          style={{
            position: 'absolute', bottom: '-20%', right: '-10%',
            width: 520, height: 520, borderRadius: '50%',
            background: isLight
              ? 'radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)'
              : 'radial-gradient(circle, rgba(59,130,246,0.18) 0%, transparent 70%)',
            filter: 'blur(60px)', pointerEvents: 'none',
          }}
        />

        <motion.div
          initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }}
          style={{ position: 'relative' }}
        >
          {/* Brand lockup */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 44 }}>
            <div style={{
              width: 48, height: 48, borderRadius: 14,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              boxShadow: '0 8px 28px rgba(37,99,235,0.4)',
            }}>
              <Activity color="white" size={24} />
            </div>
            <div>
              <h1 style={{
                fontSize: 30, fontWeight: 900, letterSpacing: '-0.025em', lineHeight: 1, margin: 0,
                background: isLight
                  ? 'linear-gradient(135deg, #2563eb, #059669)'
                  : 'linear-gradient(135deg, #60a5fa, #34d399)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>
                LOHI-TRADE
              </h1>
              <p style={{
                fontSize: 10, color: textMuted, letterSpacing: '0.3em',
                textTransform: 'uppercase', fontWeight: 600, marginTop: 4,
              }}>
                Algorithmic Trading System
              </p>
            </div>
          </div>

          {/* Lohi hero block — centered avatar with orbiting rings + chart pulses */}
          <div style={{
            position: 'relative', width: '100%', maxWidth: 520,
            margin: '0 auto 40px', textAlign: 'center',
          }}>
            {/* Outer expanding ring pulses */}
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                aria-hidden
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{ opacity: [0.35, 0, 0], scale: [0.6, 1.4, 1.4] }}
                transition={{
                  duration: 4, repeat: Infinity, ease: 'easeOut',
                  delay: i * 1.3,
                }}
                style={{
                  position: 'absolute', top: '50%', left: '50%',
                  width: 280, height: 280, marginLeft: -140, marginTop: -140,
                  borderRadius: '50%',
                  border: `1.5px solid ${isLight ? 'rgba(0,143,87,0.45)' : 'rgba(0,214,127,0.45)'}`,
                  pointerEvents: 'none',
                }}
              />
            ))}

            {/* Orbiting satellite dots — trading metaphor */}
            <motion.div
              aria-hidden
              animate={{ rotate: 360 }}
              transition={{ duration: 22, repeat: Infinity, ease: 'linear' }}
              style={{
                position: 'absolute', top: '50%', left: '50%',
                width: 240, height: 240, marginLeft: -120, marginTop: -120,
                borderRadius: '50%',
                border: `1px dashed ${isLight ? 'rgba(15,23,42,0.12)' : 'rgba(226,232,240,0.14)'}`,
                pointerEvents: 'none',
              }}
            >
              <span style={{
                position: 'absolute', top: -5, left: '50%', marginLeft: -5,
                width: 10, height: 10, borderRadius: '50%',
                background: '#60a5fa',
                boxShadow: '0 0 12px rgba(96,165,250,0.7)',
              }} />
            </motion.div>
            <motion.div
              aria-hidden
              animate={{ rotate: -360 }}
              transition={{ duration: 28, repeat: Infinity, ease: 'linear' }}
              style={{
                position: 'absolute', top: '50%', left: '50%',
                width: 180, height: 180, marginLeft: -90, marginTop: -90,
                pointerEvents: 'none',
              }}
            >
              <span style={{
                position: 'absolute', top: -4, left: '50%', marginLeft: -4,
                width: 8, height: 8, borderRadius: '50%',
                background: isLight ? '#008f57' : '#00d67f',
                boxShadow: isLight
                  ? '0 0 10px rgba(0,143,87,0.6)'
                  : '0 0 10px rgba(0,214,127,0.7)',
              }} />
            </motion.div>

            {/* The hero avatar */}
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.8, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
              style={{ position: 'relative', display: 'inline-block', padding: 24 }}
            >
              <LohiAvatar size="lg" speaking />
            </motion.div>

            {/* Greeting */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.5 }}
              style={{ marginTop: 22 }}
            >
              <p style={{
                fontSize: 10, fontWeight: 800, letterSpacing: '0.22em',
                textTransform: 'uppercase',
                color: isLight ? '#008f57' : '#00d67f',
                margin: 0,
              }}>
                I am Lohi · Your Personal Quant
              </p>
              <p style={{
                fontSize: 22, fontWeight: 700, color: textPrimary,
                margin: '10px 0 0', letterSpacing: '-0.02em', lineHeight: 1.35,
                fontStyle: 'italic',
              }}>
                &ldquo;Welcome back. The market&apos;s been busy &mdash; let&apos;s get you caught up.&rdquo;
              </p>
            </motion.div>
          </div>

          {/* Feature pills */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'center' }}>
            <FeaturePill icon={TrendingUp} label="3 Strategies" color="blue" isLight={isLight} />
            <FeaturePill icon={Shield} label="RMS Protected" color="green" isLight={isLight} />
            <FeaturePill icon={Zap} label="Real-Time" color="amber" isLight={isLight} />
            <FeaturePill icon={BarChart3} label="NSE Intraday" color="purple" isLight={isLight} />
          </div>
        </motion.div>

        {/* Decorative muted chart at the bottom */}
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          transition={{ duration: 1.2, delay: 0.4 }}
          style={{ height: 120, marginTop: 'auto', opacity: 0.25, position: 'relative' }}
        >
          <MiniChart />
        </motion.div>
      </div>

      {/* ── Right panel (login form) ──────────────────────────────────── */}
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        position: 'relative', zIndex: 10, padding: '56px 20px 32px',
      }}>
        <motion.div
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15 }}
          style={{ width: '100%', maxWidth: 420 }}
        >
          {/* Mobile logo */}
          <div id="login-mobile-logo" style={{ textAlign: 'center', marginBottom: 32 }}>
            <motion.div
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              style={{ display: 'inline-block', marginBottom: 14 }}
            >
              <LohiAvatar size="md" speaking />
            </motion.div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center', marginBottom: 6 }}>
              <span style={{
                fontSize: 24, fontWeight: 900, letterSpacing: '-0.02em',
                background: isLight
                  ? 'linear-gradient(135deg, #2563eb, #059669)'
                  : 'linear-gradient(135deg, #60a5fa, #34d399)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>
                LOHI-TRADE
              </span>
            </div>
            <p style={{ fontSize: 10, color: textMuted, letterSpacing: '0.25em', textTransform: 'uppercase', fontWeight: 600 }}>
              Algorithmic Trading System
            </p>
          </div>

          {/* ── Card ─────────────────────────────────────────────────── */}
          <div style={{
            borderRadius: 20, padding: 36,
            border: `1px solid ${cardBorder}`,
            background: cardBg,
            boxShadow: isLight
              ? '0 25px 60px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.06)'
              : '0 25px 60px rgba(0,0,0,0.5), inset 0 1px 0 rgba(148,163,184,0.05)',
          }}>
            <AnimatePresence mode="wait">
              {step === 'credentials' ? (
                <motion.div
                  key="cred-form"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.25 }}
                >
                  {/* Header */}
                  <div style={{ marginBottom: 24 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
                      <div style={{
                        width: 44, height: 44, borderRadius: 14,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        border: isLight ? '1.5px solid rgba(59,130,246,0.2)' : '1px solid rgba(59,130,246,0.25)',
                        background: isLight ? 'rgba(59,130,246,0.06)' : 'rgba(59,130,246,0.1)',
                      }}>
                        <Lock size={18} color={isLight ? '#2563eb' : '#60a5fa'} />
                      </div>
                      <div>
                        <h2 style={{ fontSize: 20, fontWeight: 800, color: textPrimary, margin: 0, letterSpacing: '-0.01em' }}>
                          Welcome back
                        </h2>
                        <p style={{ fontSize: 13, color: textMuted, marginTop: 2 }}>
                          Sign in to your trading terminal
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* ── Social Login Buttons (prominently placed) ──── */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
                    <motion.button
                      type="button"
                      onClick={handleGoogleLogin}
                      disabled={loading}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 10, padding: '13px 0', borderRadius: 12, fontSize: 14, fontWeight: 600,
                        color: isLight ? '#1e293b' : '#f1f5f9',
                        border: isLight ? '1.5px solid #e2e8f0' : '1.5px solid #334155',
                        background: isLight ? '#ffffff' : '#1e293b',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        opacity: loading ? 0.5 : 1,
                        transition: 'border-color 0.2s, background 0.2s',
                      }}
                    >
                      <GoogleIcon size={18} />
                      <span>Continue with Google</span>
                    </motion.button>

                    <motion.button
                      type="button"
                      onClick={handleAppleLogin}
                      disabled={loading}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 10, padding: '13px 0', borderRadius: 12, fontSize: 14, fontWeight: 600,
                        color: isLight ? '#ffffff' : '#ffffff',
                        border: 'none',
                        background: isLight ? '#000000' : '#000000',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        opacity: loading ? 0.5 : 1,
                        transition: 'opacity 0.2s',
                      }}
                    >
                      <AppleIcon size={18} color="#ffffff" />
                      <span>Continue with Apple</span>
                    </motion.button>
                  </div>

                  {/* ── Divider ──────────────────────────────────────── */}
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20,
                  }}>
                    <div style={{ flex: 1, height: 1, background: isLight ? '#e2e8f0' : '#334155' }} />
                    <span style={{ fontSize: 12, color: textMuted, fontWeight: 500 }}>or</span>
                    <div style={{ flex: 1, height: 1, background: isLight ? '#e2e8f0' : '#334155' }} />
                  </div>

                  {/* Error */}
                  <AnimatePresence>
                    {error && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto', marginBottom: 20 }}
                        exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                        style={{ overflow: 'hidden' }}
                      >
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px',
                          borderRadius: 12,
                          border: isLight ? '1px solid rgba(239,68,68,0.2)' : '1px solid rgba(239,68,68,0.2)',
                          background: isLight ? 'rgba(239,68,68,0.06)' : 'rgba(239,68,68,0.08)',
                        }}>
                          <AlertCircle size={14} color="#ef4444" style={{ flexShrink: 0 }} />
                          <span style={{ fontSize: 13, color: isLight ? '#dc2626' : '#fca5a5' }}>{error}</span>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Form */}
                  <form onSubmit={handleLogin}>
                    <div style={{ marginBottom: 20 }}>
                      <label style={labelStyle}>Username</label>
                      <div style={{ position: 'relative' }}>
                        <User size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type="text" value={username}
                          onChange={(e) => setUsername(e.target.value)}
                          style={inputStyle} placeholder="Enter username"
                          autoFocus required autoComplete="username"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: 28 }}>
                      <label style={labelStyle}>Password</label>
                      <div style={{ position: 'relative' }}>
                        <Lock size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type={showPassword ? 'text' : 'password'} value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          style={inputStylePassword} placeholder="Enter password"
                          required autoComplete="current-password"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                        <button type="button" onClick={() => setShowPassword(!showPassword)}
                          style={{
                            position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
                            background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: textMuted,
                          }}
                          tabIndex={-1} aria-label={showPassword ? 'Hide password' : 'Show password'}>
                          {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>

                    <motion.button
                      type="submit"
                      disabled={loading || !username || !password}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 8, padding: '14px 0', borderRadius: 12, fontSize: 15, fontWeight: 700,
                        color: 'white', border: 'none',
                        cursor: loading || !username || !password ? 'not-allowed' : 'pointer',
                        opacity: loading || !username || !password ? 0.5 : 1,
                        background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
                        boxShadow: '0 4px 20px rgba(37,99,235,0.3)',
                        transition: 'opacity 0.2s',
                      }}
                    >
                      {loading ? <LoadingSpinner size={18} color="white" /> : <Lock size={15} />}
                      <span>{loading ? 'Signing in...' : 'Sign In'}</span>
                    </motion.button>
                  </form>

                  {/* Open Account link */}
                  <div style={{ marginTop: 16, textAlign: 'center' }}>
                    <button
                      type="button"
                      onClick={() => navigate('/create-account')}
                      style={{
                        background: 'none', border: 'none', cursor: 'pointer',
                        fontSize: 13, fontWeight: 600,
                        color: isLight ? '#2563eb' : '#60a5fa',
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                      }}
                    >
                      <UserPlus size={14} />
                      <span>Open a new account</span>
                    </button>
                  </div>
                </motion.div>

              ) : step === 'totp' ? (
                <motion.div
                  key="totp-form"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  transition={{ duration: 0.25 }}
                >
                  {/* Header */}
                  <div style={{ marginBottom: 28 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
                      <div style={{
                        width: 44, height: 44, borderRadius: 14,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        border: isLight ? '1.5px solid rgba(245,158,11,0.2)' : '1px solid rgba(245,158,11,0.25)',
                        background: isLight ? 'rgba(245,158,11,0.06)' : 'rgba(245,158,11,0.1)',
                      }}>
                        <Shield size={18} color={isLight ? '#d97706' : '#fbbf24'} />
                      </div>
                      <div>
                        <h2 style={{ fontSize: 20, fontWeight: 800, color: textPrimary, margin: 0, letterSpacing: '-0.01em' }}>
                          Two-Factor Auth
                        </h2>
                        <p style={{ fontSize: 13, color: textMuted, marginTop: 2 }}>
                          Enter the 6-digit code from your authenticator
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Error */}
                  <AnimatePresence>
                    {error && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto', marginBottom: 20 }}
                        exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                        style={{ overflow: 'hidden' }}
                      >
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px',
                          borderRadius: 12,
                          border: isLight ? '1px solid rgba(239,68,68,0.2)' : '1px solid rgba(239,68,68,0.2)',
                          background: isLight ? 'rgba(239,68,68,0.06)' : 'rgba(239,68,68,0.08)',
                        }}>
                          <AlertCircle size={14} color="#ef4444" style={{ flexShrink: 0 }} />
                          <span style={{ fontSize: 13, color: isLight ? '#dc2626' : '#fca5a5' }}>{error}</span>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* OTP Form */}
                  <form onSubmit={handleTotp}>
                    <div style={{ marginBottom: 20 }}>
                      <OTPInput value={totpCode} onChange={setTotpCode} isLight={isLight} />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 24 }}>
                      <TOTPTimer isLight={isLight} />
                    </div>

                    <motion.button
                      type="submit"
                      disabled={loading || totpCode.length !== 6}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 8, padding: '14px 0', borderRadius: 12, fontSize: 15, fontWeight: 700,
                        color: 'white', border: 'none',
                        cursor: loading || totpCode.length !== 6 ? 'not-allowed' : 'pointer',
                        opacity: loading || totpCode.length !== 6 ? 0.5 : 1,
                        background: 'linear-gradient(135deg, #d97706 0%, #b45309 100%)',
                        boxShadow: '0 4px 20px rgba(217,119,6,0.25)',
                        transition: 'opacity 0.2s',
                      }}
                    >
                      {loading ? <LoadingSpinner size={18} color="white" /> : <Shield size={15} />}
                      <span>{loading ? 'Verifying...' : 'Verify & Continue'}</span>
                    </motion.button>

                    <button
                      type="button"
                      onClick={() => { setStep('credentials'); setError(''); setTotpCode(''); }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 6, fontSize: 13, color: textMuted, background: 'none', border: 'none',
                        cursor: 'pointer', padding: '10px 0', marginTop: 12,
                      }}
                    >
                      <ArrowLeft size={14} />
                      <span>Back to login</span>
                    </button>
                  </form>
                </motion.div>

              ) : (
                <motion.div
                  key="register-form"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  transition={{ duration: 0.25 }}
                >
                  {/* Header */}
                  <div style={{ marginBottom: 24 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
                      <div style={{
                        width: 44, height: 44, borderRadius: 14,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        border: isLight ? '1.5px solid rgba(16,185,129,0.2)' : '1px solid rgba(16,185,129,0.25)',
                        background: isLight ? 'rgba(16,185,129,0.06)' : 'rgba(16,185,129,0.1)',
                      }}>
                        <UserPlus size={18} color={isLight ? '#059669' : '#34d399'} />
                      </div>
                      <div>
                        <h2 style={{ fontSize: 20, fontWeight: 800, color: textPrimary, margin: 0, letterSpacing: '-0.01em' }}>
                          Create Account
                        </h2>
                        <p style={{ fontSize: 13, color: textMuted, marginTop: 2 }}>
                          Sign up with your email
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Social login buttons in register too */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
                    <motion.button
                      type="button"
                      onClick={handleGoogleLogin}
                      disabled={loading}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 10, padding: '13px 0', borderRadius: 12, fontSize: 14, fontWeight: 600,
                        color: isLight ? '#1e293b' : '#f1f5f9',
                        border: isLight ? '1.5px solid #e2e8f0' : '1.5px solid #334155',
                        background: isLight ? '#ffffff' : '#1e293b',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        opacity: loading ? 0.5 : 1,
                        transition: 'border-color 0.2s, background 0.2s',
                      }}
                    >
                      <GoogleIcon size={18} />
                      <span>Continue with Google</span>
                    </motion.button>

                    <motion.button
                      type="button"
                      onClick={handleAppleLogin}
                      disabled={loading}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 10, padding: '13px 0', borderRadius: 12, fontSize: 14, fontWeight: 600,
                        color: '#ffffff', border: 'none', background: '#000000',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        opacity: loading ? 0.5 : 1,
                        transition: 'opacity 0.2s',
                      }}
                    >
                      <AppleIcon size={18} color="#ffffff" />
                      <span>Continue with Apple</span>
                    </motion.button>
                  </div>

                  {/* Divider */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
                    <div style={{ flex: 1, height: 1, background: isLight ? '#e2e8f0' : '#334155' }} />
                    <span style={{ fontSize: 12, color: textMuted, fontWeight: 500 }}>or</span>
                    <div style={{ flex: 1, height: 1, background: isLight ? '#e2e8f0' : '#334155' }} />
                  </div>

                  {/* Error */}
                  <AnimatePresence>
                    {error && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto', marginBottom: 20 }}
                        exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                        style={{ overflow: 'hidden' }}
                      >
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px',
                          borderRadius: 12,
                          border: isLight ? '1px solid rgba(239,68,68,0.2)' : '1px solid rgba(239,68,68,0.2)',
                          background: isLight ? 'rgba(239,68,68,0.06)' : 'rgba(239,68,68,0.08)',
                        }}>
                          <AlertCircle size={14} color="#ef4444" style={{ flexShrink: 0 }} />
                          <span style={{ fontSize: 13, color: isLight ? '#dc2626' : '#fca5a5' }}>{error}</span>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Registration Form */}
                  <form onSubmit={handleRegister}>
                    <div style={{ marginBottom: 16 }}>
                      <label style={labelStyle}>Full Name</label>
                      <div style={{ position: 'relative' }}>
                        <User size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type="text" value={regName}
                          onChange={(e) => setRegName(e.target.value)}
                          style={inputStyle} placeholder="Enter your full name"
                          required autoComplete="name"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <label style={labelStyle}>Email</label>
                      <div style={{ position: 'relative' }}>
                        <Mail size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type="email" value={regEmail}
                          onChange={(e) => setRegEmail(e.target.value)}
                          style={inputStyle} placeholder="Enter your email"
                          required autoComplete="email"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <label style={labelStyle}>Mobile Number</label>
                      <div style={{ position: 'relative' }}>
                        <Phone size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type="tel" value={regPhone}
                          onChange={(e) => setRegPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                          style={inputStyle} placeholder="10-digit mobile number"
                          required inputMode="numeric" autoComplete="tel"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <label style={labelStyle}>Password</label>
                      <div style={{ position: 'relative' }}>
                        <Lock size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type={showRegPassword ? 'text' : 'password'} value={regPassword}
                          onChange={(e) => setRegPassword(e.target.value)}
                          style={inputStylePassword} placeholder="Min 8 characters"
                          required autoComplete="new-password"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                        <button type="button" onClick={() => setShowRegPassword(!showRegPassword)}
                          style={{
                            position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
                            background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: textMuted,
                          }}
                          tabIndex={-1} aria-label={showRegPassword ? 'Hide password' : 'Show password'}>
                          {showRegPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>

                    <div style={{ marginBottom: 24 }}>
                      <label style={labelStyle}>Confirm Password</label>
                      <div style={{ position: 'relative' }}>
                        <Lock size={16} color={textMuted}
                          style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                        <input
                          type={showRegPassword ? 'text' : 'password'} value={regConfirmPassword}
                          onChange={(e) => setRegConfirmPassword(e.target.value)}
                          style={inputStyle} placeholder="Re-enter password"
                          required autoComplete="new-password"
                          onFocus={handleInputFocus}
                          onBlur={handleInputBlur}
                        />
                      </div>
                    </div>

                    <motion.button
                      type="submit"
                      disabled={loading || !regName || !regEmail || !regPassword || !regConfirmPassword || !regPhone}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.98 }}
                      style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        gap: 8, padding: '14px 0', borderRadius: 12, fontSize: 15, fontWeight: 700,
                        color: 'white', border: 'none',
                        cursor: loading || !regName || !regEmail || !regPassword || !regConfirmPassword || !regPhone ? 'not-allowed' : 'pointer',
                        opacity: loading || !regName || !regEmail || !regPassword || !regConfirmPassword || !regPhone ? 0.5 : 1,
                        background: 'linear-gradient(135deg, #059669 0%, #047857 100%)',
                        boxShadow: '0 4px 20px rgba(5,150,105,0.3)',
                        transition: 'opacity 0.2s',
                      }}
                    >
                      {loading ? <LoadingSpinner size={18} color="white" /> : <UserPlus size={15} />}
                      <span>{loading ? 'Creating account...' : 'Create Account'}</span>
                    </motion.button>
                  </form>

                  {/* Back to login */}
                  <button
                    type="button"
                    onClick={() => { setStep('credentials'); setError(''); }}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      gap: 6, fontSize: 13, color: textMuted, background: 'none', border: 'none',
                      cursor: 'pointer', padding: '10px 0', marginTop: 12,
                    }}
                  >
                    <ArrowLeft size={14} />
                    <span>Back to login</span>
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Footer */}
          <div style={{ marginTop: 28, textAlign: 'center' }}>
            <p style={{ fontSize: 11, color: textMuted }}>
              Default:{' '}
              <span style={{ color: textSecondary, fontFamily: 'monospace' }}>admin</span>
              {' / '}
              <span style={{ color: textSecondary, fontFamily: 'monospace' }}>admin123</span>
            </p>
          </div>

          <div style={{
            marginTop: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 6, height: 6, borderRadius: '50%', background: '#10b981',
                animation: 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
              }} />
              <span style={{ fontSize: 10, color: textMuted, fontWeight: 500 }}>Systems Online</span>
            </div>
            <div style={{ width: 1, height: 12, background: isLight ? '#e2e8f0' : '#1e293b' }} />
            <span style={{ fontSize: 10, color: textMuted, fontFamily: 'monospace', fontWeight: 600 }}>NSE</span>
            <div style={{ width: 1, height: 12, background: isLight ? '#e2e8f0' : '#1e293b' }} />
            <a
              href="https://github.com/lohi-trade/lohi-trade-oss"
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 9, fontWeight: 700, letterSpacing: '0.12em',
                padding: '2px 7px', borderRadius: 4,
                background: isLight ? 'rgba(59,130,246,0.1)' : 'rgba(96,165,250,0.12)',
                color: isLight ? '#2563eb' : '#60a5fa',
                textTransform: 'uppercase', textDecoration: 'none',
              }}
            >
              Open Source
            </a>
            <span style={{ fontSize: 10, color: textMuted }}>v1.0.0 · AGPL-3.0</span>
          </div>

          {/* Clear session — rescue link for stale localStorage tokens */}
          <div style={{ marginTop: 12, textAlign: 'center' }}>
            <button
              type="button"
              onClick={() => {
                try {
                  localStorage.removeItem('lohi_auth_token');
                  localStorage.removeItem('lohi_auth_user');
                } catch { /* ignore */ }
                // Reload without any ?next= so we start fresh.
                window.location.replace('/login');
              }}
              style={{
                background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
                fontSize: 11, color: textMuted, textDecoration: 'underline',
                textUnderlineOffset: 3, fontFamily: 'inherit',
              }}
              title="Clears any stale login data stored in this browser. Use this if you keep seeing 'signed out for safety' on every login."
            >
              Having trouble? Clear session data
            </button>
          </div>
        </motion.div>
      </div>

      {/* Keyframes + responsive overrides */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        @media (min-width: 1024px) {
          #login-left-panel { display: flex !important; }
          #login-mobile-logo { display: none !important; }
        }
      `}</style>
    </div>
  );
}
