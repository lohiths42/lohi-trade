import { useState, useEffect, lazy, Suspense } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import {
  LayoutDashboard, Activity, History, Settings, AlertTriangle, Power,
  TrendingUp, FileText, Loader2, LogOut, Crosshair,
  BarChart3, Brain, FlaskConical, ClipboardList, ShoppingCart, Menu,
  Sun, Moon, Search, Wifi, WifiOff, ChevronRight, Play,
  ShieldCheck, Building2, Receipt, Link2, Globe, SlidersHorizontal, Gauge,
  MessageSquare, Workflow,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useWebSocket } from './hooks/use-websocket';
import { useFeatureGate } from './hooks/useFeatureGate';
import { useDashboardStore } from './stores/dashboard-store';
import { useAuthStore } from './stores/auth-store';
import { useThemeStore } from './stores/theme-store';
import { useOrderSoundCues } from './hooks/use-order-sound-cues';
import { api } from './lib/api-client';
import ToastContainer from './components/shared/Toast';
import CommandPalette from './components/shared/CommandPalette';
import NotificationCenter from './components/shared/NotificationCenter';
import PaperTradeModal from './components/shared/PaperTradeModal';
import PageTransition from './components/shared/PageTransition';
import ChatbotPanel from './components/chatbot/ChatbotPanel';
import SessionExpiredModal from './components/shared/SessionExpiredModal';
import ModeBanner from './components/shared/ModeBanner';
import ModeSwitcher from './components/shared/ModeSwitcher';
import LohiAvatar from './components/onboarding/LohiAvatar';
import { registerShortcuts } from './lib/shortcut-manager';
import type { PaperTradingStatus } from './lib/types';
import { useOnboarding } from './hooks/use-onboarding';
import './styles/onboarding.css';

const WalkthroughOverlay = lazy(() => import('./components/onboarding/WalkthroughOverlay'));

/* ─── Nav groups ─────────────────────────────────────────────────────────── */
const NAV_GROUPS = [
  {
    label: 'Overview',
    items: [
      { icon: LayoutDashboard, label: 'Dashboard', to: '/' },
      { icon: ShoppingCart, label: 'Trade', to: '/trade' },
      { icon: ClipboardList, label: 'Positions', to: '/positions' },
      { icon: ShoppingCart, label: 'Orders', to: '/orders' },
    ],
  },
  {
    label: 'Markets',
    items: [
      { icon: Globe, label: 'Stocks', to: '/universe' },
      { icon: SlidersHorizontal, label: 'Screener', to: '/screener', dataTour: 'screener' },
      { icon: Activity, label: 'Market Data', to: '/market-data' },
    ],
  },
  {
    label: 'Trading',
    items: [
      { icon: TrendingUp, label: 'Strategies', to: '/strategies' },
      { icon: Gauge, label: 'Algo Performance', to: '/algo-performance' },
      { icon: History, label: 'Trade History', to: '/history' },
      { icon: BarChart3, label: 'Analytics', to: '/analytics', dataTour: 'watchlist' },
      { icon: FlaskConical, label: 'Backtests', to: '/backtest' },
    ],
  },
  {
    label: 'Watchlist',
    items: [
      { icon: Activity, label: 'Watchlist & Alerts', to: '/watchlist' },
    ],
  },
  {
    label: 'System',
    items: [
      { icon: Brain, label: 'Commander', to: '/commander', dataTour: 'chatbot' },
      { icon: Crosshair, label: 'Soldier', to: '/soldier' },
      { icon: FileText, label: 'Logs & Audit', to: '/logs' },
      { icon: Activity, label: 'System Status', to: '/status' },
      { icon: Workflow, label: 'Architecture', to: '/architecture' },
      { icon: Settings, label: 'Configuration', to: '/settings' },
    ],
  },
  {
    label: 'Safety',
    items: [
      { icon: ShieldCheck, label: 'Risk & Live Mode', to: '/settings/risk' },
      { icon: Activity, label: 'Notifications', to: '/settings/notifications' },
    ],
  },
  {
    label: 'Account',
    items: [
      { icon: ShieldCheck, label: 'Verification', to: '/verification' },
      { icon: Building2, label: 'Bank Accounts', to: '/bank' },
      { icon: Receipt, label: 'Fund Transactions', to: '/funds' },
      { icon: Link2, label: 'Brokers', to: '/settings/brokers' },
      { icon: LayoutDashboard, label: 'Profile', to: '/settings/profile' },
    ],
  },
  {
    label: 'Help',
    items: [
      { icon: FileText, label: 'Help & Docs', to: '/help' },
    ],
  },
];

/* ─── Route → Feature mapping for "unconfigured" badges ──────────────────── */
const ROUTE_FEATURE_MAP: Record<string, string> = {
  '/trade': 'live_trading',
  '/orders': 'live_trading',
  '/positions': 'live_trading',
  '/market-data': 'live_market_data',
  '/settings/notifications': 'telegram_notifications',
};

/* ─── Sidebar Nav Item ───────────────────────────────────────────────────── */
const SidebarItem = ({ icon: Icon, label, to, dataTour, collapsed = false, unconfigured = false }: { icon: LucideIcon; label: string; to: string; dataTour?: string; collapsed?: boolean; unconfigured?: boolean }) => {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      data-tour={dataTour}
      title={collapsed ? label : undefined}
      aria-label={label}
      style={{ textDecoration: 'none' }}
    >
      {({ isActive }) => (
        <motion.div
          whileHover={{ x: collapsed ? 0 : 2 }}
          transition={{ duration: 0.15 }}
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            gap: collapsed ? 0 : 12,
            justifyContent: collapsed ? 'center' : 'flex-start',
            padding: collapsed ? '8px 0' : '9px 12px',
            borderRadius: 'var(--r-sm)',
            background: isActive
              ? 'color-mix(in srgb, var(--accent) 14%, transparent)'
              : 'transparent',
            color: isActive ? 'var(--fg-primary)' : 'var(--fg-secondary)',
            fontSize: 13,
            fontWeight: isActive ? 600 : 500,
            transition: 'background var(--dur-2) var(--ease-out), color var(--dur-2) var(--ease-out)',
          }}
        >
          {/* Left accent bar on active */}
          {isActive && (
            <motion.span
              layoutId="sidebar-active-bar"
              style={{
                position: 'absolute',
                left: collapsed ? 0 : -4,
                top: 8,
                bottom: 8,
                width: 3,
                borderRadius: 2,
                background: 'var(--accent-gradient)',
                boxShadow: '0 0 12px var(--accent-glow)',
              }}
            />
          )}
          <span
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              display: 'grid',
              placeItems: 'center',
              background: isActive
                ? 'color-mix(in srgb, var(--accent) 22%, transparent)'
                : 'var(--surface-3)',
              border: `1px solid ${isActive ? 'color-mix(in srgb, var(--accent) 35%, transparent)' : 'var(--line-1)'}`,
              color: isActive ? 'var(--accent-2)' : 'var(--fg-muted)',
              flexShrink: 0,
            }}
          >
            <Icon size={14} strokeWidth={2.2} />
          </span>
          {!collapsed && (
            <>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {label}
              </span>
              {unconfigured && !isActive && (
                <span
                  title="Service not configured"
                  style={{
                    fontSize: 8,
                    fontWeight: 700,
                    letterSpacing: '0.05em',
                    padding: '2px 5px',
                    borderRadius: 4,
                    background: 'color-mix(in srgb, var(--warn) 15%, transparent)',
                    color: 'var(--warn)',
                    border: '1px solid color-mix(in srgb, var(--warn) 30%, transparent)',
                    textTransform: 'uppercase',
                    whiteSpace: 'nowrap',
                  }}
                >
                  Setup
                </span>
              )}
              {isActive && (
                <ChevronRight size={12} style={{ opacity: 0.6, color: 'var(--accent-2)' }} />
              )}
            </>
          )}
          {collapsed && unconfigured && (
            <span
              aria-label="Service not configured"
              style={{
                position: 'absolute',
                top: 4,
                right: 4,
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: 'var(--warn)',
                boxShadow: '0 0 4px var(--warn)',
              }}
            />
          )}
        </motion.div>
      )}
    </NavLink>
  );
};

/* ─── Status Dot ─────────────────────────────────────────────────────────── */
const StatusDot = ({ label, status }: { label: string; status: 'healthy' | 'warning' | 'error' }) => {
  const color = status === 'healthy' ? 'var(--bull)' : status === 'warning' ? 'var(--warn)' : 'var(--bear)';
  const bg = status === 'healthy' ? 'var(--bull-soft)' : status === 'warning' ? 'var(--warn-soft)' : 'var(--bear-soft)';
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 'var(--r-pill)',
      background: bg,
      border: `1px solid ${color}`,
      borderColor: `color-mix(in srgb, ${color} 25%, transparent)`,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: color,
        boxShadow: `0 0 6px ${color}`,
      }} />
      <span style={{ fontSize: 10, fontWeight: 700, color, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {label}
      </span>
    </div>
  );
};

/* ─── Sidebar Portfolio Widget ───────────────────────────────────────────── */
function SidebarCapital() {
  const totalPnl = useDashboardStore((s) => s.totalPnl);
  const [capital, setCapital] = useState(200000);

  useEffect(() => {
    api.getConfig().then((cfg) => { if (cfg?.capital?.total) setCapital(cfg.capital.total); }).catch(() => {});
    api.getPaperTradingStatus().then((s) => { if (s.running && s.capital) setCapital(s.capital); }).catch(() => {});
  }, []);

  const currentValue = capital + totalPnl;
  const pnlPct = capital > 0 ? (totalPnl / capital) * 100 : 0;
  const barPct = Math.min(100, Math.max(0, ((capital - Math.abs(totalPnl < 0 ? totalPnl : 0)) / capital) * 100));
  const isUp = totalPnl >= 0;

  return (
    <div
      className="lt-bento"
      style={{
        padding: '14px 16px 12px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <p style={{
            fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase',
            letterSpacing: '0.14em', fontWeight: 700, margin: '0 0 4px',
          }}>
            Portfolio
          </p>
          <p className="lt-tabular" style={{
            fontSize: 18, fontWeight: 800, color: 'var(--fg-primary)',
            margin: 0, letterSpacing: '-0.02em',
          }}>
            ₹{currentValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </p>
        </div>
        <span
          className="lt-tabular"
          style={{
            padding: '3px 8px', borderRadius: 'var(--r-xs)',
            fontSize: 11, fontWeight: 800,
            background: isUp ? 'var(--bull-soft)' : 'var(--bear-soft)',
            color: isUp ? 'var(--bull)' : 'var(--bear)',
          }}
        >
          {isUp ? '+' : ''}{pnlPct.toFixed(1)}%
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 10, color: 'var(--fg-muted)', fontWeight: 600 }}>P&L</span>
        <span className="lt-tabular" style={{ fontSize: 12, fontWeight: 700, color: isUp ? 'var(--bull)' : 'var(--bear)' }}>
          {isUp ? '+' : ''}₹{totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </span>
      </div>
      <div style={{
        height: 4, borderRadius: 2, background: 'var(--line-2)', overflow: 'hidden',
      }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${barPct}%` }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          style={{
            height: '100%', borderRadius: 2,
            background: isUp
              ? 'linear-gradient(90deg, var(--accent) 0%, var(--bull) 100%)'
              : 'linear-gradient(90deg, var(--accent) 0%, var(--bear) 100%)',
            boxShadow: `0 0 10px ${isUp ? 'var(--bull-glow)' : 'var(--bear-glow)'}`,
          }}
        />
      </div>
    </div>
  );
}

/* ─── Market Status ──────────────────────────────────────────────────────── */
function getMarketStatus(): { label: string; color: string } {
  const now = new Date();
  const mins = now.getHours() * 60 + now.getMinutes();
  const day = now.getDay();
  if (day === 0 || day === 6) return { label: 'CLOSED', color: '#64748b' };
  if (mins < 555) return { label: 'PRE-OPEN', color: '#fbbf24' };
  if (mins < 930) return { label: 'OPEN', color: '#34d399' };
  return { label: 'CLOSED', color: '#64748b' };
}

/* ─── App ────────────────────────────────────────────────────────────────── */
export default function App() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const { isFeatureAvailable } = useFeatureGate();
  // Single sidebar state: `sidebarOpen` means labels are visible (264px).
  // When `false`, the rail shows only icons (64px). Works identically on
  // every viewport — on mobile the open state floats over content with
  // a scrim, on desktop it pushes content.
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    const stored = window.localStorage.getItem('lohi_sidebar_open');
    // On mobile the default is closed (icon rail); on desktop with no
    // prior preference, default to closed so the Kiro-style rail is the
    // first thing the user sees.
    if (stored === '1') return true;
    if (stored === '0') return false;
    return false;
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        'lohi_sidebar_open',
        sidebarOpen ? '1' : '0',
      );
    } catch {
      /* ignored */
    }
  }, [sidebarOpen]);

  const [confirmDialog, setConfirmDialog] = useState<{ title: string; message: string; danger?: boolean; onConfirm: () => void } | null>(null);
  const killSwitchActive = useDashboardStore((s) => s.killSwitchActive);
  const setKillSwitchActive = useDashboardStore((s) => s.setKillSwitchActive);
  const authUser = useAuthStore((s) => s.user);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [chatbotOpen, setChatbotOpen] = useState(false);
  const { status: wsStatus } = useWebSocket();
  useOrderSoundCues();
  const { isOnboarded, completeOnboarding } = useOnboarding();
  const location = useLocation();
  const showWalkthrough = !isOnboarded && location.pathname === '/';

  // Broker connection status (wired to real API data)
  const [brokerStatus, setBrokerStatus] = useState<'healthy' | 'warning' | 'error'>('healthy');

  useEffect(() => {
    const fetchBrokerStatus = () => {
      api.getBrokersStatus().then((res) => {
        const connected = res.brokers.filter((b) => b.status === 'connected').length;
        const expired = res.brokers.filter((b) => b.status === 'token_expired').length;
        if (connected > 0) setBrokerStatus('healthy');
        else if (expired > 0) setBrokerStatus('warning');
        else setBrokerStatus('error');
      }).catch(() => {});
    };
    fetchBrokerStatus();
    const interval = setInterval(fetchBrokerStatus, 30_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    return registerShortcuts([
      { key: 'k', ctrl: true, description: 'Open command palette', action: () => setPaletteOpen(true) },
      { key: 'Escape', description: 'Close palette', action: () => setPaletteOpen(false), ignoreInInput: false },
      { key: 'b', ctrl: true, description: 'Open Trade ticket (Buy)', action: () => { window.location.href = '/trade'; } },
      { key: 's', ctrl: true, description: 'Open Trade ticket (Sell)', action: () => { window.location.href = '/trade'; } },
      { key: '?', description: 'Toggle keyboard shortcuts overlay', action: () => { /* handled by ShortcutOverlay if installed */ }, ignoreInInput: true },
    ]);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const handleKillSwitch = async () => {
    if (killSwitchActive) {
      setConfirmDialog({
        title: 'Resume Trading',
        message: 'Are you sure you want to resume trading? Ensure risk checks are cleared.',
        onConfirm: async () => {
          setConfirmDialog(null);
          try { const res = await api.toggleKillSwitch(); setKillSwitchActive(res.active); } catch { setKillSwitchActive(false); }
        },
      });
    } else {
      setConfirmDialog({
        title: 'EMERGENCY: ACTIVATE KILL SWITCH',
        message: 'This will halt all algorithms and cancel pending orders immediately.',
        danger: true,
        onConfirm: async () => {
          setConfirmDialog(null);
          try { const res = await api.toggleKillSwitch(); setKillSwitchActive(res.active); } catch { setKillSwitchActive(true); }
        },
      });
    }
  };

  const [paperStatus, setPaperStatus] = useState<PaperTradingStatus>({
    running: false, startedAt: null, capital: null, days: null, speed: null, pid: null, useRealData: null,
  });
  const [paperLoading, setPaperLoading] = useState(false);
  const [showPaperModal, setShowPaperModal] = useState(false);

  useEffect(() => {
    const poll = () => api.getPaperTradingStatus().then(setPaperStatus).catch(() => {});
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!paperStatus.running) return;
    const refresh = setInterval(() => {
      api.getStrategyPerformance().then((strategies) => {
        const totPnl = strategies.reduce((sum, s) => sum + s.totalPnl, 0);
        const totTrades = strategies.reduce((sum, s) => sum + s.tradesCount, 0);
        const totWins = strategies.reduce((sum, s) => sum + Math.round(s.winRate * s.tradesCount / 100), 0);
        const wr = totTrades > 0 ? (totWins / totTrades) * 100 : 0;
        useDashboardStore.setState({ totalPnl: Math.round(totPnl * 100) / 100, tradesCount: totTrades, winRate: Math.round(wr * 10) / 10 });
      }).catch(() => {});
    }, 5000);
    return () => clearInterval(refresh);
  }, [paperStatus.running]);

  const handleStartPaper = async (cfg: { capital: number; days: number; speed: number; useRealData: boolean }) => {
    setPaperLoading(true);
    try {
      const res = await api.startPaperTrading({ capital: cfg.capital, days: cfg.days, speed: cfg.speed, useRealData: cfg.useRealData });
      setPaperStatus(res);
    } catch (e: any) {
      alert(e?.detail || e?.message || 'Failed to start simulation');
    } finally {
      setPaperLoading(false);
    }
  };

  const handleStopPaper = () => {
    setConfirmDialog({
      title: 'Stop Paper Trading',
      message: 'Stop the paper trading simulation? Current progress will be saved.',
      onConfirm: async () => {
        setConfirmDialog(null);
        setPaperLoading(true);
        try { const res = await api.stopPaperTrading(); setPaperStatus(res); } catch { /* ignore */ }
        finally { setPaperLoading(false); }
      },
    });
  };

  const mktStatus = getMarketStatus();

  return (
    <div
      data-theme={theme}
      className="flex flex-col h-screen overflow-hidden font-sans"
      style={{
        background: 'var(--surface-0)',
        color: 'var(--fg-primary)',
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, sans-serif',
      }}
    >
      {/* Ambient background orbs — subtle, performant */}
      <div
        aria-hidden
        style={{
          position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
          overflow: 'hidden',
        }}
      >
        <div style={{
          position: 'absolute', top: '-15%', left: '-10%',
          width: 600, height: 600, borderRadius: '50%',
          background: 'radial-gradient(circle, color-mix(in srgb, var(--accent) 12%, transparent) 0%, transparent 70%)',
          filter: 'blur(60px)',
        }} />
        <div style={{
          position: 'absolute', bottom: '-25%', right: '-15%',
          width: 700, height: 700, borderRadius: '50%',
          background: 'radial-gradient(circle, color-mix(in srgb, var(--accent-2) 10%, transparent) 0%, transparent 70%)',
          filter: 'blur(80px)',
        }} />
      </div>

      {/* ── Top Brand Bar ────────────────────────────────────────── */}
      <div
        style={{
          position: 'relative', zIndex: 30,
          height: 56, flexShrink: 0,
          display: 'flex', alignItems: 'center', gap: 16,
          padding: '0 20px',
          background: 'color-mix(in srgb, var(--surface-1) 72%, transparent)',
          backdropFilter: 'saturate(140%) blur(16px)',
          WebkitBackdropFilter: 'saturate(140%) blur(16px)',
          borderBottom: '1px solid var(--line-2)',
        }}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setSidebarOpen((v) => !v);
          }}
          aria-label={sidebarOpen ? 'Collapse navigation' : 'Expand navigation'}
          aria-expanded={sidebarOpen}
          aria-controls="app-sidebar"
          style={{
            padding: 8, borderRadius: 'var(--r-sm)',
            color: 'var(--fg-secondary)',
            background: 'var(--surface-2)', border: '1px solid var(--line-2)',
            cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Menu size={18} />
        </button>

        {/* Brand lockup */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 10,
            display: 'grid', placeItems: 'center', flexShrink: 0,
            background: 'var(--accent-gradient)',
            boxShadow: '0 6px 18px var(--accent-glow)',
          }}>
            <Activity size={16} color="#fff" strokeWidth={2.4} />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, minWidth: 0 }}>
            <span style={{
              fontSize: 17, fontWeight: 900, letterSpacing: '-0.02em',
              lineHeight: 1, color: 'var(--fg-primary)',
            }}>
              LOHI<span style={{ color: 'var(--accent-2)' }}>-TRADE</span>
            </span>
            <span style={{
              fontSize: 9, fontWeight: 700, letterSpacing: '0.12em',
              padding: '2px 7px', borderRadius: 4,
              background: 'color-mix(in srgb, var(--accent) 14%, transparent)',
              color: 'var(--accent-2)',
              textTransform: 'uppercase',
            }}>
              Open Source
            </span>
            <span className="hidden sm:inline" style={{
              fontSize: 10, color: 'var(--fg-muted)',
              fontWeight: 600, letterSpacing: '0.08em',
            }}>
              ALGO TRADING SYSTEM
            </span>
          </div>
        </div>

        {/* Spacer + live market ticker on the right */}
        <div style={{ flex: 1 }} />
        <div className="hidden md:flex" style={{ alignItems: 'center', gap: 10 }}>
          <div
            className="lt-glass"
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '5px 12px', borderRadius: 'var(--r-pill)',
            }}
          >
            <span style={{ fontSize: 9, color: 'var(--fg-muted)', fontWeight: 700, letterSpacing: '0.1em' }}>
              NIFTY 50
            </span>
            <span className="lt-tabular" style={{ fontSize: 13, fontWeight: 800, color: 'var(--fg-primary)' }}>
              21,456.30
            </span>
            <span className="lt-tabular" style={{
              fontSize: 11, fontWeight: 700, color: 'var(--bull)',
              padding: '1px 6px', borderRadius: 4, background: 'var(--bull-soft)',
            }}>
              +0.45%
            </span>
          </div>
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 11px', borderRadius: 'var(--r-pill)',
              background: `color-mix(in srgb, ${mktStatus.color} 12%, transparent)`,
              border: `1px solid color-mix(in srgb, ${mktStatus.color} 28%, transparent)`,
            }}
          >
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: mktStatus.color, boxShadow: `0 0 8px ${mktStatus.color}`,
            }} />
            <span style={{ fontSize: 10, fontWeight: 800, color: mktStatus.color, letterSpacing: '0.1em' }}>
              {mktStatus.label}
            </span>
          </div>

          {/* Mode switcher — mirrors Research shell's top-right placement */}
          <ModeSwitcher />
        </div>

        {/* Mobile: keep the mode switcher visible even when the ticker is hidden */}
        <div className="md:hidden">
          <ModeSwitcher />
        </div>
      </div>

      {/* ── Row: Sidebar + Main Content ──────────────────────────── */}
      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0, position: 'relative', zIndex: 1 }}>

      {/* ── Sidebar ──────────────────────────────────────────────────── */}
      {/* Single-component sidebar. Width animates between 64 (icon rail)
          and 264 (full nav) based on `sidebarOpen`. On every viewport.
          On mobile (< md) when open, a scrim appears over the main pane
          so tapping outside closes the sidebar; but the sidebar itself
          stays in its normal DOM position — no absolute/fixed overlay
          trick, so the hamburger button is always reachable and visible. */}
      <motion.div
        id="app-sidebar"
        className="relative flex flex-col z-40 lt-scroll"
        initial={false}
        animate={{ width: sidebarOpen ? 264 : 64 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        style={{
          height: '100%',
          flexShrink: 0,
          background: 'color-mix(in srgb, var(--surface-1) 80%, transparent)',
          backdropFilter: 'saturate(140%) blur(18px)',
          WebkitBackdropFilter: 'saturate(140%) blur(18px)',
          borderRight: '1px solid var(--line-2)',
          overflow: 'hidden',
        }}
      >
          {/* Lohi companion card — collapses to avatar-only when slim */}
          <div style={{ padding: !sidebarOpen ? '12px 8px 10px' : '14px 14px 10px' }}>
            <div
              className="lt-bento"
              style={{
                padding: !sidebarOpen ? '8px' : '12px 14px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: !sidebarOpen ? 'center' : 'flex-start',
                gap: 12,
              }}
            >
              <div
                style={{
                  flexShrink: 0,
                  width: !sidebarOpen ? 32 : 48,
                  height: (!sidebarOpen ? 32 : 48) * 1.35,
                  display: 'grid',
                  placeItems: 'center',
                }}
              >
                <LohiAvatar size="sm" speaking mood="happy" />
              </div>
              {sidebarOpen && (
                <div style={{ minWidth: 0 }}>
                  <p
                    style={{
                      fontSize: 9,
                      fontWeight: 800,
                      letterSpacing: '0.14em',
                      textTransform: 'uppercase',
                      color: 'var(--fg-muted)',
                      margin: 0,
                    }}
                  >
                    Quant Companion
                  </p>
                  <p
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: 'var(--fg-primary)',
                      margin: '2px 0 0',
                      letterSpacing: '-0.01em',
                    }}
                  >
                    Lohi
                  </p>
                  <p
                    style={{
                      fontSize: 10,
                      color: 'var(--accent-2)',
                      margin: '2px 0 0',
                      fontWeight: 600,
                    }}
                  >
                    Watching the book · live
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Nav */}
          <nav
            style={{
              flex: 1,
              padding: !sidebarOpen ? '4px 8px 12px' : '4px 12px 12px',
              overflowY: 'auto',
              overflowX: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              gap: !sidebarOpen ? 10 : 18,
            }}
          >
            {NAV_GROUPS.map((group) => (
              <div key={group.label}>
                {!sidebarOpen ? (
                  <div
                    aria-hidden
                    style={{
                      height: 1,
                      background: 'var(--line-2)',
                      margin: '4px 8px 6px',
                      opacity: 0.7,
                    }}
                  />
                ) : (
                  <p
                    style={{
                      fontSize: 10,
                      fontWeight: 800,
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.16em',
                      padding: '0 12px',
                      marginBottom: 8,
                      opacity: 0.8,
                    }}
                  >
                    {group.label}
                  </p>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {group.items.map((item) => (
                    <SidebarItem
                      key={item.to}
                      icon={item.icon}
                      label={item.label}
                      to={item.to}
                      dataTour={(item as any).dataTour}
                      collapsed={!sidebarOpen}
                      unconfigured={
                        ROUTE_FEATURE_MAP[item.to]
                          ? !isFeatureAvailable(ROUTE_FEATURE_MAP[item.to])
                          : false
                      }
                    />
                  ))}
                </div>
              </div>
            ))}
          </nav>

          {/* Bottom: Portfolio + User */}
          <div
            style={{
              padding: !sidebarOpen ? '12px 8px 16px' : '12px 14px 16px',
              borderTop: '1px solid var(--line-2)',
            }}
          >
            {sidebarOpen && <SidebarCapital />}

            <button
              onClick={() => clearAuth()}
              aria-label="Sign out"
              title={!sidebarOpen ? (authUser?.username ?? 'admin') : undefined}
              style={{
                marginTop: !sidebarOpen ? 0 : 10,
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: !sidebarOpen ? 'center' : 'space-between',
                padding: !sidebarOpen ? '8px 6px' : '8px 10px',
                borderRadius: 'var(--r-sm)',
                background: 'transparent',
                border: '1px solid transparent',
                cursor: 'pointer',
                transition:
                  'background var(--dur-2) var(--ease-out), border-color var(--dur-2) var(--ease-out)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--surface-3)';
                e.currentTarget.style.borderColor = 'var(--line-2)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent';
                e.currentTarget.style.borderColor = 'transparent';
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: !sidebarOpen ? 0 : 10,
                }}
              >
                <div
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: 8,
                    background: 'var(--accent-gradient)',
                    display: 'grid',
                    placeItems: 'center',
                    boxShadow: '0 4px 10px var(--accent-glow)',
                    flexShrink: 0,
                  }}
                >
                  <span style={{ fontSize: 12, fontWeight: 800, color: '#fff' }}>
                    {(authUser?.username ?? 'A')[0].toUpperCase()}
                  </span>
                </div>
                {sidebarOpen && (
                  <div style={{ textAlign: 'left' }}>
                    <p
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: 'var(--fg-primary)',
                        margin: 0,
                      }}
                    >
                      {authUser?.username ?? 'admin'}
                    </p>
                    <p
                      style={{
                        fontSize: 10,
                        color: 'var(--fg-muted)',
                        margin: 0,
                      }}
                    >
                      Trader
                    </p>
                  </div>
                )}
              </div>
              {sidebarOpen && <LogOut size={14} color="var(--fg-muted)" />}
            </button>

            {/* Open Source footer — hidden on the slim rail */}
            {sidebarOpen && (
              <div
                style={{
                  marginTop: 12,
                  paddingTop: 10,
                  borderTop: '1px solid var(--line-1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 6,
                  flexWrap: 'wrap',
                  fontSize: 9,
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  color: 'var(--fg-muted)',
                }}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 5,
                      height: 5,
                      borderRadius: '50%',
                      background: 'var(--accent-2)',
                    }}
                  />
                  Open Source
                </span>
                <span style={{ opacity: 0.4 }}>·</span>
                <a
                  href="https://www.gnu.org/licenses/agpl-3.0.html"
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: 'inherit', textDecoration: 'none' }}
                >
                  AGPL-3.0
                </a>
                <span style={{ opacity: 0.4 }}>·</span>
                <a
                  href="https://github.com/lohi-trade/lohi-trade-oss"
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: 'inherit', textDecoration: 'none' }}
                >
                  GitHub
                </a>
              </div>
            )}
          </div>
        </motion.div>

      {/* ── Main Content ─────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden relative">

        {/* Kill Switch Overlay */}
        <AnimatePresence>
          {killSwitchActive && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 pointer-events-none z-50 flex items-center justify-center"
              style={{
                border: '12px solid color-mix(in srgb, var(--bear) 50%, transparent)',
                boxShadow: 'inset 0 0 120px color-mix(in srgb, var(--bear) 45%, transparent)',
                backdropFilter: 'blur(3px)',
              }}
            >
              <div
                className="lt-bento"
                style={{
                  padding: 32, textAlign: 'center',
                  background: 'color-mix(in srgb, var(--bear) 18%, var(--surface-2))',
                  border: '1px solid var(--bear)',
                  boxShadow: 'var(--elev-3), 0 0 60px var(--bear-glow)',
                }}
              >
                <AlertTriangle size={56} color="var(--bear)" className="mx-auto mb-4 animate-bounce" />
                <h1 style={{ fontSize: 32, fontWeight: 900, color: '#fff', margin: '0 0 6px', letterSpacing: '-0.02em' }}>
                  SYSTEM HALTED
                </h1>
                <p style={{ color: '#fecaca', fontSize: 15, margin: 0 }}>
                  Kill Switch Engaged. All Orders Cancelled.
                </p>
                <div style={{ marginTop: 24 }}>
                  <button
                    onClick={() => setKillSwitchActive(false)}
                    className="pointer-events-auto"
                    style={{
                      padding: '10px 22px', borderRadius: 'var(--r-sm)',
                      background: 'var(--bear)', border: 'none', color: '#fff',
                      fontWeight: 700, fontSize: 13, cursor: 'pointer',
                      boxShadow: '0 6px 16px var(--bear-glow)',
                    }}
                  >
                    Resume Operations
                  </button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Top Header ───────────────────────────────────────────── */}
        <header style={{
          height: 58, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 20px', zIndex: 10,
          background: 'color-mix(in srgb, var(--surface-1) 72%, transparent)',
          backdropFilter: 'saturate(140%) blur(16px)',
          WebkitBackdropFilter: 'saturate(140%) blur(16px)',
          borderBottom: '1px solid var(--line-2)',
        }}>
          {/* Left: System dots */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="hidden xl:flex items-center gap-1.5">
              <span data-tour="broker"><StatusDot label="Broker" status={killSwitchActive ? 'error' : brokerStatus} /></span>
              <StatusDot label="Redis" status="healthy" />
              <StatusDot label="AI" status="healthy" />
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '4px 10px', borderRadius: 'var(--r-pill)',
                background: wsStatus === 'connected' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                border: `1px solid color-mix(in srgb, ${wsStatus === 'connected' ? 'var(--bull)' : 'var(--bear)'} 25%, transparent)`,
              }}>
                {wsStatus === 'connected'
                  ? <Wifi size={11} color="var(--bull)" />
                  : <WifiOff size={11} color="var(--bear)" />}
                <span style={{
                  fontSize: 10, fontWeight: 700,
                  color: wsStatus === 'connected' ? 'var(--bull)' : 'var(--bear)',
                  letterSpacing: '0.08em', textTransform: 'uppercase',
                }}>
                  WS
                </span>
              </div>
            </div>
          </div>

          {/* Right: actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={() => setPaletteOpen(true)}
              className="hidden lg:flex"
              style={{
                alignItems: 'center', gap: 8,
                padding: '7px 12px', borderRadius: 'var(--r-sm)',
                background: 'var(--surface-2)', border: '1px solid var(--line-2)',
                color: 'var(--fg-muted)', cursor: 'pointer',
                transition: 'border-color var(--dur-2) var(--ease-out), color var(--dur-2) var(--ease-out)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--accent) 30%, var(--line-2))'; e.currentTarget.style.color = 'var(--fg-secondary)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--line-2)'; e.currentTarget.style.color = 'var(--fg-muted)'; }}
            >
              <Search size={13} />
              <span style={{ fontSize: 12 }}>Search</span>
              <kbd style={{
                fontSize: 9, padding: '1px 5px', borderRadius: 4,
                background: 'var(--surface-3)', border: '1px solid var(--line-2)',
                color: 'var(--fg-muted)', fontFamily: 'ui-monospace, monospace',
              }}>⌘K</kbd>
            </button>

            <NotificationCenter />

            <button
              onClick={() => setChatbotOpen((v) => !v)}
              aria-label="Ask Lohi"
              title="Ask Lohi"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                padding: '7px 12px', borderRadius: 'var(--r-sm)',
                background: chatbotOpen ? 'var(--accent-gradient)' : 'var(--surface-2)',
                border: chatbotOpen ? 'none' : '1px solid var(--line-2)',
                color: chatbotOpen ? '#fff' : 'var(--fg-secondary)',
                cursor: 'pointer',
                boxShadow: chatbotOpen ? '0 4px 12px var(--accent-glow)' : 'none',
                transition: 'all var(--dur-2) var(--ease-out)',
                fontWeight: 700, fontSize: 12,
              }}
            >
              <MessageSquare size={13} />
              <span className="hidden lg:inline">Ask Lohi</span>
            </button>

            <button
              onClick={toggleTheme}
              aria-label="Toggle theme"
              style={{
                padding: 8, borderRadius: 'var(--r-sm)',
                background: 'var(--surface-2)', border: '1px solid var(--line-2)',
                color: 'var(--fg-secondary)', cursor: 'pointer', display: 'flex',
                transition: 'border-color var(--dur-2) var(--ease-out)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--accent) 30%, var(--line-2))'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--line-2)'; }}
            >
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </button>

            <div className="hidden md:block" style={{ textAlign: 'right', padding: '0 4px', lineHeight: 1 }}>
              <p className="lt-tabular" style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>
                {currentTime.toLocaleTimeString()}
              </p>
              <p style={{
                fontSize: 9, color: 'var(--fg-muted)',
                margin: '2px 0 0', letterSpacing: '0.08em', textTransform: 'uppercase',
              }}>
                {currentTime.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
              </p>
            </div>

            <div style={{ width: 1, height: 28, background: 'var(--line-2)' }} />

            {paperStatus.running ? (
              <button
                onClick={() => setShowPaperModal(true)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                  padding: '8px 14px', borderRadius: 'var(--r-sm)',
                  background: 'linear-gradient(135deg, #d97706, #b45309)',
                  border: 'none', color: '#fff',
                  fontWeight: 700, fontSize: 12, cursor: 'pointer',
                  boxShadow: '0 4px 14px rgba(217,119,6,0.35)',
                }}
              >
                <Loader2 size={13} className="animate-spin" />
                <span>SIM LIVE</span>
                <span className="animate-pulse" style={{ width: 6, height: 6, borderRadius: '50%', background: '#fde68a', display: 'inline-block' }} />
              </button>
            ) : (
              <button
                onClick={() => setShowPaperModal(true)}
                disabled={paperLoading}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                  padding: '8px 14px', borderRadius: 'var(--r-sm)',
                  background: 'linear-gradient(135deg, var(--bull), #00a76a)',
                  border: 'none', color: '#001f14',
                  fontWeight: 800, fontSize: 12, cursor: 'pointer',
                  boxShadow: '0 4px 14px var(--bull-glow)',
                }}
              >
                {paperLoading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} strokeWidth={3} />}
                <span>PAPER TRADE</span>
              </button>
            )}

            <button
              data-tour="kill-switch"
              onClick={handleKillSwitch}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                padding: '8px 14px', borderRadius: 'var(--r-sm)',
                background: killSwitchActive
                  ? 'var(--surface-3)'
                  : 'linear-gradient(135deg, var(--bear), #c03050)',
                border: killSwitchActive ? '1px solid var(--line-2)' : 'none',
                color: killSwitchActive ? 'var(--fg-muted)' : '#fff',
                fontWeight: 800, fontSize: 12, cursor: 'pointer',
                boxShadow: killSwitchActive ? 'none' : '0 4px 14px var(--bear-glow)',
              }}
            >
              <Power size={13} strokeWidth={3} />
              <span>{killSwitchActive ? 'HALTED' : 'KILL'}</span>
            </button>
          </div>
        </header>

        {/* Page Content */}
        <main
          className="flex-1 overflow-y-auto overflow-x-hidden lt-scroll"
          style={{ padding: '28px 28px', position: 'relative' }}
        >
          <div style={{ marginBottom: 16 }}>
            <ModeBanner />
          </div>
          <PageTransition />
        </main>
      </div>
      </div>{/* /row wrapper */}

      {/* Lohi chat panel (accessible from all pages) */}
      <ChatbotPanel open={chatbotOpen} onClose={() => setChatbotOpen(false)} />

      {/* Session expired guard (listens for 'session-expired' event from api client) */}
      <SessionExpiredModal />

      {/* Toast */}
      <ToastContainer />

      {/* Paper Trading Modal */}
      <PaperTradeModal
        open={showPaperModal}
        onClose={() => setShowPaperModal(false)}
        onStart={handleStartPaper}
        onStop={handleStopPaper}
        status={paperStatus}
        loading={paperLoading}
      />

      {/* Command Palette */}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />

      {/* Confirm Dialog */}
      {confirmDialog && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 200,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'var(--scrim)',
            backdropFilter: 'saturate(140%) blur(8px)',
            WebkitBackdropFilter: 'saturate(140%) blur(8px)',
          }}
          onClick={() => setConfirmDialog(null)}
        >
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="lt-bento"
            style={{
              padding: 28, width: 440, maxWidth: '90vw',
              border: confirmDialog.danger
                ? '1px solid color-mix(in srgb, var(--bear) 40%, transparent)'
                : '1px solid var(--line-2)',
              boxShadow: confirmDialog.danger
                ? 'var(--elev-3), 0 0 40px var(--bear-glow)'
                : 'var(--elev-3)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
              <div style={{
                width: 40, height: 40, borderRadius: 'var(--r-sm)',
                background: confirmDialog.danger ? 'var(--bear-soft)' : 'var(--warn-soft)',
                border: `1px solid ${confirmDialog.danger ? 'color-mix(in srgb, var(--bear) 30%, transparent)' : 'color-mix(in srgb, var(--warn) 30%, transparent)'}`,
                display: 'grid', placeItems: 'center',
              }}>
                <AlertTriangle size={18} color={confirmDialog.danger ? 'var(--bear)' : 'var(--warn)'} />
              </div>
              <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.01em' }}>
                {confirmDialog.title}
              </h3>
            </div>
            <p style={{ fontSize: 13, color: 'var(--fg-secondary)', lineHeight: 1.6, marginBottom: 22 }}>
              {confirmDialog.message}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button
                onClick={() => setConfirmDialog(null)}
                style={{
                  padding: '9px 18px', fontSize: 13, fontWeight: 600,
                  color: 'var(--fg-secondary)', background: 'var(--surface-3)',
                  border: '1px solid var(--line-2)', borderRadius: 'var(--r-sm)', cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDialog.onConfirm}
                style={{
                  padding: '9px 18px', fontSize: 13, fontWeight: 700, color: '#fff',
                  background: confirmDialog.danger
                    ? 'linear-gradient(135deg, var(--bear), #c03050)'
                    : 'var(--accent-gradient)',
                  borderRadius: 'var(--r-sm)', border: 'none', cursor: 'pointer',
                  boxShadow: confirmDialog.danger
                    ? '0 6px 16px var(--bear-glow)'
                    : '0 6px 16px var(--accent-glow)',
                }}
              >
                {confirmDialog.danger ? 'Activate Kill Switch' : 'Confirm'}
              </button>
            </div>
          </motion.div>
        </div>
      )}

      {/* Onboarding Walkthrough (lazy-loaded, zero bytes for returning users) */}
      {showWalkthrough && (
        <Suspense fallback={null}>
          <WalkthroughOverlay
            isOpen={showWalkthrough}
            onComplete={completeOnboarding}
            onSkip={completeOnboarding}
          />
        </Suspense>
      )}
    </div>
  );
}
