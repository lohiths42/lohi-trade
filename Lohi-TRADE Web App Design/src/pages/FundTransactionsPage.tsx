import { useState, useEffect } from 'react';
import {
  Receipt, ArrowDownToLine, ArrowUpFromLine, Loader2, CheckCircle, XCircle, Clock,
} from 'lucide-react';
import { useThemeColors } from '../hooks/use-theme-colors';
import { api } from '../lib/api-client';
import PageHeader from '../components/shared/PageHeader';
import type { FundTransaction, BalanceResponse } from '../lib/types';

function statusIcon(status: string) {
  if (status === 'COMPLETED') return <CheckCircle size={14} color="#34d399" />;
  if (status === 'FAILED') return <XCircle size={14} color="#f87171" />;
  return <Clock size={14} color="#fbbf24" />;
}

function statusColor(status: string) {
  if (status === 'COMPLETED') return '#34d399';
  if (status === 'FAILED') return '#f87171';
  return '#fbbf24';
}

export default function FundTransactionsPage() {
  const t = useThemeColors();
  const [transactions, setTransactions] = useState<FundTransaction[]>([]);
  const [balance, setBalance] = useState<BalanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'ALL' | 'DEPOSIT' | 'WITHDRAWAL'>('ALL');

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [txns, bal] = await Promise.all([
        api.listFundTransactions().catch(() => ({ transactions: [], count: 0 })),
        api.getFundBalance().catch(() => null),
      ]);
      setTransactions(txns.transactions);
      if (bal) setBalance(bal);
    } finally {
      setLoading(false);
    }
  }

  const filtered = filter === 'ALL' ? transactions : transactions.filter((tx) => tx.type === filter);

  const cardStyle: React.CSSProperties = {
    background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16, padding: 24, boxShadow: t.cardShadow,
  };

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
        icon={<Receipt size={16} />}
        title="Fund Transactions"
        subtitle="Deposit and withdrawal history"
      />

      <div style={{ height: 20 }} />

      {/* Balance summary */}
      {balance && (
        <div style={{ ...cardStyle, marginBottom: 20, display: 'flex', gap: 32 }}>
          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 4px' }}>Available</p>
            <p style={{ fontSize: 20, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: '#34d399', margin: 0 }}>₹{parseFloat(balance.available_balance).toLocaleString('en-IN')}</p>
          </div>
          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 4px' }}>Blocked</p>
            <p style={{ fontSize: 20, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: '#fbbf24', margin: 0 }}>₹{parseFloat(balance.blocked_margin).toLocaleString('en-IN')}</p>
          </div>
          <div>
            <p style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 4px' }}>Withdrawable</p>
            <p style={{ fontSize: 20, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: t.textPrimary, margin: 0 }}>₹{parseFloat(balance.withdrawable_balance).toLocaleString('en-IN')}</p>
          </div>
        </div>
      )}

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {(['ALL', 'DEPOSIT', 'WITHDRAWAL'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '8px 18px', borderRadius: 8, fontSize: 12, fontWeight: 700,
              background: filter === f ? t.accentBg : 'transparent',
              border: `1px solid ${filter === f ? t.accentText + '40' : t.borderPrimary}`,
              color: filter === f ? t.accentText : t.textMuted,
              cursor: 'pointer', transition: 'all 0.15s',
            }}
          >
            {f === 'ALL' ? 'All' : f === 'DEPOSIT' ? 'Deposits' : 'Withdrawals'}
          </button>
        ))}
        <span style={{ fontSize: 12, color: t.textMuted, alignSelf: 'center', marginLeft: 'auto' }}>
          {filtered.length} transaction{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Transaction list */}
      <div style={cardStyle}>
        {filtered.length === 0 ? (
          <p style={{ fontSize: 13, color: t.textMuted, textAlign: 'center', padding: 20 }}>No transactions found.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filtered.map((tx) => (
              <div key={tx.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '14px 16px', borderRadius: 12, background: t.bgMuted, border: `1px solid ${t.borderPrimary}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: tx.type === 'DEPOSIT' ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)',
                  }}>
                    {tx.type === 'DEPOSIT'
                      ? <ArrowDownToLine size={16} color="#34d399" />
                      : <ArrowUpFromLine size={16} color="#f87171" />}
                  </div>
                  <div>
                    <p style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: 0 }}>
                      {tx.type === 'DEPOSIT' ? 'Deposit' : 'Withdrawal'}
                      {tx.payment_method && <span style={{ fontSize: 11, color: t.textMuted, marginLeft: 8 }}>via {tx.payment_method}</span>}
                    </p>
                    <p style={{ fontSize: 11, color: t.textMuted, margin: '2px 0 0' }}>
                      {tx.created_at ? new Date(tx.created_at).toLocaleString() : '—'}
                      {tx.transaction_ref && <span> · Ref: {tx.transaction_ref}</span>}
                    </p>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <p style={{
                    fontSize: 15, fontWeight: 800, fontFamily: 'ui-monospace,monospace', margin: 0,
                    color: tx.type === 'DEPOSIT' ? '#34d399' : '#f87171',
                  }}>
                    {tx.type === 'DEPOSIT' ? '+' : '-'}₹{parseFloat(tx.amount).toLocaleString('en-IN')}
                  </p>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {statusIcon(tx.status)}
                    <span style={{ fontSize: 11, fontWeight: 700, color: statusColor(tx.status) }}>{tx.status}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
