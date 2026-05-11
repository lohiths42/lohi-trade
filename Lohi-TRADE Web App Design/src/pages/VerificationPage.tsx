import { useState, useEffect } from 'react';
import {
  ShieldCheck, CreditCard, FileText, Landmark, CheckCircle, XCircle,
  Clock, Loader2, ChevronRight, AlertTriangle, Trash2, Plus,
} from 'lucide-react';
import { useThemeColors } from '../hooks/use-theme-colors';
import { api } from '../lib/api-client';
import PageHeader from '../components/shared/PageHeader';
import type {
  PANStatusResponse, KYCStatusResponse, DMATAccount,
} from '../lib/types';

/* ─── Step indicator ─────────────────────────────────────────────────────── */

const STEPS = [
  { key: 'pan', label: 'PAN Verification', icon: CreditCard },
  { key: 'kyc', label: 'KYC Verification', icon: FileText },
  { key: 'dmat', label: 'DMAT Linking', icon: Landmark },
] as const;

type StepKey = (typeof STEPS)[number]['key'];

function statusColor(status: string) {
  if (status === 'VERIFIED' || status === 'LINKED') return '#34d399';
  if (status === 'REJECTED' || status === 'FAILED') return '#f87171';
  if (status === 'PENDING') return '#fbbf24';
  return '#64748b';
}

function StatusBadge({ status }: { status: string }) {
  const c = statusColor(status);
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 6,
      background: `${c}18`, color: c, letterSpacing: '0.04em',
    }}>
      {status}
    </span>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */

export default function VerificationPage() {
  const t = useThemeColors();
  const [activeStep, setActiveStep] = useState<StepKey>('pan');
  const [loading, setLoading] = useState(true);

  // PAN state
  const [panStatus, setPanStatus] = useState<PANStatusResponse | null>(null);
  const [panInput, setPanInput] = useState('');
  const [panSubmitting, setPanSubmitting] = useState(false);
  const [panError, setPanError] = useState('');

  // KYC state
  const [kycStatus, setKycStatus] = useState<KYCStatusResponse | null>(null);
  const [kycForm, setKycForm] = useState({ full_name: '', date_of_birth: '', address: '', aadhaar_number: '' });
  const [kycFile, setKycFile] = useState<File | null>(null);
  const [kycSubmitting, setKycSubmitting] = useState(false);
  const [kycError, setKycError] = useState('');

  // DMAT state
  const [dmatAccounts, setDmatAccounts] = useState<DMATAccount[]>([]);
  const [dmatInput, setDmatInput] = useState('');
  const [dmatSubmitting, setDmatSubmitting] = useState(false);
  const [dmatError, setDmatError] = useState('');

  useEffect(() => {
    loadStatuses();
  }, []);

  async function loadStatuses() {
    setLoading(true);
    try {
      const [pan, kyc, dmat] = await Promise.all([
        api.getPanStatus().catch(() => null),
        api.getKycStatus().catch(() => null),
        api.listDmatAccounts().catch(() => ({ accounts: [], count: 0 })),
      ]);
      if (pan) setPanStatus(pan);
      if (kyc) setKycStatus(kyc);
      setDmatAccounts(dmat.accounts);

      // Auto-select first incomplete step
      if (pan?.status === 'VERIFIED') {
        if (kyc?.status === 'VERIFIED') setActiveStep('dmat');
        else setActiveStep('kyc');
      }
    } finally {
      setLoading(false);
    }
  }

  /* ── PAN submit ──────────────────────────────────────────────────────── */
  async function handlePanSubmit() {
    setPanError('');
    const panRegex = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
    if (!panRegex.test(panInput.toUpperCase())) {
      setPanError('Invalid PAN format. Expected: ABCDE1234F');
      return;
    }
    setPanSubmitting(true);
    try {
      const res = await api.submitPan(panInput.toUpperCase());
      setPanStatus({ status: res.status as PANStatusResponse['status'], pan_masked: res.pan_masked, holder_name: res.holder_name, rejection_reason: res.rejection_reason });
      if (res.status === 'VERIFIED') setActiveStep('kyc');
    } catch (e: any) {
      setPanError(e?.detail || e?.message || 'PAN verification failed');
    } finally {
      setPanSubmitting(false);
    }
  }

  /* ── KYC submit ──────────────────────────────────────────────────────── */
  async function handleKycSubmit() {
    setKycError('');
    if (!kycForm.full_name || !kycForm.date_of_birth || !kycForm.address) {
      setKycError('Please fill all required fields');
      return;
    }
    if (!kycFile) {
      setKycError('Please upload a government ID photo');
      return;
    }
    setKycSubmitting(true);
    try {
      const fd = new FormData();
      fd.append('full_name', kycForm.full_name);
      fd.append('date_of_birth', kycForm.date_of_birth);
      fd.append('address', kycForm.address);
      if (kycForm.aadhaar_number) fd.append('aadhaar_number', kycForm.aadhaar_number);
      fd.append('government_id_photo', kycFile);
      const res = await api.submitKyc(fd);
      setKycStatus({ status: res.status as KYCStatusResponse['status'], verification_ref: res.verification_ref, rejection_reason: res.rejection_reason });
      if (res.status === 'VERIFIED') setActiveStep('dmat');
    } catch (e: any) {
      setKycError(e?.detail || e?.message || 'KYC submission failed');
    } finally {
      setKycSubmitting(false);
    }
  }

  /* ── DMAT link ───────────────────────────────────────────────────────── */
  async function handleDmatLink() {
    setDmatError('');
    if (!dmatInput.trim()) { setDmatError('Enter a DMAT account number'); return; }
    setDmatSubmitting(true);
    try {
      const res = await api.linkDmat(dmatInput.trim());
      if (res.status === 'LINKED') {
        setDmatInput('');
        const list = await api.listDmatAccounts();
        setDmatAccounts(list.accounts);
      } else {
        setDmatError(res.rejection_reason || res.message);
      }
    } catch (e: any) {
      setDmatError(e?.detail || e?.message || 'DMAT linking failed');
    } finally {
      setDmatSubmitting(false);
    }
  }

  async function handleDmatUnlink(id: string) {
    try {
      await api.unlinkDmat(id);
      setDmatAccounts((prev) => prev.filter((a) => a.dmat_id !== id));
    } catch (e: any) {
      setDmatError(e?.detail || e?.message || 'Failed to unlink');
    }
  }

  /* ── Render helpers ──────────────────────────────────────────────────── */
  const cardStyle: React.CSSProperties = {
    background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16, padding: 28, boxShadow: t.cardShadow,
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: 14,
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    color: t.textPrimary, outline: 'none',
  };

  const btnPrimary: React.CSSProperties = {
    padding: '10px 24px', borderRadius: 10, fontSize: 13, fontWeight: 700,
    background: 'linear-gradient(135deg, #3b82f6, #6366f1)', color: '#fff',
    border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin" style={{ color: t.accentText }} />
      </div>
    );
  }

  function getStepStatus(key: StepKey): string {
    if (key === 'pan') return panStatus?.status || 'NOT_SUBMITTED';
    if (key === 'kyc') return kycStatus?.status || 'NOT_STARTED';
    return dmatAccounts.some((a) => a.status === 'LINKED') ? 'LINKED' : 'NOT_LINKED';
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <PageHeader
        icon={<ShieldCheck size={16} />}
        title="Account Verification"
        subtitle="Complete PAN, KYC, and DMAT verification to start trading"
      />

      <div style={{ height: 20 }} />

      {/* Step indicators */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 28 }}>
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          const status = getStepStatus(step.key);
          const isActive = activeStep === step.key;
          const isDone = status === 'VERIFIED' || status === 'LINKED';
          return (
            <button
              key={step.key}
              onClick={() => setActiveStep(step.key)}
              style={{
                flex: 1, display: 'flex', alignItems: 'center', gap: 10,
                padding: '14px 16px', borderRadius: 12, cursor: 'pointer',
                background: isActive ? t.accentBg : 'transparent',
                border: `1px solid ${isActive ? t.accentText + '40' : t.borderPrimary}`,
                transition: 'all 0.15s',
              }}
            >
              <div style={{
                width: 36, height: 36, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: isDone ? 'rgba(52,211,153,0.15)' : isActive ? t.accentBg : t.bgMuted,
              }}>
                {isDone ? <CheckCircle size={18} color="#34d399" /> : <Icon size={18} style={{ color: isActive ? t.accentText : t.textMuted }} />}
              </div>
              <div style={{ textAlign: 'left' }}>
                <p style={{ fontSize: 12, fontWeight: 700, color: t.textPrimary, margin: 0 }}>{step.label}</p>
                <p style={{ fontSize: 10, color: t.textMuted, margin: '2px 0 0' }}>{status.replace(/_/g, ' ')}</p>
              </div>
              {i < STEPS.length - 1 && <ChevronRight size={14} style={{ color: t.textMuted, marginLeft: 'auto' }} />}
            </button>
          );
        })}
      </div>

      {/* ── PAN Step ─────────────────────────────────────────────────────── */}
      {activeStep === 'pan' && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: t.textPrimary, margin: '0 0 6px' }}>PAN Card Verification</h2>
          <p style={{ fontSize: 13, color: t.textSecondary, margin: '0 0 20px' }}>
            Verify your Permanent Account Number as required by SEBI regulations.
          </p>

          {panStatus?.status === 'VERIFIED' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 16, borderRadius: 12, background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.2)' }}>
              <CheckCircle size={20} color="#34d399" />
              <div>
                <p style={{ fontSize: 14, fontWeight: 600, color: '#34d399', margin: 0 }}>PAN Verified</p>
                <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0' }}>
                  {panStatus.pan_masked} — {panStatus.holder_name}
                </p>
              </div>
            </div>
          ) : (
            <>
              {panStatus?.status === 'REJECTED' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 12, borderRadius: 10, background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)', marginBottom: 16 }}>
                  <XCircle size={16} color="#f87171" />
                  <span style={{ fontSize: 12, color: '#f87171' }}>Rejected: {panStatus.rejection_reason}</span>
                </div>
              )}
              <div style={{ display: 'flex', gap: 12 }}>
                <input
                  style={inputStyle}
                  placeholder="Enter PAN (e.g. ABCDE1234F)"
                  value={panInput}
                  onChange={(e) => setPanInput(e.target.value.toUpperCase())}
                  maxLength={10}
                />
                <button style={btnPrimary} onClick={handlePanSubmit} disabled={panSubmitting}>
                  {panSubmitting ? <Loader2 size={14} className="animate-spin" /> : 'Verify'}
                </button>
              </div>
              {panError && <p style={{ fontSize: 12, color: '#f87171', marginTop: 8 }}>{panError}</p>}
            </>
          )}
        </div>
      )}

      {/* ── KYC Step ─────────────────────────────────────────────────────── */}
      {activeStep === 'kyc' && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: t.textPrimary, margin: '0 0 6px' }}>KYC Verification</h2>
          <p style={{ fontSize: 13, color: t.textSecondary, margin: '0 0 20px' }}>
            Submit your identity documents for Know Your Customer verification.
          </p>

          {panStatus?.status !== 'VERIFIED' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 14, borderRadius: 10, background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
              <AlertTriangle size={16} color="#fbbf24" />
              <span style={{ fontSize: 13, color: '#fbbf24' }}>Complete PAN verification first</span>
            </div>
          )}

          {panStatus?.status === 'VERIFIED' && kycStatus?.status === 'VERIFIED' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 16, borderRadius: 12, background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.2)' }}>
              <CheckCircle size={20} color="#34d399" />
              <div>
                <p style={{ fontSize: 14, fontWeight: 600, color: '#34d399', margin: 0 }}>KYC Verified</p>
                {kycStatus.verification_ref && <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0' }}>Ref: {kycStatus.verification_ref}</p>}
              </div>
            </div>
          )}

          {panStatus?.status === 'VERIFIED' && kycStatus?.status === 'PENDING' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 14, borderRadius: 10, background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
              <Clock size={16} color="#fbbf24" />
              <span style={{ fontSize: 13, color: '#fbbf24' }}>KYC verification is being processed</span>
            </div>
          )}

          {panStatus?.status === 'VERIFIED' && (!kycStatus || kycStatus.status === 'NOT_STARTED' || kycStatus.status === 'REJECTED') && (
            <>
              {kycStatus?.status === 'REJECTED' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 12, borderRadius: 10, background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)', marginBottom: 16 }}>
                  <XCircle size={16} color="#f87171" />
                  <span style={{ fontSize: 12, color: '#f87171' }}>Rejected: {kycStatus.rejection_reason}</span>
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <input style={inputStyle} placeholder="Full Name *" value={kycForm.full_name} onChange={(e) => setKycForm((p) => ({ ...p, full_name: e.target.value }))} />
                <input style={inputStyle} type="date" placeholder="Date of Birth *" value={kycForm.date_of_birth} onChange={(e) => setKycForm((p) => ({ ...p, date_of_birth: e.target.value }))} />
                <input style={inputStyle} placeholder="Address *" value={kycForm.address} onChange={(e) => setKycForm((p) => ({ ...p, address: e.target.value }))} />
                <input style={inputStyle} placeholder="Aadhaar Number (optional)" value={kycForm.aadhaar_number} onChange={(e) => setKycForm((p) => ({ ...p, aadhaar_number: e.target.value }))} />
                <div>
                  <label style={{ fontSize: 12, fontWeight: 600, color: t.textSecondary, display: 'block', marginBottom: 6 }}>Government ID Photo *</label>
                  <input type="file" accept="image/jpeg,image/png" onChange={(e) => setKycFile(e.target.files?.[0] || null)} style={{ fontSize: 13, color: t.textSecondary }} />
                </div>
                <button style={{ ...btnPrimary, alignSelf: 'flex-start' }} onClick={handleKycSubmit} disabled={kycSubmitting}>
                  {kycSubmitting ? <Loader2 size={14} className="animate-spin" /> : 'Submit KYC'}
                </button>
              </div>
              {kycError && <p style={{ fontSize: 12, color: '#f87171', marginTop: 8 }}>{kycError}</p>}
            </>
          )}
        </div>
      )}

      {/* ── DMAT Step ────────────────────────────────────────────────────── */}
      {activeStep === 'dmat' && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: t.textPrimary, margin: '0 0 6px' }}>DMAT Account Linking</h2>
          <p style={{ fontSize: 13, color: t.textSecondary, margin: '0 0 20px' }}>
            Link your CDSL or NSDL demat account for electronic securities holding. Max 3 accounts.
          </p>

          {kycStatus?.status !== 'VERIFIED' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 14, borderRadius: 10, background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
              <AlertTriangle size={16} color="#fbbf24" />
              <span style={{ fontSize: 13, color: '#fbbf24' }}>Complete KYC verification first</span>
            </div>
          )}

          {kycStatus?.status === 'VERIFIED' && (
            <>
              {/* Linked accounts */}
              {dmatAccounts.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
                  {dmatAccounts.map((acc) => (
                    <div key={acc.dmat_id} style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '12px 16px', borderRadius: 10, background: t.bgMuted, border: `1px solid ${t.borderPrimary}`,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <Landmark size={16} style={{ color: t.accentText }} />
                        <div>
                          <p style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: 0 }}>{acc.depository} — {acc.dp_name || 'DP'}</p>
                          <p style={{ fontSize: 11, color: t.textMuted, margin: '2px 0 0' }}>ID: {acc.dmat_id}</p>
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <StatusBadge status={acc.status} />
                        <button onClick={() => handleDmatUnlink(acc.dmat_id)} style={{ padding: 6, borderRadius: 6, background: 'rgba(248,113,113,0.1)', border: 'none', cursor: 'pointer' }}>
                          <Trash2 size={14} color="#f87171" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Link new */}
              {dmatAccounts.length < 3 && (
                <div style={{ display: 'flex', gap: 12 }}>
                  <input
                    style={inputStyle}
                    placeholder="DMAT account number (CDSL: 16 digits, NSDL: IN + 14 chars)"
                    value={dmatInput}
                    onChange={(e) => setDmatInput(e.target.value)}
                  />
                  <button style={btnPrimary} onClick={handleDmatLink} disabled={dmatSubmitting}>
                    {dmatSubmitting ? <Loader2 size={14} className="animate-spin" /> : <><Plus size={14} /> Link</>}
                  </button>
                </div>
              )}
              {dmatError && <p style={{ fontSize: 12, color: '#f87171', marginTop: 8 }}>{dmatError}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
