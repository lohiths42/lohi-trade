import { useState, useEffect } from 'react';
import {
  Building2, Plus, CheckCircle, XCircle, Star, Loader2, AlertTriangle,
  ArrowDownToLine, ArrowUpFromLine,
} from 'lucide-react';
import { useThemeColors } from '../hooks/use-theme-colors';
import { api } from '../lib/api-client';
import PageHeader from '../components/shared/PageHeader';
import type {
  BankAccountItem, BankRegisterRequest, BalanceResponse, PaymentMethod,
} from '../lib/types';

/* ─── Page ───────────────────────────────────────────────────────────────── */

export default function BankAccountPage() {
  const t = useThemeColors();
  const [accounts, setAccounts] = useState<BankAccountItem[]>([]);
  const [balance, setBalance] = useState<BalanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);

  // Register form
  const [regForm, setRegForm] = useState<BankRegisterRequest>({
    account_holder_name: '', account_number: '', ifsc_code: '', bank_name: '', account_type: 'savings',
  });
  const [regSubmitting, setRegSubmitting] = useState(false);
  const [regError, setRegError] = useState('');

  // Deposit form
  const [showDeposit, setShowDeposit] = useState(false);
  const [depositAmount, setDepositAmount] = useState('');
  const [depositMethod, setDepositMethod] = useState<PaymentMethod>('UPI');
  const [depositSubmitting, setDepositSubmitting] = useState(false);
  const [depositMsg, setDepositMsg] = useState('');

  // Withdraw form
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [withdrawBankId, setWithdrawBankId] = useState('');
  const [withdrawSubmitting, setWithdrawSubmitting] = useState(false);
  const [withdrawMsg, setWithdrawMsg] = useState('');

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [bankList, bal] = await Promise.all([
        api.listBankAccounts().catch(() => ({ accounts: [], count: 0 })),
        api.getFundBalance().catch(() => null),
      ]);
      setAccounts(bankList.accounts);
      if (bal) setBalance(bal);
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister() {
    setRegError('');
    if (!regForm.account_holder_name || !regForm.account_number || !regForm.ifsc_code || !regForm.bank_name) {
      setRegError('All fields are required');
      return;
    }
    if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(regForm.ifsc_code.toUpperCase())) {
      setRegError('Invalid IFSC code format');
      return;
    }
    setRegSubmitting(true);
    try {
      await api.registerBankAccount({ ...regForm, ifsc_code: regForm.ifsc_code.toUpperCase() });
      setShowRegister(false);
      setRegForm({ account_holder_name: '', account_number: '', ifsc_code: '', bank_name: '', account_type: 'savings' });
      await loadData();
    } catch (e: any) {
      setRegError(e?.detail || e?.message || 'Registration failed');
    } finally {
      setRegSubmitting(false);
    }
  }

  async function handleSetPrimary(id: string) {
    try {
      await api.setPrimaryBank(id);
      await loadData();
    } catch { /* ignore */ }
  }

  async function handleDeposit() {
    setDepositMsg('');
    const amt = parseFloat(depositAmount);
    if (isNaN(amt) || amt < 100 || amt > 1000000) {
      setDepositMsg('Amount must be between ₹100 and ₹10,00,000');
      return;
    }
    setDepositSubmitting(true);
    try {
      const res = await api.depositFunds({ amount: depositAmount, payment_method: depositMethod });
      setDepositMsg(res.message);
      setDepositAmount('');
      await loadData();
    } catch (e: any) {
      setDepositMsg(e?.detail || e?.message || 'Deposit failed');
    } finally {
      setDepositSubmitting(false);
    }
  }

  async function handleWithdraw() {
    setWithdrawMsg('');
    const amt = parseFloat(withdrawAmount);
    if (isNaN(amt) || amt < 100) {
      setWithdrawMsg('Minimum withdrawal is ₹100');
      return;
    }
    if (!withdrawBankId) {
      setWithdrawMsg('Select a bank account');
      return;
    }
    setWithdrawSubmitting(true);
    try {
      const res = await api.withdrawFunds({ amount: withdrawAmount, bank_account_id: withdrawBankId });
      setWithdrawMsg(res.message);
      setWithdrawAmount('');
      await loadData();
    } catch (e: any) {
      setWithdrawMsg(e?.detail || e?.message || 'Withdrawal failed');
    } finally {
      setWithdrawSubmitting(false);
    }
  }

  const cardStyle: React.CSSProperties = {
    background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16, padding: 24, boxShadow: t.cardShadow,
  };
  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: 14,
    background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textPrimary, outline: 'none',
  };
  const btnPrimary: React.CSSProperties = {
    padding: '10px 24px', borderRadius: 10, fontSize: 13, fontWeight: 700,
    background: 'linear-gradient(135deg, #3b82f6, #6366f1)', color: '#fff',
    border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
  };
  const btnOutline: React.CSSProperties = {
    padding: '10px 20px', borderRadius: 10, fontSize: 13, fontWeight: 600,
    background: 'transparent', border: `1px solid ${t.borderPrimary}`,
    color: t.textSecondary, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
  };

  const verifiedAccounts = accounts.filter((a) => a.status === 'VERIFIED');

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin" style={{ color: t.accentText }} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <PageHeader
        icon={<Building2 size={16} />}
        title="Bank & Funds"
        subtitle="Manage bank accounts, deposits, and withdrawals"
        actions={
          <>
            <button style={btnOutline} onClick={() => { setShowDeposit(!showDeposit); setShowWithdraw(false); }}>
              <ArrowDownToLine size={14} /> Deposit
            </button>
            <button style={btnOutline} onClick={() => { setShowWithdraw(!showWithdraw); setShowDeposit(false); }}>
              <ArrowUpFromLine size={14} /> Withdraw
            </button>
          </>
        }
      />

      <div style={{ height: 20 }} />

      {/* Balance card */}
      {balance && (
        <div style={{ ...cardStyle, marginBottom: 20, display: 'flex', gap: 32 }}>
          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 4px' }}>Available Balance</p>
            <p style={{ fontSize: 24, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: '#34d399', margin: 0 }}>₹{parseFloat(balance.available_balance).toLocaleString('en-IN')}</p>
          </div>
          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 4px' }}>Blocked Margin</p>
            <p style={{ fontSize: 24, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: '#fbbf24', margin: 0 }}>₹{parseFloat(balance.blocked_margin).toLocaleString('en-IN')}</p>
          </div>
          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 4px' }}>Withdrawable</p>
            <p style={{ fontSize: 24, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: t.textPrimary, margin: 0 }}>₹{parseFloat(balance.withdrawable_balance).toLocaleString('en-IN')}</p>
          </div>
        </div>
      )}

      {/* Deposit form */}
      {showDeposit && (
        <div style={{ ...cardStyle, marginBottom: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 16px' }}>Deposit Funds</h3>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <input style={{ ...inputStyle, maxWidth: 200 }} placeholder="Amount (₹)" value={depositAmount} onChange={(e) => setDepositAmount(e.target.value)} type="number" min={100} max={1000000} />
            <select style={{ ...inputStyle, maxWidth: 180 }} value={depositMethod} onChange={(e) => setDepositMethod(e.target.value as PaymentMethod)}>
              <option value="UPI">UPI</option>
              <option value="NET_BANKING">Net Banking</option>
              <option value="NEFT">NEFT</option>
              <option value="RTGS">RTGS</option>
              <option value="IMPS">IMPS</option>
            </select>
            <button style={btnPrimary} onClick={handleDeposit} disabled={depositSubmitting}>
              {depositSubmitting ? <Loader2 size={14} className="animate-spin" /> : 'Deposit'}
            </button>
          </div>
          {depositMsg && <p style={{ fontSize: 12, color: depositMsg.includes('fail') ? '#f87171' : '#34d399', marginTop: 8 }}>{depositMsg}</p>}
        </div>
      )}

      {/* Withdraw form */}
      {showWithdraw && (
        <div style={{ ...cardStyle, marginBottom: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 16px' }}>Withdraw Funds</h3>
          {verifiedAccounts.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 14, borderRadius: 10, background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
              <AlertTriangle size={16} color="#fbbf24" />
              <span style={{ fontSize: 13, color: '#fbbf24' }}>No verified bank accounts. Register and verify a bank account first.</span>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <input style={{ ...inputStyle, maxWidth: 200 }} placeholder="Amount (₹)" value={withdrawAmount} onChange={(e) => setWithdrawAmount(e.target.value)} type="number" min={100} />
              <select style={{ ...inputStyle, maxWidth: 260 }} value={withdrawBankId} onChange={(e) => setWithdrawBankId(e.target.value)}>
                <option value="">Select bank account</option>
                {verifiedAccounts.map((a) => (
                  <option key={a.id} value={a.id!}>{a.bank_name} — {a.account_holder_name}{a.is_primary ? ' (Primary)' : ''}</option>
                ))}
              </select>
              <button style={btnPrimary} onClick={handleWithdraw} disabled={withdrawSubmitting}>
                {withdrawSubmitting ? <Loader2 size={14} className="animate-spin" /> : 'Withdraw'}
              </button>
            </div>
          )}
          {withdrawMsg && <p style={{ fontSize: 12, color: withdrawMsg.includes('fail') || withdrawMsg.includes('Fail') ? '#f87171' : '#34d399', marginTop: 8 }}>{withdrawMsg}</p>}
        </div>
      )}

      {/* Bank accounts list */}
      <div style={{ ...cardStyle, marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Bank Accounts</h3>
          {accounts.length < 3 && (
            <button style={btnOutline} onClick={() => setShowRegister(!showRegister)}>
              <Plus size={14} /> Add Account
            </button>
          )}
        </div>

        {accounts.length === 0 && !showRegister && (
          <p style={{ fontSize: 13, color: t.textMuted, textAlign: 'center', padding: 20 }}>No bank accounts registered yet.</p>
        )}

        {accounts.map((acc) => (
          <div key={acc.id} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '14px 16px', borderRadius: 12, marginBottom: 10,
            background: t.bgMuted, border: `1px solid ${t.borderPrimary}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Building2 size={16} style={{ color: t.accentText }} />
              <div>
                <p style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: 0 }}>
                  {acc.bank_name} — {acc.account_holder_name}
                  {acc.is_primary && <Star size={12} color="#fbbf24" style={{ marginLeft: 6, verticalAlign: 'middle' }} />}
                </p>
                <p style={{ fontSize: 11, color: t.textMuted, margin: '2px 0 0' }}>IFSC: {acc.ifsc_code} · {acc.account_type}</p>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {acc.status === 'VERIFIED' ? (
                <CheckCircle size={16} color="#34d399" />
              ) : acc.status === 'FAILED' ? (
                <XCircle size={16} color="#f87171" />
              ) : (
                <Loader2 size={16} className="animate-spin" style={{ color: '#fbbf24' }} />
              )}
              <span style={{ fontSize: 11, fontWeight: 700, color: acc.status === 'VERIFIED' ? '#34d399' : acc.status === 'FAILED' ? '#f87171' : '#fbbf24' }}>{acc.status}</span>
              {acc.status === 'VERIFIED' && !acc.is_primary && (
                <button onClick={() => handleSetPrimary(acc.id!)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6, background: t.accentBg, border: 'none', color: t.accentText, cursor: 'pointer', fontWeight: 600 }}>
                  Set Primary
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Register form */}
      {showRegister && (
        <div style={{ ...cardStyle }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 16px' }}>Register Bank Account</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <input style={inputStyle} placeholder="Account Holder Name *" value={regForm.account_holder_name} onChange={(e) => setRegForm((p) => ({ ...p, account_holder_name: e.target.value }))} />
            <input style={inputStyle} placeholder="Account Number *" value={regForm.account_number} onChange={(e) => setRegForm((p) => ({ ...p, account_number: e.target.value }))} />
            <input style={inputStyle} placeholder="IFSC Code *" value={regForm.ifsc_code} onChange={(e) => setRegForm((p) => ({ ...p, ifsc_code: e.target.value.toUpperCase() }))} maxLength={11} />
            <input style={inputStyle} placeholder="Bank Name *" value={regForm.bank_name} onChange={(e) => setRegForm((p) => ({ ...p, bank_name: e.target.value }))} />
            <select style={inputStyle} value={regForm.account_type} onChange={(e) => setRegForm((p) => ({ ...p, account_type: e.target.value }))}>
              <option value="savings">Savings</option>
              <option value="current">Current</option>
            </select>
            <button style={{ ...btnPrimary, alignSelf: 'flex-start' }} onClick={handleRegister} disabled={regSubmitting}>
              {regSubmitting ? <Loader2 size={14} className="animate-spin" /> : 'Register Account'}
            </button>
          </div>
          {regError && <p style={{ fontSize: 12, color: '#f87171', marginTop: 8 }}>{regError}</p>}
        </div>
      )}
    </div>
  );
}
