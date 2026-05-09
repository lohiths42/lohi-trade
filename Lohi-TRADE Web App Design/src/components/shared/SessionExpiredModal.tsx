import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { LockKeyhole } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../stores/auth-store';

/**
 * SessionExpiredModal — spec §2.0.5.
 *
 * Listens for a global `session-expired` event (fired by the api client
 * on 401 responses) and blocks the UI with a modal that preserves the
 * current route as ?next= so the user lands back where they were after
 * reauthenticating.
 *
 * To trigger:
 *   window.dispatchEvent(new CustomEvent('session-expired'));
 */

export default function SessionExpiredModal() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const clearAuth = useAuthStore((s) => s.clearAuth);

  useEffect(() => {
    const handler = () => {
      // Belt-and-suspenders: if the event somehow fires while we're on a
      // pre-auth route (/login, /login/2fa, /setup, /create-account), ignore
      // it. The api-client already filters these out, but in case an
      // unrelated 401 (e.g., a background poll still in flight) slips through
      // while the user is mid-login, we don't want to show a scary modal.
      const path = window.location.pathname;
      if (/^\/(login|setup|create-account)(\/|$)/.test(path)) return;
      setOpen(true);
    };
    window.addEventListener('session-expired', handler);
    return () => window.removeEventListener('session-expired', handler);
  }, []);

  const reauth = () => {
    clearAuth();
    const next = encodeURIComponent(location.pathname + location.search);
    setOpen(false);
    navigate(`/login?next=${next}`, { replace: true });
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          role="dialog"
          aria-modal="true"
          aria-label="Session expired"
          style={{
            position: 'fixed', inset: 0, zIndex: 10000,
            display: 'grid', placeItems: 'center',
            background: 'var(--scrim)',
            backdropFilter: 'saturate(140%) blur(14px)',
            WebkitBackdropFilter: 'saturate(140%) blur(14px)',
          }}
        >
          <motion.div
            initial={{ scale: 0.95, y: 8 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.97, y: 4 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="lt-glass"
            style={{
              width: '100%', maxWidth: 380,
              padding: 28, borderRadius: 'var(--r-lg)',
              border: '1px solid var(--line-2)',
              boxShadow: 'var(--elev-3)',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                width: 52, height: 52, borderRadius: '50%',
                margin: '0 auto 14px',
                display: 'grid', placeItems: 'center',
                background: 'color-mix(in srgb, var(--warn) 18%, transparent)',
                color: 'var(--warn)',
              }}
            >
              <LockKeyhole size={22} />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.02em' }}>Session expired</h2>
            <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '6px 0 18px' }}>
              You've been signed out for your safety. Sign in again to pick up where you left off.
            </p>
            <button
              onClick={reauth}
              style={{
                width: '100%', padding: '10px 16px', borderRadius: 'var(--r-sm)',
                background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
                color: '#fff', border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
                fontSize: 13, fontWeight: 600, cursor: 'pointer',
                boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
              }}
            >
              Log in
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
