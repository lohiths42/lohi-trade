/**
 * ResearchShell — the dedicated layout for the Lohi-Research product.
 *
 * Quartr-inspired identity:
 *   • Pure black-and-white chrome. No gradient fills, no rounded-corner
 *     chips, no colored accents in the shell itself — company brands and
 *     charts carry the color, per Quartr's stated brand principle.
 *   • Editorial masthead bar: a wordmark with a serif "Edge"-style
 *     secondary mark and a wide-tracking kicker.
 *   • Hairline dividers, not shadows.
 *   • A thin left sidebar with uppercase nav groups and a monochrome
 *     underline on the active route — mirrors the Quartr Pro sidebar.
 *
 * Also sets `<html data-surface="research">` via the mode store so the
 * surface-scoped tokens in `research-theme.css` apply globally under this
 * tree.
 */

import { useEffect, type ReactNode } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  BookOpen,
  Bookmark,
  Compass,
  FileText,
  LayoutGrid,
  Lightbulb,
  LogOut,
  MessageSquare,
  Newspaper,
  Search,
  Shield,
  Workflow,
} from 'lucide-react';
import { useAppModeStore } from '../../stores/mode-store';
import { useAuthStore } from '../../stores/auth-store';
import { useThemeStore } from '../../stores/theme-store';
import ModeSwitcher from '../shared/ModeSwitcher';
import LohiAvatarResearch from './LohiAvatarResearch';

interface NavItem {
  label: string;
  to: string;
  icon: ReactNode;
}
interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Research',
    items: [
      { label: 'Feed', to: '/research', icon: <Newspaper size={14} /> },
      { label: 'Ideas', to: '/research/ideas', icon: <Lightbulb size={14} /> },
      { label: 'Sectors', to: '/research/sectors', icon: <LayoutGrid size={14} /> },
      { label: 'Themes', to: '/research/themes', icon: <Compass size={14} /> },
      { label: 'Coverage', to: '/research/coverage', icon: <Bookmark size={14} /> },
    ],
  },
  {
    label: 'Workspace',
    items: [
      { label: 'Chat', to: '/research/chat', icon: <MessageSquare size={14} /> },
      { label: 'Briefs', to: '/research/briefs', icon: <FileText size={14} /> },
      { label: 'Filings', to: '/research/filings', icon: <BookOpen size={14} /> },
    ],
  },
  {
    label: 'Governance',
    items: [
      { label: 'Architecture', to: '/research/architecture', icon: <Workflow size={14} /> },
      { label: 'Refusal policy', to: '/research/policy', icon: <Shield size={14} /> },
    ],
  },
];

export default function ResearchShell() {
  const setSurface = useAppModeStore((s) => s.setSurface);
  const surface = useAppModeStore((s) => s.surface);
  const authUser = useAuthStore((s) => s.user);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const theme = useThemeStore((s) => s.theme);
  const location = useLocation();
  const navigate = useNavigate();

  // Any mount of a `/research/*` route implies the user is in the Research
  // surface, even if they arrived via a direct link without the switcher.
  useEffect(() => {
    if (surface !== 'research') setSurface('research');
  }, [surface, setSurface]);

  return (
    <div
      className="research-shell"
      data-theme={theme}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
        background: 'var(--surface-0)',
        color: 'var(--fg-primary)',
      }}
    >
      {/* ── Masthead ─ newspaper-style, pure monochrome ───────────────── */}
      <header
        style={{
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 20,
          padding: '14px 24px',
          background: 'var(--surface-1)',
          borderBottom: '1px solid var(--line-3)',
        }}
      >
        <div
          onClick={() => navigate('/research')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            cursor: 'pointer',
            minWidth: 0,
          }}
        >
          {/* Q-mark — a literal square with a filled quarter-arc: as close
              to Quartr's Q-mark silhouette as pure SVG allows. */}
          <QMark />

          <div
            className="qr-serif"
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: '-0.02em',
              color: 'var(--fg-primary)',
              lineHeight: 1,
            }}
          >
            Lohi Research
          </div>

          <span
            className="qr-kicker qr-kicker--edge"
            style={{ margin: 0 }}
          >
            Edge · beta
          </span>
        </div>

        <div style={{ flex: 1 }} />

        {/* Inline search — underline-only, Quartr style */}
        <button
          onClick={() => navigate('/research/chat')}
          style={{
            all: 'unset',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 10,
            padding: '6px 0',
            color: 'var(--fg-muted)',
            fontSize: 13,
            cursor: 'pointer',
            borderBottom: '1px solid var(--line-2)',
            minWidth: 260,
          }}
        >
          <Search size={13} aria-hidden />
          <span>Ask anything about a company…</span>
          <span style={{ flex: 1 }} />
          <span
            style={{
              fontSize: 10,
              color: 'var(--fg-muted)',
              padding: '1px 6px',
              border: '1px solid var(--line-2)',
              borderRadius: 2,
              fontFamily: 'ui-monospace, monospace',
            }}
          >
            /
          </span>
        </button>

        <ModeSwitcher />
      </header>

      {/* ── Sidebar + content row ─────────────────────────────────────── */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <aside
          style={{
            width: 232,
            flexShrink: 0,
            borderRight: '1px solid var(--line-2)',
            background: 'var(--surface-1)',
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
          }}
        >
          <nav
            aria-label="Research navigation"
            style={{
              flex: 1,
              padding: '20px 14px',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: 22,
            }}
          >
            {NAV_GROUPS.map((group) => (
              <div key={group.label}>
                <p className="qr-kicker" style={{ padding: '0 12px', margin: '0 0 8px' }}>
                  {group.label}
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {group.items.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.to === '/research'}
                      className="qr-nav-link"
                    >
                      <span style={{ color: 'var(--fg-muted)' }}>{item.icon}</span>
                      <span>{item.label}</span>
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          <div
            style={{
              padding: '16px 14px 0',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <div style={{ flexShrink: 0, width: 44, height: 44 * 1.35 }}>
              <LohiAvatarResearch size="sm" mood="focused" />
            </div>
            <div style={{ minWidth: 0 }}>
              <p className="qr-kicker" style={{ margin: 0 }}>
                Research companion
              </p>
              <p
                className="qr-serif"
                style={{
                  margin: '2px 0 0',
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--fg-primary)',
                  lineHeight: 1.1,
                }}
              >
                Lohi · Edge
              </p>
              <p
                style={{
                  margin: '2px 0 0',
                  fontSize: 10,
                  color: 'var(--fg-muted)',
                }}
              >
                Reading the tape, silently
              </p>
            </div>
          </div>

          <div
            style={{
              padding: '14px 16px',
              borderTop: '1px solid var(--line-2)',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <div
              aria-hidden
              style={{
                width: 28,
                height: 28,
                borderRadius: 0,
                background: 'var(--fg-primary)',
                color: 'var(--surface-2)',
                display: 'grid',
                placeItems: 'center',
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.02em',
              }}
            >
              {(authUser?.username ?? 'A')[0].toUpperCase()}
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <p style={{ margin: 0, fontSize: 12, fontWeight: 600, color: 'var(--fg-primary)' }}>
                {authUser?.username ?? 'guest'}
              </p>
              <p className="qr-kicker" style={{ margin: 0, letterSpacing: '0.1em' }}>
                Research
              </p>
            </div>
            <button
              aria-label="Sign out"
              onClick={() => clearAuth()}
              style={{
                all: 'unset',
                padding: 6,
                cursor: 'pointer',
                color: 'var(--fg-muted)',
              }}
            >
              <LogOut size={13} />
            </button>
          </div>
        </aside>

        <main
          key={location.pathname}
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            overflowY: 'auto',
            padding: '32px 40px 64px',
            background: 'var(--surface-0)',
          }}
        >
          <div style={{ maxWidth: 1240, margin: '0 auto' }}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/**
 * Monochrome Q-mark — evocative of Quartr's Q, never a direct reproduction.
 * A black square (or white in dark mode) with a negative-space quarter
 * in the upper-right corner.
 */
function QMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      role="img"
      aria-label="Lohi Research"
      width={size}
      height={size}
      viewBox="0 0 28 28"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <rect
        x={0}
        y={0}
        width={28}
        height={28}
        rx={2}
        fill="var(--fg-primary)"
      />
      <path
        d="M28 0 V14 A14 14 0 0 0 14 0 Z"
        fill="var(--surface-1)"
      />
      {/* Small descender — the "tail" of the Q, as a 3px rule. */}
      <rect
        x={20}
        y={20}
        width={6}
        height={2}
        fill="var(--fg-primary)"
        transform="rotate(-45 23 21)"
      />
    </svg>
  );
}
