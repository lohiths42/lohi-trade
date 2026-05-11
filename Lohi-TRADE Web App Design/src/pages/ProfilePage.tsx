import { useState } from 'react';
import { UserCircle, KeyRound, RefreshCw, ShieldCheck, Save, Loader2 } from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { useAuthStore } from '../stores/auth-store';

/**
 * ProfilePage — spec §2.20 /settings/profile
 * Admin profile management: display name, email, avatar, timezone,
 * password change (+2FA), regenerate backup codes (+2FA), reset TOTP
 * (+password+recovery phrase).
 */
export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const [displayName, setDisplayName] = useState(user?.username ?? 'admin');
  const [email, setEmail] = useState('');
  const [timezone, setTimezone] = useState('Asia/Kolkata');
  const [saving, setSaving] = useState(false);

  const [pwOpen, setPwOpen] = useState(false);
  const [totpOpen, setTotpOpen] = useState(false);
  const [backupOpen, setBackupOpen] = useState(false);

  const save = async () => {
    setSaving(true);
    await new Promise((r) => setTimeout(r, 400));
    setSaving(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader icon={<UserCircle size={16} />} title="Profile" subtitle="Admin identity, security, and account actions" />

      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={sectionTitle}>Identity</h3>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center', marginTop: 14 }}>
            <div style={{ width: 68, height: 68, borderRadius: '50%', display: 'grid', placeItems: 'center', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', color: '#fff', fontSize: 26, fontWeight: 800 }}>
              {displayName.charAt(0).toUpperCase()}
            </div>
            <button style={chipBtn}>Upload avatar (local only)</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginTop: 18 }}>
            <Field label="Display name"><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} style={input} /></Field>
            <Field label="Email (optional)"><input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="[email]" style={input} /></Field>
            <Field label="Timezone">
              <select value={timezone} onChange={(e) => setTimezone(e.target.value)} style={input}>
                {['Asia/Kolkata', 'Asia/Dubai', 'America/New_York', 'UTC'].map((tz) => <option key={tz}>{tz}</option>)}
              </select>
            </Field>
          </div>
          <button onClick={save} disabled={saving} style={{ ...primaryBtn, marginTop: 16 }}>
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </BentoCard>

      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={sectionTitle}>Security</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginTop: 14 }}>
            <ActionTile icon={<KeyRound size={14} />} title="Change password" blurb="Current + new + 2FA re-entry" onClick={() => setPwOpen(true)} />
            <ActionTile icon={<RefreshCw size={14} />} title="Regenerate backup codes" blurb="Requires 2FA · old codes invalidated" onClick={() => setBackupOpen(true)} />
            <ActionTile icon={<ShieldCheck size={14} />} title="Reset TOTP" blurb="Requires password + recovery phrase" onClick={() => setTotpOpen(true)} />
          </div>
        </div>
      </BentoCard>

      {/* Simple reauth modals */}
      {pwOpen && (
        <ReauthModal
          title="Change password"
          fields={[
            { key: 'current', label: 'Current password', type: 'password' },
            { key: 'next', label: 'New password', type: 'password' },
            { key: 'confirm', label: 'Confirm new password', type: 'password' },
            { key: 'totp', label: 'TOTP code', type: 'text' },
          ]}
          onClose={() => setPwOpen(false)}
        />
      )}
      {backupOpen && (
        <ReauthModal
          title="Regenerate backup codes"
          blurb="Old codes will stop working immediately."
          fields={[{ key: 'totp', label: 'TOTP code', type: 'text' }]}
          onClose={() => setBackupOpen(false)}
        />
      )}
      {totpOpen && (
        <ReauthModal
          title="Reset TOTP"
          blurb="Paste your 12-word recovery phrase to reset the second factor."
          fields={[
            { key: 'password', label: 'Password', type: 'password' },
            { key: 'phrase', label: 'Recovery phrase (12 words)', type: 'text' },
          ]}
          onClose={() => setTotpOpen(false)}
        />
      )}
    </div>
  );
}

function ActionTile({ icon, title, blurb, onClick }: { icon: React.ReactNode; title: string; blurb: string; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      textAlign: 'left', padding: 16, borderRadius: 'var(--r-md)',
      background: 'var(--surface-3)', border: '1px solid var(--line-2)',
      color: 'var(--fg-primary)', cursor: 'pointer',
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <span style={{ display: 'grid', placeItems: 'center', width: 26, height: 26, borderRadius: 'var(--r-sm)', background: 'color-mix(in srgb, var(--accent) 14%, transparent)', color: 'var(--accent-2)' }}>{icon}</span>
        <strong style={{ fontSize: 12, fontWeight: 700 }}>{title}</strong>
      </span>
      <span style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{blurb}</span>
    </button>
  );
}

function ReauthModal({
  title, blurb, fields, onClose,
}: { title: string; blurb?: string; fields: { key: string; label: string; type: string }[]; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const complete = fields.every((f) => values[f.key]);

  return (
    <div onClick={onClose} role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'grid', placeItems: 'center', background: 'var(--scrim)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
      <div onClick={(e) => e.stopPropagation()} className="lt-glass" style={{ width: '100%', maxWidth: 420, padding: 24, borderRadius: 'var(--r-lg)', border: '1px solid var(--line-2)', boxShadow: 'var(--elev-3)' }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>{title}</h3>
        {blurb && <p style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 4 }}>{blurb}</p>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
          {fields.map((f) => (
            <Field key={f.key} label={f.label}>
              <input
                type={f.type}
                value={values[f.key] ?? ''}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                style={input}
              />
            </Field>
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
          <button onClick={onClose} style={chipBtn}>Cancel</button>
          <button onClick={onClose} disabled={!complete} style={{ ...primaryBtn, opacity: complete ? 1 : 0.5, cursor: complete ? 'pointer' : 'not-allowed' }}>Confirm</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
      {children}
    </label>
  );
}

const input: React.CSSProperties = {
  padding: '9px 11px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
};
const sectionTitle: React.CSSProperties = { fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 };
const chipBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
};
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px',
  borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer',
  boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
};
