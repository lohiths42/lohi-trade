import { useState, useEffect, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Activity, Check, ChevronRight, ArrowLeft, ArrowRight,
  CreditCard, Building2, BarChart3, User, FileCheck, Camera,
  AlertCircle, Shield, Phone, Mail, Lock, Eye, EyeOff,
  Loader2, CheckCircle2, XCircle,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { api } from '../lib/api-client';
import { useAuthStore } from '../stores/auth-store';
import { useThemeStore } from '../stores/theme-store';

/* ─── Step definitions ───────────────────────────────────────────────── */
const STEPS = [
  { id: 'signup', label: 'Sign Up', description: 'Create your account with email & phone', icon: User },
  { id: 'pan', label: 'PAN & Aadhaar Verification', description: 'Verify your PAN details for KRA validation', icon: CreditCard },
  { id: 'bank', label: 'Bank Verification', description: 'Link your bank account for fund transfers', icon: Building2 },
  { id: 'segments', label: 'Segment Selection', description: 'Choose trading segments: Equity, F&O, Currency', icon: BarChart3 },
  { id: 'personal', label: 'Personal Details', description: 'Occupation, income, and trading experience', icon: FileCheck },
  { id: 'nominee', label: 'Nominee Details', description: 'Add a nominee for your trading account', icon: Shield },
  { id: 'esign', label: 'Liveliness Check & e-Sign', description: 'Quick selfie verification and digital signature', icon: Camera },
] as const;

type StepId = (typeof STEPS)[number]['id'];

/* ─── Animated loading spinner ───────────────────────────────────────── */
function Spinner({ size = 18 }: { size?: number }) {
  return (
    <motion.div
      style={{ width: size, height: size, borderRadius: '50%', border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff' }}
      animate={{ rotate: 360 }}
      transition={{ duration: 0.7, repeat: Infinity, ease: 'linear' }}
    />
  );
}

/* ─── PAN Card Visual ────────────────────────────────────────────────── */
function PANCardVisual({ pan, dob, isLight }: { pan: string; dob: string; isLight: boolean }) {
  const masked = pan ? pan.replace(/./g, '•').slice(0, -4) + pan.slice(-4) : '••••••••••';
  return (
    <div style={{
      width: '100%', maxWidth: 380, aspectRatio: '1.6/1', borderRadius: 16,
      background: 'linear-gradient(135deg, #1e293b 0%, #334155 50%, #1e293b 100%)',
      border: '1px solid rgba(59,130,246,0.2)',
      padding: '24px 28px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
      position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: -40, right: -40, width: 120, height: 120, borderRadius: '50%', background: 'rgba(59,130,246,0.06)' }} />
      <div style={{ position: 'absolute', bottom: -30, left: -30, width: 100, height: 100, borderRadius: '50%', background: 'rgba(99,102,241,0.05)' }} />
      <div style={{ fontSize: 20, fontFamily: 'ui-monospace, monospace', fontWeight: 700, color: '#e2e8f0', letterSpacing: '0.15em' }}>
        {pan || '••••••••••'}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontSize: 9, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>Name</div>
          <div style={{ fontSize: 13, color: '#94a3b8', fontFamily: 'ui-monospace, monospace' }}>••••••</div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>Date of Birth</div>
          <div style={{ fontSize: 13, color: '#94a3b8', fontFamily: 'ui-monospace, monospace' }}>{dob || '••/••/••'}</div>
        </div>
      </div>
    </div>
  );
}

/* ─── Chatbot bubble ─────────────────────────────────────────────────── */
function ChatBubble({ isLight }: { isLight: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 50 }}>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            style={{
              position: 'absolute', bottom: 60, right: 0, width: 300, padding: 16, borderRadius: 16,
              background: isLight ? '#ffffff' : '#1e293b',
              border: isLight ? '1px solid #e2e8f0' : '1px solid #334155',
              boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
            }}
          >
            <p style={{ fontSize: 13, color: isLight ? '#334155' : '#cbd5e1', lineHeight: 1.5 }}>
              Hi, this is Lohi-TRADE support. How may I help you today?
            </p>
          </motion.div>
        )}
      </AnimatePresence>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: 48, height: 48, borderRadius: '50%', border: 'none', cursor: 'pointer',
          background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
          boxShadow: '0 4px 16px rgba(59,130,246,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white',
        }}
        aria-label="Open chat support"
      >
        <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </button>
    </div>
  );
}

/* ─── Main Create Account Page ───────────────────────────────────────── */
export default function CreateAccountPage() {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const theme = useThemeStore((s) => s.theme);
  const isLight = theme === 'light';

  const [currentStep, setCurrentStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Step 0: Sign Up
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Step 1: PAN
  const [pan, setPan] = useState('');
  const [dob, setDob] = useState('');
  const [panVerified, setPanVerified] = useState(false);

  // Step 2: Bank
  const [accountHolder, setAccountHolder] = useState('');
  const [accountNumber, setAccountNumber] = useState('');
  const [confirmAccountNumber, setConfirmAccountNumber] = useState('');
  const [ifsc, setIfsc] = useState('');
  const [bankName, setBankName] = useState('');
  const [accountType, setAccountType] = useState('savings');

  // Step 3: Segments
  const [segments, setSegments] = useState<Set<string>>(new Set(['equity']));

  // Step 4: Personal
  const [occupation, setOccupation] = useState('');
  const [annualIncome, setAnnualIncome] = useState('');
  const [tradingExperience, setTradingExperience] = useState('');
  const [politicallyExposed, setPoliticallyExposed] = useState(false);

  // Step 5: Nominee
  const [nomineeName, setNomineeName] = useState('');
  const [nomineeRelation, setNomineeRelation] = useState('');
  const [nomineeDob, setNomineeDob] = useState('');
  const [nomineeShare, setNomineeShare] = useState('100');

  // Step 6: e-Sign
  const [selfieComplete, setSelfieComplete] = useState(false);
  const [esignComplete, setEsignComplete] = useState(false);

  // Theme colors
  const bg = isLight ? '#f0f3f8' : 'var(--surface-1)';
  const cardBg = isLight ? '#ffffff' : 'var(--surface-2)';
  const cardBorder = isLight ? '#e2e8f0' : 'var(--line-2)';
  const textPrimary = isLight ? '#0f172a' : 'var(--fg-primary)';
  const textSecondary = isLight ? '#475569' : 'var(--fg-secondary)';
  const textMuted = isLight ? '#64748b' : 'var(--fg-muted)';
  const inputBg = isLight ? '#f8fafc' : 'var(--surface-3)';
  const inputBorder = isLight ? '#cbd5e1' : 'var(--line-2)';

  const inputStyle: React.CSSProperties = {
    width: '100%', borderRadius: 12, padding: '14px 16px', fontSize: 14, outline: 'none',
    background: inputBg, border: `1.5px solid ${inputBorder}`, color: textPrimary,
    transition: 'border-color 0.2s, box-shadow 0.2s',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block', fontSize: 12, color: textSecondary, marginBottom: 6, fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.05em',
  };

  const handleFocus = (e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) => {
    e.target.style.borderColor = '#3b82f6';
    e.target.style.boxShadow = '0 0 0 3px rgba(59,130,246,0.1)';
  };
  const handleBlur = (e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) => {
    e.target.style.borderColor = inputBorder;
    e.target.style.boxShadow = 'none';
  };

  const clearMessages = () => { setError(''); setSuccess(''); };

  /* ─── Step handlers ──────────────────────────────────────────────── */
  const handleSignUp = async () => {
    clearMessages();
    if (!name.trim() || !email.trim() || !phone.trim() || !password) {
      setError('All fields are required'); return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Enter a valid email address'); return;
    }
    if (!/^\d{10}$/.test(phone)) {
      setError('Enter a valid 10-digit mobile number'); return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters'); return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match'); return;
    }
    setLoading(true);
    try {
      await api.registerEmail({ email, password, phone, name });
      const loginRes = await api.loginEmailV2(email, password);
      setAuth(loginRes.access_token, { username: email, role: 'TRADER' });
      markComplete(0);
      goNext();
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  const handlePanVerify = async () => {
    clearMessages();
    if (!/^[A-Z]{5}\d{4}[A-Z]$/.test(pan.toUpperCase())) {
      setError('Enter a valid PAN (e.g. ABCDE1234F)'); return;
    }
    if (!dob) { setError('Date of birth is required'); return; }
    setLoading(true);
    try {
      const res = await api.submitPan(pan.toUpperCase());
      if (res.status === 'REJECTED') {
        setError(res.rejection_reason || 'PAN verification failed');
      } else {
        setPanVerified(true);
        setSuccess('PAN verified successfully');
        markComplete(1);
        setTimeout(goNext, 800);
      }
    } catch (err: any) {
      setError(err?.detail || err?.message || 'PAN verification failed');
    } finally {
      setLoading(false);
    }
  };

  const handleBankVerify = async () => {
    clearMessages();
    if (!accountHolder || !accountNumber || !ifsc || !bankName) {
      setError('All bank details are required'); return;
    }
    if (accountNumber !== confirmAccountNumber) {
      setError('Account numbers do not match'); return;
    }
    if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc.toUpperCase())) {
      setError('Enter a valid IFSC code'); return;
    }
    setLoading(true);
    try {
      await api.registerBankAccount({
        account_holder_name: accountHolder,
        account_number: accountNumber,
        ifsc_code: ifsc.toUpperCase(),
        bank_name: bankName,
        account_type: accountType,
      });
      setSuccess('Bank account linked successfully');
      markComplete(2);
      setTimeout(goNext, 800);
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Bank verification failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSegments = () => {
    clearMessages();
    if (segments.size === 0) { setError('Select at least one segment'); return; }
    markComplete(3);
    goNext();
  };

  const handlePersonal = () => {
    clearMessages();
    if (!occupation || !annualIncome || !tradingExperience) {
      setError('All fields are required'); return;
    }
    markComplete(4);
    goNext();
  };

  const handleNominee = () => {
    clearMessages();
    if (!nomineeName || !nomineeRelation || !nomineeDob) {
      setError('All nominee details are required'); return;
    }
    markComplete(5);
    goNext();
  };

  const handleEsign = () => {
    clearMessages();
    if (!selfieComplete || !esignComplete) {
      setError('Complete both liveliness check and e-Sign'); return;
    }
    markComplete(6);
    setSuccess('Account created successfully! Redirecting...');
    setTimeout(() => navigate('/', { replace: true }), 1500);
  };

  const markComplete = (step: number) => {
    setCompletedSteps((prev) => new Set([...prev, step]));
  };

  const goNext = () => {
    if (currentStep < STEPS.length - 1) setCurrentStep((s) => s + 1);
    clearMessages();
  };

  const goBack = () => {
    if (currentStep > 0) setCurrentStep((s) => s - 1);
    clearMessages();
  };

  const handleStepSubmit = () => {
    const handlers = [handleSignUp, handlePanVerify, handleBankVerify, handleSegments, handlePersonal, handleNominee, handleEsign];
    handlers[currentStep]();
  };

  const toggleSegment = (seg: string) => {
    setSegments((prev) => {
      const next = new Set(prev);
      if (next.has(seg)) next.delete(seg); else next.add(seg);
      return next;
    });
  };

  /* ─── Step content renderers ─────────────────────────────────────── */
  const renderSignUp = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <label style={labelStyle}>Full Name</label>
        <div style={{ position: 'relative' }}>
          <User size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: textMuted }} />
          <input style={{ ...inputStyle, paddingLeft: 40 }} placeholder="Enter your full name" value={name} onChange={(e) => setName(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div>
        <label style={labelStyle}>Email Address</label>
        <div style={{ position: 'relative' }}>
          <Mail size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: textMuted }} />
          <input style={{ ...inputStyle, paddingLeft: 40 }} type="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div>
        <label style={labelStyle}>Mobile Number</label>
        <div style={{ position: 'relative' }}>
          <Phone size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: textMuted }} />
          <input style={{ ...inputStyle, paddingLeft: 40 }} type="tel" placeholder="10-digit mobile number" maxLength={10} value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, ''))} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div>
        <label style={labelStyle}>Password</label>
        <div style={{ position: 'relative' }}>
          <Lock size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: textMuted }} />
          <input style={{ ...inputStyle, paddingLeft: 40, paddingRight: 44 }} type={showPassword ? 'text' : 'password'} placeholder="Min 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
          <button type="button" onClick={() => setShowPassword(!showPassword)} style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: textMuted, padding: 4 }}>
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </div>
      <div>
        <label style={labelStyle}>Confirm Password</label>
        <div style={{ position: 'relative' }}>
          <Lock size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: textMuted }} />
          <input style={{ ...inputStyle, paddingLeft: 40 }} type={showPassword ? 'text' : 'password'} placeholder="Re-enter password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
    </div>
  );

  const renderPan = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <h3 style={{ fontSize: 18, fontWeight: 700, color: textPrimary, margin: 0 }}>PAN Details</h3>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <label style={labelStyle}>PAN Number</label>
          <input style={inputStyle} placeholder="ABCDE1234F" maxLength={10} value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
        <div>
          <label style={labelStyle}>Date of Birth</label>
          <input style={inputStyle} type="date" value={dob} onChange={(e) => setDob(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
        <PANCardVisual pan={pan} dob={dob ? new Date(dob).toLocaleDateString('en-IN') : ''} isLight={isLight} />
      </div>
      {panVerified && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 10, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)' }}>
          <CheckCircle2 size={16} color="#10b981" />
          <span style={{ fontSize: 13, color: '#10b981', fontWeight: 600 }}>PAN Verified</span>
        </div>
      )}
    </div>
  );

  const renderBank = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <h3 style={{ fontSize: 18, fontWeight: 700, color: textPrimary, margin: 0 }}>Bank Account Details</h3>
      <div>
        <label style={labelStyle}>Account Holder Name</label>
        <input style={inputStyle} placeholder="As per bank records" value={accountHolder} onChange={(e) => setAccountHolder(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <label style={labelStyle}>Account Number</label>
          <input style={inputStyle} placeholder="Account number" value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
        <div>
          <label style={labelStyle}>Confirm Account Number</label>
          <input style={inputStyle} placeholder="Re-enter account number" value={confirmAccountNumber} onChange={(e) => setConfirmAccountNumber(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <label style={labelStyle}>IFSC Code</label>
          <input style={inputStyle} placeholder="e.g. SBIN0001234" maxLength={11} value={ifsc} onChange={(e) => setIfsc(e.target.value.toUpperCase())} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
        <div>
          <label style={labelStyle}>Bank Name</label>
          <input style={inputStyle} placeholder="Bank name" value={bankName} onChange={(e) => setBankName(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div>
        <label style={labelStyle}>Account Type</label>
        <select
          value={accountType}
          onChange={(e) => setAccountType(e.target.value)}
          onFocus={handleFocus as any}
          onBlur={handleBlur as any}
          style={{ ...inputStyle, cursor: 'pointer', appearance: 'auto' }}
        >
          <option value="savings">Savings</option>
          <option value="current">Current</option>
        </select>
      </div>
    </div>
  );

  const SEGMENT_OPTIONS = [
    { id: 'equity', label: 'Equity (Cash)', desc: 'Buy and sell stocks on NSE/BSE' },
    { id: 'fno', label: 'Futures & Options', desc: 'Trade derivatives with leverage' },
    { id: 'currency', label: 'Currency', desc: 'Trade forex pairs like USD/INR' },
    { id: 'commodity', label: 'Commodity', desc: 'Trade gold, silver, crude oil' },
  ];

  const renderSegments = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <h3 style={{ fontSize: 18, fontWeight: 700, color: textPrimary, margin: 0 }}>Select Trading Segments</h3>
      <p style={{ fontSize: 13, color: textSecondary, margin: 0 }}>Choose the segments you want to trade in. You can change this later.</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {SEGMENT_OPTIONS.map((seg) => {
          const active = segments.has(seg.id);
          return (
            <button
              key={seg.id}
              type="button"
              onClick={() => toggleSegment(seg.id)}
              style={{
                padding: '16px 18px', borderRadius: 14, textAlign: 'left', cursor: 'pointer',
                background: active ? 'rgba(59,130,246,0.1)' : (isLight ? '#f8fafc' : '#0a0f1e'),
                border: active ? '2px solid #3b82f6' : `1.5px solid ${inputBorder}`,
                transition: 'all 0.2s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: active ? '#3b82f6' : textPrimary }}>{seg.label}</span>
                {active && <CheckCircle2 size={16} color="#3b82f6" />}
              </div>
              <span style={{ fontSize: 11, color: textMuted }}>{seg.desc}</span>
            </button>
          );
        })}
      </div>
    </div>
  );

  const renderPersonal = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <h3 style={{ fontSize: 18, fontWeight: 700, color: textPrimary, margin: 0 }}>Personal Details</h3>
      <div>
        <label style={labelStyle}>Occupation</label>
        <select value={occupation} onChange={(e) => setOccupation(e.target.value)} onFocus={handleFocus as any} onBlur={handleBlur as any} style={{ ...inputStyle, cursor: 'pointer', appearance: 'auto' }}>
          <option value="">Select occupation</option>
          <option value="salaried">Salaried</option>
          <option value="self_employed">Self Employed</option>
          <option value="business">Business</option>
          <option value="student">Student</option>
          <option value="retired">Retired</option>
          <option value="homemaker">Homemaker</option>
        </select>
      </div>
      <div>
        <label style={labelStyle}>Annual Income</label>
        <select value={annualIncome} onChange={(e) => setAnnualIncome(e.target.value)} onFocus={handleFocus as any} onBlur={handleBlur as any} style={{ ...inputStyle, cursor: 'pointer', appearance: 'auto' }}>
          <option value="">Select income range</option>
          <option value="below_1l">Below ₹1 Lakh</option>
          <option value="1l_5l">₹1 Lakh - ₹5 Lakhs</option>
          <option value="5l_10l">₹5 Lakhs - ₹10 Lakhs</option>
          <option value="10l_25l">₹10 Lakhs - ₹25 Lakhs</option>
          <option value="above_25l">Above ₹25 Lakhs</option>
        </select>
      </div>
      <div>
        <label style={labelStyle}>Trading Experience</label>
        <select value={tradingExperience} onChange={(e) => setTradingExperience(e.target.value)} onFocus={handleFocus as any} onBlur={handleBlur as any} style={{ ...inputStyle, cursor: 'pointer', appearance: 'auto' }}>
          <option value="">Select experience</option>
          <option value="none">No experience</option>
          <option value="less_1y">Less than 1 year</option>
          <option value="1_3y">1-3 years</option>
          <option value="3_5y">3-5 years</option>
          <option value="above_5y">More than 5 years</option>
        </select>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontSize: 13, color: textSecondary }}>
        <input type="checkbox" checked={politicallyExposed} onChange={(e) => setPoliticallyExposed(e.target.checked)} style={{ width: 18, height: 18, accentColor: '#3b82f6' }} />
        I am a Politically Exposed Person (PEP)
      </label>
    </div>
  );

  const renderNominee = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <h3 style={{ fontSize: 18, fontWeight: 700, color: textPrimary, margin: 0 }}>Nominee Details</h3>
      <p style={{ fontSize: 13, color: textSecondary, margin: 0 }}>Add a nominee for your trading and demat account.</p>
      <div>
        <label style={labelStyle}>Nominee Full Name</label>
        <input style={inputStyle} placeholder="Full name of nominee" value={nomineeName} onChange={(e) => setNomineeName(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <label style={labelStyle}>Relationship</label>
          <select value={nomineeRelation} onChange={(e) => setNomineeRelation(e.target.value)} onFocus={handleFocus as any} onBlur={handleBlur as any} style={{ ...inputStyle, cursor: 'pointer', appearance: 'auto' }}>
            <option value="">Select</option>
            <option value="spouse">Spouse</option>
            <option value="parent">Parent</option>
            <option value="child">Child</option>
            <option value="sibling">Sibling</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div>
          <label style={labelStyle}>Date of Birth</label>
          <input style={inputStyle} type="date" value={nomineeDob} onChange={(e) => setNomineeDob(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
        </div>
      </div>
      <div>
        <label style={labelStyle}>Share Percentage</label>
        <input style={inputStyle} type="number" min={1} max={100} value={nomineeShare} onChange={(e) => setNomineeShare(e.target.value)} onFocus={handleFocus} onBlur={handleBlur} />
      </div>
    </div>
  );

  const renderEsign = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <h3 style={{ fontSize: 18, fontWeight: 700, color: textPrimary, margin: 0 }}>Liveliness Check & e-Sign</h3>
      <p style={{ fontSize: 13, color: textSecondary, margin: 0 }}>Complete a quick selfie verification and digitally sign your application.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <button
          type="button"
          onClick={() => setSelfieComplete(true)}
          style={{
            padding: '20px 24px', borderRadius: 14, cursor: 'pointer', textAlign: 'left',
            display: 'flex', alignItems: 'center', gap: 16,
            background: selfieComplete ? 'rgba(16,185,129,0.08)' : (isLight ? '#f8fafc' : '#0a0f1e'),
            border: selfieComplete ? '2px solid #10b981' : `1.5px solid ${inputBorder}`,
            transition: 'all 0.2s',
          }}
        >
          <div style={{
            width: 48, height: 48, borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: selfieComplete ? 'rgba(16,185,129,0.15)' : 'rgba(59,130,246,0.1)',
          }}>
            {selfieComplete ? <CheckCircle2 size={22} color="#10b981" /> : <Camera size={22} color="#3b82f6" />}
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: textPrimary }}>Liveliness Check</div>
            <div style={{ fontSize: 12, color: textMuted, marginTop: 2 }}>
              {selfieComplete ? 'Selfie verified successfully' : 'Take a quick selfie for identity verification'}
            </div>
          </div>
        </button>
        <button
          type="button"
          onClick={() => setEsignComplete(true)}
          style={{
            padding: '20px 24px', borderRadius: 14, cursor: 'pointer', textAlign: 'left',
            display: 'flex', alignItems: 'center', gap: 16,
            background: esignComplete ? 'rgba(16,185,129,0.08)' : (isLight ? '#f8fafc' : '#0a0f1e'),
            border: esignComplete ? '2px solid #10b981' : `1.5px solid ${inputBorder}`,
            transition: 'all 0.2s',
          }}
        >
          <div style={{
            width: 48, height: 48, borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: esignComplete ? 'rgba(16,185,129,0.15)' : 'rgba(59,130,246,0.1)',
          }}>
            {esignComplete ? <CheckCircle2 size={22} color="#10b981" /> : <FileCheck size={22} color="#3b82f6" />}
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: textPrimary }}>e-Sign Application</div>
            <div style={{ fontSize: 12, color: textMuted, marginTop: 2 }}>
              {esignComplete ? 'Application signed digitally' : 'Digitally sign your account opening form via Aadhaar'}
            </div>
          </div>
        </button>
      </div>
    </div>
  );

  const stepRenderers = [renderSignUp, renderPan, renderBank, renderSegments, renderPersonal, renderNominee, renderEsign];

  /* ─── Render ─────────────────────────────────────────────────────── */
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', flexDirection: 'column',
      background: bg, color: textPrimary,
      fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <header style={{
        height: 60, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 28px', flexShrink: 0,
        borderBottom: isLight ? '1px solid #e2e8f0' : '1px solid rgba(30,41,59,0.6)',
        background: isLight ? '#ffffff' : '#0a0f1e',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
            boxShadow: '0 4px 12px rgba(59,130,246,0.3)',
          }}>
            <Activity size={18} color="white" />
          </div>
          <span style={{
            fontSize: 18, fontWeight: 900, letterSpacing: '-0.02em',
            background: isLight ? 'linear-gradient(135deg, #2563eb, #4f46e5)' : 'linear-gradient(135deg, #60a5fa, #818cf8)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          }}>
            LOHI-TRADE
          </span>
        </div>
        <Link
          to="/login"
          style={{
            display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600,
            color: '#3b82f6', textDecoration: 'none',
          }}
        >
          <ArrowLeft size={15} />
          Back to Login
        </Link>
      </header>

      {/* ── Main content ───────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── Left: Stepper ────────────────────────────────────────── */}
        <div style={{
          width: 340, flexShrink: 0, padding: '40px 32px', overflowY: 'auto',
          borderRight: isLight ? '1px solid #e2e8f0' : '1px solid rgba(30,41,59,0.6)',
          background: isLight ? '#ffffff' : '#0a0f1e',
          display: 'none',
        }} className="stepper-panel">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {STEPS.map((step, idx) => {
              const isActive = idx === currentStep;
              const isCompleted = completedSteps.has(idx);
              const isPast = idx < currentStep;
              return (
                <div key={step.id} style={{ display: 'flex', gap: 16 }}>
                  {/* Dot + line */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 28 }}>
                    <motion.div
                      animate={{
                        scale: isActive ? 1.1 : 1,
                        background: isCompleted ? '#10b981' : isActive ? '#3b82f6' : (isLight ? '#cbd5e1' : '#334155'),
                      }}
                      style={{
                        width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        border: isActive ? '3px solid rgba(59,130,246,0.3)' : 'none',
                        flexShrink: 0,
                      }}
                    >
                      {isCompleted ? (
                        <Check size={14} color="white" strokeWidth={3} />
                      ) : (
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: isActive ? 'white' : (isLight ? '#94a3b8' : '#64748b') }} />
                      )}
                    </motion.div>
                    {idx < STEPS.length - 1 && (
                      <div style={{
                        width: 2, flex: 1, minHeight: 48,
                        background: isCompleted ? '#10b981' : (isLight ? '#e2e8f0' : '#1e293b'),
                        transition: 'background 0.3s',
                      }} />
                    )}
                  </div>
                  {/* Label */}
                  <div style={{ paddingBottom: idx < STEPS.length - 1 ? 32 : 0, paddingTop: 2 }}>
                    <button
                      type="button"
                      onClick={() => { if (isCompleted || isPast) { setCurrentStep(idx); clearMessages(); } }}
                      style={{
                        background: 'none', border: 'none', cursor: isCompleted || isPast ? 'pointer' : 'default',
                        padding: 0, textAlign: 'left',
                      }}
                    >
                      <div style={{
                        fontSize: 14, fontWeight: isActive ? 700 : 500,
                        color: isActive ? '#3b82f6' : isCompleted ? '#10b981' : textSecondary,
                        transition: 'color 0.2s',
                      }}>
                        {step.label}
                      </div>
                    </button>
                    {isActive && (
                      <motion.p
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        style={{ fontSize: 12, color: textMuted, marginTop: 4, lineHeight: 1.4 }}
                      >
                        {step.description}
                      </motion.p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Right: Form content ─────────────────────────────────── */}
        <div style={{ flex: 1, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '40px 32px', overflowY: 'auto' }}>
          <div style={{ width: '100%', maxWidth: 520 }}>

            {/* Mobile stepper (horizontal dots) */}
            <div className="mobile-stepper" style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 28,
            }}>
              {STEPS.map((_, idx) => (
                <div
                  key={idx}
                  style={{
                    width: idx === currentStep ? 28 : 8, height: 8, borderRadius: 4,
                    background: completedSteps.has(idx) ? '#10b981' : idx === currentStep ? '#3b82f6' : (isLight ? '#cbd5e1' : '#334155'),
                    transition: 'all 0.3s',
                  }}
                />
              ))}
            </div>

            {/* Step indicator */}
            <div style={{ marginBottom: 8 }}>
              <span style={{ fontSize: 11, color: textMuted, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                Step {currentStep + 1} of {STEPS.length}
              </span>
            </div>

            {/* Card */}
            <motion.div
              key={currentStep}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.25 }}
              style={{
                borderRadius: 20, padding: '32px 32px 28px',
                background: cardBg,
                border: `1px solid ${cardBorder}`,
                boxShadow: isLight
                  ? '0 8px 32px rgba(0,0,0,0.06)'
                  : '0 8px 32px rgba(0,0,0,0.3)',
              }}
            >
              {stepRenderers[currentStep]()}

              {/* Error / Success */}
              <AnimatePresence>
                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, marginTop: 16,
                      padding: '10px 14px', borderRadius: 10,
                      background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                    }}
                  >
                    <AlertCircle size={15} color="#ef4444" />
                    <span style={{ fontSize: 13, color: '#ef4444', fontWeight: 500 }}>{error}</span>
                  </motion.div>
                )}
                {success && (
                  <motion.div
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, marginTop: 16,
                      padding: '10px 14px', borderRadius: 10,
                      background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)',
                    }}
                  >
                    <CheckCircle2 size={15} color="#10b981" />
                    <span style={{ fontSize: 13, color: '#10b981', fontWeight: 500 }}>{success}</span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Action buttons */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 24, gap: 12 }}>
                {currentStep > 0 ? (
                  <button
                    type="button"
                    onClick={goBack}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '12px 20px', borderRadius: 12,
                      background: 'transparent', border: `1.5px solid ${inputBorder}`,
                      color: textSecondary, fontSize: 14, fontWeight: 600, cursor: 'pointer',
                      transition: 'all 0.2s',
                    }}
                  >
                    <ArrowLeft size={16} />
                    Back
                  </button>
                ) : <div />}

                <button
                  type="button"
                  onClick={handleStepSubmit}
                  disabled={loading}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8, padding: '12px 28px', borderRadius: 12,
                    background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                    border: 'none', color: 'white', fontSize: 14, fontWeight: 700,
                    cursor: loading ? 'not-allowed' : 'pointer',
                    opacity: loading ? 0.7 : 1,
                    boxShadow: '0 4px 16px rgba(59,130,246,0.3)',
                    transition: 'all 0.2s',
                  }}
                >
                  {loading ? (
                    <Spinner />
                  ) : currentStep === STEPS.length - 1 ? (
                    <>Complete Setup</>
                  ) : currentStep === 0 ? (
                    <>Create Account</>
                  ) : (
                    <>
                      {STEPS[currentStep].id === 'pan' || STEPS[currentStep].id === 'bank' ? 'Verify' : 'Continue'}
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </div>
            </motion.div>

            {/* Consent text */}
            <p style={{ fontSize: 11, color: textMuted, textAlign: 'center', marginTop: 20, lineHeight: 1.5 }}>
              By proceeding, I authorize Lohi-TRADE Securities Pvt. Ltd. to fetch my details from CKYCR and KRA solely for account opening and maintenance.
            </p>
          </div>
        </div>
      </div>

      {/* Chat bubble */}
      <ChatBubble isLight={isLight} />

      {/* ── Responsive CSS ─────────────────────────────────────────── */}
      <style>{`
        .stepper-panel { display: none !important; }
        .mobile-stepper { display: flex !important; }
        @media (min-width: 768px) {
          .stepper-panel { display: block !important; }
          .mobile-stepper { display: none !important; }
        }
      `}</style>
    </div>
  );
}
