/**
 * LandingPage — public marketing homepage for LOHI-TRADE.
 *
 * Design inspired by modern fintech SaaS layouts (Tradeo-style):
 *   Hero  →  Logo row  →  Feature bento  →  How it works  →
 *   Platform preview  →  Pricing  →  Testimonial  →  CTA  →  Footer
 *
 * All styling uses the app's design tokens (design-tokens.css) so it
 * inherits the dark-first fintech palette without ad-hoc colors.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import {
  Activity, ArrowRight, Check, ShieldCheck, Zap, Brain, BarChart3,
  Lock, Gauge, LineChart, TrendingUp, Sparkles, Github, Twitter, Linkedin,
  Wallet, Boxes, Layers,
} from 'lucide-react';
import { useThemeStore } from '../stores/theme-store';

/* ─── Animated gradient orb for hero backdrop ──────────────────────── */
function HeroOrbs() {
  return (
    <div aria-hidden style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
      <motion.div
        animate={{ x: [0, 40, 0], y: [0, -30, 0] }}
        transition={{ duration: 18, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          position: 'absolute', top: '-10%', left: '-10%',
          width: 520, height: 520, borderRadius: '50%',
          background: 'radial-gradient(circle, color-mix(in srgb, var(--accent) 35%, transparent) 0%, transparent 70%)',
          filter: 'blur(40px)',
        }}
      />
      <motion.div
        animate={{ x: [0, -60, 0], y: [0, 40, 0] }}
        transition={{ duration: 22, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          position: 'absolute', bottom: '-20%', right: '-10%',
          width: 620, height: 620, borderRadius: '50%',
          background: 'radial-gradient(circle, color-mix(in srgb, var(--accent-2) 28%, transparent) 0%, transparent 70%)',
          filter: 'blur(50px)',
        }}
      />
      <motion.div
        animate={{ x: [0, 30, 0], y: [0, 20, 0] }}
        transition={{ duration: 26, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          position: 'absolute', top: '30%', left: '40%',
          width: 340, height: 340, borderRadius: '50%',
          background: 'radial-gradient(circle, color-mix(in srgb, var(--bull) 20%, transparent) 0%, transparent 70%)',
          filter: 'blur(60px)',
        }}
      />
    </div>
  );
}

/* ─── Navbar ──────────────────────────────────────────────────────── */
function Navbar() {
  return (
    <header
      style={{
        position: 'sticky', top: 0, zIndex: 40,
        padding: '16px 32px',
        backdropFilter: 'saturate(140%) blur(14px)',
        WebkitBackdropFilter: 'saturate(140%) blur(14px)',
        background: 'color-mix(in srgb, var(--surface-0) 62%, transparent)',
        borderBottom: '1px solid var(--line-1)',
      }}
    >
      <div style={{ maxWidth: 1280, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
          <div style={{
            width: 34, height: 34, borderRadius: 10,
            background: 'var(--accent-gradient)',
            boxShadow: '0 8px 24px var(--accent-glow)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Activity size={17} color="#fff" strokeWidth={2.4} />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontWeight: 900, fontSize: 17, letterSpacing: '-0.02em', color: 'var(--fg-primary)' }}>
              LOHI<span style={{ color: 'var(--accent-2)' }}>-TRADE</span>
            </span>
            <span style={{
              fontSize: 9, fontWeight: 700, letterSpacing: '0.12em',
              padding: '2px 7px', borderRadius: 4,
              background: 'color-mix(in srgb, var(--accent) 16%, transparent)',
              color: 'var(--accent-2)',
            }}>
              OSS
            </span>
          </div>
        </Link>

        <nav style={{ display: 'flex', alignItems: 'center', gap: 28 }} className="hidden md:flex">
          {['Features', 'How it works', 'Pricing', 'Docs'].map((item) => (
            <a
              key={item}
              href={`#${item.toLowerCase().replace(/\s+/g, '-')}`}
              style={{ color: 'var(--fg-secondary)', fontSize: 14, fontWeight: 500, textDecoration: 'none' }}
            >
              {item}
            </a>
          ))}
        </nav>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Link
            to="/login"
            style={{
              fontSize: 14, fontWeight: 600, color: 'var(--fg-secondary)',
              padding: '8px 14px', borderRadius: 'var(--r-sm)', textDecoration: 'none',
            }}
          >
            Sign in
          </Link>
          <Link
            to="/onboarding"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 14, fontWeight: 700,
              padding: '9px 16px', borderRadius: 'var(--r-sm)',
              background: 'var(--accent-gradient)',
              color: '#fff', textDecoration: 'none',
              boxShadow: '0 6px 18px var(--accent-glow)',
            }}
          >
            Get started
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </header>
  );
}

/* ─── Hero ────────────────────────────────────────────────────────── */
function Hero() {
  return (
    <section style={{ position: 'relative', padding: '80px 32px 100px', overflow: 'hidden' }}>
      <HeroOrbs />
      <div style={{ maxWidth: 1100, margin: '0 auto', position: 'relative', textAlign: 'center' }}>
        <motion.div
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '6px 14px', borderRadius: 999,
            background: 'color-mix(in srgb, var(--accent) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent) 22%, transparent)',
            marginBottom: 24,
          }}
        >
          <Sparkles size={13} color="var(--accent-2)" />
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg-secondary)', letterSpacing: '0.02em' }}>
            Over 4M+ traders in our community
          </span>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.05 }}
          style={{
            fontSize: 'clamp(40px, 6vw, 72px)', fontWeight: 900, lineHeight: 1.05,
            letterSpacing: '-0.035em', color: 'var(--fg-primary)', margin: '0 0 24px',
          }}
        >
          Algorithmic trading,<br />
          <span style={{
            background: 'var(--accent-gradient)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}>
            built for the flow state.
          </span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.15 }}
          style={{
            fontSize: 18, color: 'var(--fg-secondary)', lineHeight: 1.6,
            maxWidth: 680, margin: '0 auto 36px',
          }}
        >
          Deploy strategies, backtest with real market data, and monitor live P&L — all from one
          keyboard-first terminal. Open-source, self-hostable, and AGPL-3.0 licensed.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.25 }}
          style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}
        >
          <Link
            to="/onboarding"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '14px 24px', borderRadius: 'var(--r-md)', textDecoration: 'none',
              background: 'var(--accent-gradient)', color: '#fff',
              fontSize: 15, fontWeight: 700,
              boxShadow: '0 10px 28px var(--accent-glow)',
            }}
          >
            Start trading free
            <ArrowRight size={16} />
          </Link>
          <a
            href="#how-it-works"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '14px 24px', borderRadius: 'var(--r-md)', textDecoration: 'none',
              background: 'var(--surface-2)', color: 'var(--fg-primary)',
              border: '1px solid var(--line-2)',
              fontSize: 15, fontWeight: 600,
            }}
          >
            See how it works
          </a>
        </motion.div>

        {/* Hero KPI strip */}
        <motion.div
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.35 }}
          style={{
            marginTop: 64, display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 16, maxWidth: 920, marginLeft: 'auto', marginRight: 'auto',
          }}
        >
          {[
            { k: '4M+', v: 'Active traders' },
            { k: '$12B', v: 'Volume traded' },
            { k: '99.99%', v: 'Uptime SLA' },
            { k: '<12ms', v: 'Order latency' },
          ].map((stat) => (
            <div
              key={stat.v}
              className="lt-bento"
              style={{ padding: '18px 20px', textAlign: 'left' }}
            >
              <p className="lt-tabular" style={{
                fontSize: 28, fontWeight: 800, letterSpacing: '-0.02em',
                color: 'var(--fg-primary)', margin: 0,
              }}>
                {stat.k}
              </p>
              <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '4px 0 0', fontWeight: 500 }}>
                {stat.v}
              </p>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

/* ─── Logo bar ───────────────────────────────────────────────────── */
function LogoBar() {
  const logos = ['Zerodha', 'Dhan', 'Upstox', 'ICICI Direct', 'Angel One', 'Fyers'];
  return (
    <section style={{ padding: '0 32px 60px' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', textAlign: 'center' }}>
        <p style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.18em',
          color: 'var(--fg-muted)', textTransform: 'uppercase', marginBottom: 22,
        }}>
          Works with every major Indian broker
        </p>
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 32, justifyContent: 'center',
          alignItems: 'center', opacity: 0.7,
        }}>
          {logos.map((l) => (
            <span key={l} style={{
              fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em',
              color: 'var(--fg-secondary)',
            }}>
              {l}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Feature bento grid ─────────────────────────────────────────── */
function Features() {
  const features = [
    {
      icon: LineChart, title: 'Intuitive trading interface',
      desc: 'A live charting terminal with multi-timeframe views, saved layouts, and keyboard shortcuts that keep your hands off the mouse.',
      tall: true,
    },
    {
      icon: Brain, title: 'AI Commander & Soldier',
      desc: 'Delegate execution to a supervisor agent that runs guarded strategies and reports back on every fill.',
    },
    {
      icon: ShieldCheck, title: 'Risk rails by default',
      desc: 'Daily loss caps, per-symbol limits, and a one-key kill switch halt everything instantly.',
    },
    {
      icon: FlaskIcon, title: 'Battle-tested backtests',
      desc: 'Replay years of tick-level NSE data, compare strategies side-by-side, and export full equity curves.',
    },
    {
      icon: Gauge, title: 'Sub-second latency',
      desc: 'Native WebSocket feeds and co-located order routing keep round-trip times under 12ms.',
    },
    {
      icon: Lock, title: 'Self-hosted by design',
      desc: 'Your keys. Your server. Your data. Ship as a single Docker image or deploy to your own cloud.',
    },
  ];

  return (
    <section id="features" style={{ padding: '80px 32px' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <SectionHeader
          eyebrow="Features"
          title="Everything you need to trade with confidence"
          subtitle="A complete trading operating system — from signal generation to execution to audit — without the SaaS subscription tax."
        />

        <div style={{
          display: 'grid', gap: 20, marginTop: 56,
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        }}>
          {features.map((f, idx) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.4, delay: idx * 0.05 }}
              className="lt-bento"
              style={{
                padding: 28,
                gridRow: f.tall ? 'span 2' : undefined,
                minHeight: f.tall ? 360 : 200,
                display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{
                  width: 42, height: 42, borderRadius: 'var(--r-sm)',
                  background: 'color-mix(in srgb, var(--accent) 12%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--accent) 22%, transparent)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  marginBottom: 18,
                }}>
                  <f.icon size={19} color="var(--accent-2)" />
                </div>
                <h3 style={{
                  fontSize: 18, fontWeight: 700, color: 'var(--fg-primary)',
                  margin: '0 0 10px', letterSpacing: '-0.01em',
                }}>
                  {f.title}
                </h3>
                <p style={{
                  fontSize: 14, color: 'var(--fg-muted)', lineHeight: 1.6, margin: 0,
                }}>
                  {f.desc}
                </p>
              </div>

              {f.tall && <HeroChartPreview />}
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* Inline beaker icon (lucide's FlaskConical aliased) */
function FlaskIcon(props: { size?: number; color?: string }) {
  return <Boxes size={props.size} color={props.color} />;
}

/* ─── Mini chart preview inside the tall feature cell ───────────── */
function HeroChartPreview() {
  return (
    <div style={{
      marginTop: 24, padding: 16, borderRadius: 'var(--r-md)',
      background: 'var(--surface-1)', border: '1px solid var(--line-2)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <div>
          <p style={{ fontSize: 10, fontWeight: 700, color: 'var(--fg-muted)', letterSpacing: '0.1em', margin: 0 }}>
            RELIANCE · 1D
          </p>
          <p className="lt-tabular" style={{ fontSize: 20, fontWeight: 800, color: 'var(--fg-primary)', margin: '4px 0 0' }}>
            ₹2,842.50
          </p>
        </div>
        <span className="lt-tabular lt-glow-bull" style={{ fontSize: 13, fontWeight: 700 }}>
          +2.34%
        </span>
      </div>
      <svg viewBox="0 0 300 80" style={{ width: '100%', height: 80 }} preserveAspectRatio="none">
        <defs>
          <linearGradient id="chartFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--bull)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--bull)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          d="M0,60 L20,55 L40,58 L60,45 L80,50 L100,40 L120,42 L140,32 L160,38 L180,30 L200,25 L220,28 L240,18 L260,22 L280,12 L300,15 L300,80 L0,80 Z"
          fill="url(#chartFill)"
        />
        <path
          d="M0,60 L20,55 L40,58 L60,45 L80,50 L100,40 L120,42 L140,32 L160,38 L180,30 L200,25 L220,28 L240,18 L260,22 L280,12 L300,15"
          fill="none" stroke="var(--bull)" strokeWidth="2"
        />
      </svg>
    </div>
  );
}

/* ─── Section header primitive ──────────────────────────────────── */
function SectionHeader({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle?: string }) {
  return (
    <div style={{ textAlign: 'center', maxWidth: 720, margin: '0 auto' }}>
      <p style={{
        fontSize: 11, fontWeight: 700, letterSpacing: '0.18em',
        color: 'var(--accent-2)', textTransform: 'uppercase', marginBottom: 14,
      }}>
        {eyebrow}
      </p>
      <h2 style={{
        fontSize: 'clamp(28px, 3.8vw, 44px)', fontWeight: 800,
        color: 'var(--fg-primary)', lineHeight: 1.15,
        letterSpacing: '-0.03em', margin: '0 0 16px',
      }}>
        {title}
      </h2>
      {subtitle && (
        <p style={{ fontSize: 16, color: 'var(--fg-secondary)', lineHeight: 1.6, margin: 0 }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}

/* ─── How it works ──────────────────────────────────────────────── */
function HowItWorks() {
  const steps = [
    {
      icon: UserPlusIcon, n: '01', title: 'Instant account setup',
      desc: 'Sign up with email or SSO in under 60 seconds. Connect your broker, fund your wallet, and you are live.',
    },
    {
      icon: Wallet, n: '02', title: 'Fund & fortify',
      desc: 'Deposit from any UPI app or bank. Hardware-key 2FA and per-session risk caps protect every rupee.',
    },
    {
      icon: TrendingUp, n: '03', title: 'Buy, sell, or automate',
      desc: 'Place orders manually, schedule baskets, or hand the wheel to an AI strategy. P&L updates in real time.',
    },
  ];

  return (
    <section id="how-it-works" style={{ padding: '80px 32px', background: 'var(--surface-1)' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <SectionHeader
          eyebrow="How it works"
          title="Three steps to your first live trade"
          subtitle="From signup to first fill in under five minutes, no sales calls, no waitlists."
        />

        <div style={{
          marginTop: 56, display: 'grid', gap: 20,
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        }}>
          {steps.map((s, idx) => (
            <motion.div
              key={s.n}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.4, delay: idx * 0.08 }}
              className="lt-bento"
              style={{ padding: 32, position: 'relative' }}
            >
              <span style={{
                position: 'absolute', top: 24, right: 28,
                fontSize: 56, fontWeight: 900, lineHeight: 1,
                background: 'var(--accent-gradient)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                opacity: 0.25, letterSpacing: '-0.04em',
              }}>
                {s.n}
              </span>
              <div style={{
                width: 46, height: 46, borderRadius: 'var(--r-sm)',
                background: 'var(--accent-gradient)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                marginBottom: 20, boxShadow: '0 8px 20px var(--accent-glow)',
              }}>
                <s.icon size={20} color="#fff" />
              </div>
              <h3 style={{
                fontSize: 20, fontWeight: 700, color: 'var(--fg-primary)',
                margin: '0 0 10px', letterSpacing: '-0.01em',
              }}>
                {s.title}
              </h3>
              <p style={{ fontSize: 14, color: 'var(--fg-muted)', lineHeight: 1.6, margin: 0 }}>
                {s.desc}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* Placeholder for lucide UserPlus (keeps import list compact) */
function UserPlusIcon(props: { size?: number; color?: string }) {
  return <Layers size={props.size} color={props.color} />;
}

/* ─── Platform preview (mock dashboard screenshot) ──────────────── */
function PlatformPreview() {
  return (
    <section style={{ padding: '80px 32px', position: 'relative', overflow: 'hidden' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <SectionHeader
          eyebrow="The terminal"
          title="A trading cockpit, not a dashboard"
          subtitle="Every panel is keyboard-navigable. Every number is tabular. Every action is auditable."
        />

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.6 }}
          style={{
            marginTop: 56, borderRadius: 'var(--r-xl)',
            border: '1px solid var(--line-2)',
            background: 'var(--surface-2)',
            overflow: 'hidden',
            boxShadow: 'var(--elev-3), 0 40px 80px color-mix(in srgb, var(--accent) 15%, transparent)',
          }}
        >
          {/* Window chrome */}
          <div style={{
            padding: '12px 16px', borderBottom: '1px solid var(--line-2)',
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'var(--surface-1)',
          }}>
            {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
              <span key={c} style={{ width: 11, height: 11, borderRadius: '50%', background: c, opacity: 0.9 }} />
            ))}
            <span style={{
              marginLeft: 12, fontSize: 11, color: 'var(--fg-muted)',
              fontFamily: 'ui-monospace, monospace', letterSpacing: '0.05em',
            }}>
              lohi-trade — /dashboard
            </span>
          </div>

          {/* Mock terminal body */}
          <div style={{
            display: 'grid', gridTemplateColumns: '220px 1fr 260px',
            minHeight: 440,
          }}>
            {/* Sidebar mock */}
            <div style={{
              padding: 14, borderRight: '1px solid var(--line-2)',
              background: 'var(--surface-1)',
            }}>
              {['Dashboard', 'Trade', 'Positions', 'Orders', 'Strategies', 'Backtests', 'Analytics'].map((item, i) => (
                <div key={item} style={{
                  padding: '9px 12px', borderRadius: 'var(--r-sm)', fontSize: 12,
                  color: i === 0 ? 'var(--fg-primary)' : 'var(--fg-muted)',
                  background: i === 0 ? 'color-mix(in srgb, var(--accent) 12%, transparent)' : 'transparent',
                  fontWeight: i === 0 ? 600 : 500, marginBottom: 2,
                }}>
                  {item}
                </div>
              ))}
            </div>

            {/* Main panel mock */}
            <div style={{ padding: 20 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
                {[
                  { label: 'Portfolio', v: '₹2,14,580', d: '+6.8%', up: true },
                  { label: 'Today P&L', v: '+₹8,240', d: '+1.2%', up: true },
                  { label: 'Open positions', v: '12', d: '3 new', up: true },
                ].map((m) => (
                  <div key={m.label} style={{
                    padding: 14, borderRadius: 'var(--r-sm)',
                    border: '1px solid var(--line-2)', background: 'var(--surface-2)',
                  }}>
                    <p style={{ fontSize: 10, color: 'var(--fg-muted)', fontWeight: 700, letterSpacing: '0.08em', margin: 0, textTransform: 'uppercase' }}>
                      {m.label}
                    </p>
                    <p className="lt-tabular" style={{ fontSize: 18, fontWeight: 800, color: 'var(--fg-primary)', margin: '6px 0 2px' }}>
                      {m.v}
                    </p>
                    <p className="lt-tabular" style={{ fontSize: 11, fontWeight: 700, color: m.up ? 'var(--bull)' : 'var(--bear)', margin: 0 }}>
                      {m.d}
                    </p>
                  </div>
                ))}
              </div>
              <div style={{
                height: 260, borderRadius: 'var(--r-sm)',
                border: '1px solid var(--line-2)', background: 'var(--surface-1)',
                padding: 16, position: 'relative',
              }}>
                <svg viewBox="0 0 600 220" style={{ width: '100%', height: '100%' }} preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="pnlFill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent-2)" stopOpacity="0.3" />
                      <stop offset="100%" stopColor="var(--accent-2)" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  {[40, 80, 120, 160, 200].map((y) => (
                    <line key={y} x1="0" x2="600" y1={y} y2={y} stroke="var(--line-1)" />
                  ))}
                  <path
                    d="M0,180 L40,170 L80,175 L120,155 L160,160 L200,140 L240,145 L280,120 L320,125 L360,100 L400,105 L440,85 L480,75 L520,55 L560,60 L600,40 L600,220 L0,220 Z"
                    fill="url(#pnlFill)"
                  />
                  <path
                    d="M0,180 L40,170 L80,175 L120,155 L160,160 L200,140 L240,145 L280,120 L320,125 L360,100 L400,105 L440,85 L480,75 L520,55 L560,60 L600,40"
                    fill="none" stroke="var(--accent-2)" strokeWidth="2.2"
                  />
                </svg>
              </div>
            </div>

            {/* Right panel — order book mock */}
            <div style={{
              padding: 16, borderLeft: '1px solid var(--line-2)',
              background: 'var(--surface-1)',
            }}>
              <p style={{ fontSize: 10, fontWeight: 700, color: 'var(--fg-muted)', letterSpacing: '0.1em', textTransform: 'uppercase', margin: '0 0 12px' }}>
                Order Book · RELIANCE
              </p>
              {[
                { p: '2,843.20', q: '1,240', side: 'ask' },
                { p: '2,842.95', q: '860', side: 'ask' },
                { p: '2,842.70', q: '2,110', side: 'ask' },
              ].map((r) => (
                <Row key={r.p} {...r} />
              ))}
              <div style={{
                margin: '10px 0', padding: '8px 10px', borderRadius: 'var(--r-xs)',
                background: 'color-mix(in srgb, var(--accent) 10%, transparent)',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <span className="lt-tabular" style={{ fontSize: 13, fontWeight: 800, color: 'var(--fg-primary)' }}>
                  ₹2,842.50
                </span>
                <span style={{ fontSize: 10, color: 'var(--fg-muted)', fontWeight: 600 }}>LTP</span>
              </div>
              {[
                { p: '2,842.15', q: '1,540', side: 'bid' },
                { p: '2,841.80', q: '920', side: 'bid' },
                { p: '2,841.50', q: '3,220', side: 'bid' },
              ].map((r) => (
                <Row key={r.p} {...r} />
              ))}
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function Row({ p, q, side }: { p: string; q: string; side: 'bid' | 'ask' }) {
  const isBid = side === 'bid';
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', padding: '6px 10px',
      borderRadius: 'var(--r-xs)', marginBottom: 2,
      background: isBid ? 'var(--bull-soft)' : 'var(--bear-soft)',
    }}>
      <span className="lt-tabular" style={{ fontSize: 12, color: isBid ? 'var(--bull)' : 'var(--bear)', fontWeight: 700 }}>
        {p}
      </span>
      <span className="lt-tabular" style={{ fontSize: 12, color: 'var(--fg-secondary)' }}>
        {q}
      </span>
    </div>
  );
}

/* ─── Pricing ─────────────────────────────────────────────────────── */
function Pricing() {
  const [yearly, setYearly] = useState(false);
  const plans = [
    {
      name: 'Self-host',
      price: 'Free',
      note: 'Forever · AGPL-3.0',
      desc: 'Clone the repo, run it on your box. All features, zero limits.',
      features: [
        'Unlimited strategies & backtests',
        'Broker integrations (all brokers)',
        'Single-user deployment',
        'Community support',
      ],
      cta: 'Deploy on GitHub',
      href: 'https://github.com/lohi-trade/lohi-trade-oss',
      highlight: false,
    },
    {
      name: 'Cloud Pro',
      price: yearly ? '₹1,999' : '₹2,499',
      note: yearly ? 'per month · billed yearly' : 'per month',
      desc: 'Managed hosting with automatic updates, backups, and priority order routing.',
      features: [
        'Everything in Self-host',
        'Co-located low-latency execution',
        'Auto-snapshot backups',
        'Priority email support',
        'Advanced analytics & PDF reports',
      ],
      cta: 'Start 14-day trial',
      href: '/onboarding',
      highlight: true,
    },
    {
      name: 'Enterprise',
      price: 'Custom',
      note: 'Teams & funds',
      desc: 'Dedicated infrastructure, SSO, role-based access, and white-glove onboarding.',
      features: [
        'Everything in Cloud Pro',
        'Multi-user with RBAC & SSO',
        'Dedicated tenant + SLA',
        'Custom strategy consulting',
        '24/7 Slack support',
      ],
      cta: 'Talk to sales',
      href: 'mailto:sales@lohi-trade.dev',
      highlight: false,
    },
  ];

  return (
    <section id="pricing" style={{ padding: '80px 32px' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <SectionHeader
          eyebrow="Pricing"
          title="Pay for scale, not for software"
          subtitle="Run it yourself for free. Graduate to managed cloud when you're ready to scale."
        />

        {/* Billing toggle */}
        <div style={{
          marginTop: 32, display: 'flex', justifyContent: 'center',
        }}>
          <div style={{
            display: 'inline-flex', padding: 4, borderRadius: 999,
            background: 'var(--surface-2)', border: '1px solid var(--line-2)',
          }}>
            {[
              { k: 'monthly', label: 'Monthly', active: !yearly },
              { k: 'yearly', label: 'Yearly · save 20%', active: yearly },
            ].map((opt) => (
              <button
                key={opt.k}
                onClick={() => setYearly(opt.k === 'yearly')}
                style={{
                  padding: '8px 18px', borderRadius: 999, fontSize: 13, fontWeight: 600,
                  border: 'none', cursor: 'pointer',
                  background: opt.active ? 'var(--accent-gradient)' : 'transparent',
                  color: opt.active ? '#fff' : 'var(--fg-secondary)',
                  transition: 'all var(--dur-2) var(--ease-out)',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{
          marginTop: 48, display: 'grid', gap: 20,
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        }}>
          {plans.map((p, idx) => (
            <motion.div
              key={p.name}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.4, delay: idx * 0.08 }}
              className="lt-bento"
              style={{
                padding: 32,
                border: p.highlight ? '1px solid color-mix(in srgb, var(--accent) 40%, transparent)' : undefined,
                boxShadow: p.highlight ? '0 20px 40px color-mix(in srgb, var(--accent) 18%, transparent)' : undefined,
                position: 'relative',
              }}
            >
              {p.highlight && (
                <span style={{
                  position: 'absolute', top: -12, left: 32,
                  fontSize: 10, fontWeight: 800, letterSpacing: '0.1em',
                  padding: '4px 10px', borderRadius: 999,
                  background: 'var(--accent-gradient)', color: '#fff',
                }}>
                  MOST POPULAR
                </span>
              )}
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-secondary)', margin: 0, letterSpacing: '0.04em' }}>
                {p.name}
              </h3>
              <div style={{ margin: '14px 0 8px' }}>
                <span className="lt-tabular" style={{
                  fontSize: 40, fontWeight: 900, color: 'var(--fg-primary)',
                  letterSpacing: '-0.03em',
                }}>
                  {p.price}
                </span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '0 0 14px', fontWeight: 500 }}>
                {p.note}
              </p>
              <p style={{ fontSize: 14, color: 'var(--fg-secondary)', margin: '0 0 20px', lineHeight: 1.55 }}>
                {p.desc}
              </p>

              <div style={{ height: 1, background: 'var(--line-2)', margin: '0 0 20px' }} />

              <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 28px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {p.features.map((f) => (
                  <li key={f} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: 'var(--fg-secondary)' }}>
                    <Check size={14} color="var(--bull)" strokeWidth={2.6} />
                    {f}
                  </li>
                ))}
              </ul>

              <a
                href={p.href}
                target={p.href.startsWith('http') ? '_blank' : undefined}
                rel={p.href.startsWith('http') ? 'noreferrer' : undefined}
                style={{
                  display: 'block', textAlign: 'center',
                  padding: '11px 16px', borderRadius: 'var(--r-sm)', textDecoration: 'none',
                  fontSize: 14, fontWeight: 700,
                  background: p.highlight ? 'var(--accent-gradient)' : 'var(--surface-3)',
                  color: p.highlight ? '#fff' : 'var(--fg-primary)',
                  border: p.highlight ? 'none' : '1px solid var(--line-2)',
                  boxShadow: p.highlight ? '0 6px 18px var(--accent-glow)' : 'none',
                }}
              >
                {p.cta}
              </a>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Testimonial ────────────────────────────────────────────────── */
function Testimonial() {
  return (
    <section style={{ padding: '80px 32px', background: 'var(--surface-1)' }}>
      <div style={{ maxWidth: 900, margin: '0 auto', textAlign: 'center' }}>
        <p style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.18em',
          color: 'var(--accent-2)', textTransform: 'uppercase', marginBottom: 24,
        }}>
          Testimonial
        </p>
        <blockquote style={{
          fontSize: 'clamp(22px, 2.8vw, 32px)', fontWeight: 600,
          lineHeight: 1.4, letterSpacing: '-0.02em',
          color: 'var(--fg-primary)', margin: '0 0 36px', fontStyle: 'normal',
        }}>
          &ldquo;LOHI-TRADE is the first tool that actually respects my workflow. Keyboard-first, audit-heavy, and self-hostable — it&apos;s what Bloomberg Terminal would look like if it were built in 2026.&rdquo;
        </blockquote>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14 }}>
          <div style={{
            width: 48, height: 48, borderRadius: '50%',
            background: 'var(--accent-gradient)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontWeight: 800, fontSize: 18,
          }}>
            RJ
          </div>
          <div style={{ textAlign: 'left' }}>
            <p style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>
              Ravi Jaggar
            </p>
            <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '2px 0 0' }}>
              Quant Developer · Mumbai
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Final CTA ──────────────────────────────────────────────────── */
function FinalCTA() {
  return (
    <section style={{ padding: '80px 32px', position: 'relative', overflow: 'hidden' }}>
      <div
        aria-hidden
        style={{
          position: 'absolute', inset: 0,
          background: 'radial-gradient(ellipse at center, color-mix(in srgb, var(--accent) 18%, transparent) 0%, transparent 60%)',
        }}
      />
      <div className="lt-bento" style={{
        maxWidth: 1000, margin: '0 auto', padding: 'clamp(40px, 6vw, 72px) 32px',
        textAlign: 'center', position: 'relative',
      }}>
        <Zap size={32} color="var(--accent-2)" style={{ margin: '0 auto 20px', display: 'block' }} />
        <h2 style={{
          fontSize: 'clamp(28px, 4vw, 44px)', fontWeight: 800,
          letterSpacing: '-0.03em', color: 'var(--fg-primary)',
          margin: '0 0 16px', lineHeight: 1.15,
        }}>
          Ready to find your flow?
        </h2>
        <p style={{
          fontSize: 17, color: 'var(--fg-secondary)', lineHeight: 1.6,
          maxWidth: 560, margin: '0 auto 32px',
        }}>
          Spin up your trading terminal in under a minute. No credit card. Cancel any time.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Link
            to="/onboarding"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '14px 28px', borderRadius: 'var(--r-md)', textDecoration: 'none',
              background: 'var(--accent-gradient)', color: '#fff',
              fontSize: 15, fontWeight: 700,
              boxShadow: '0 10px 28px var(--accent-glow)',
            }}
          >
            Create free account
            <ArrowRight size={16} />
          </Link>
          <a
            href="https://github.com/lohi-trade/lohi-trade-oss"
            target="_blank" rel="noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '14px 28px', borderRadius: 'var(--r-md)', textDecoration: 'none',
              background: 'var(--surface-3)', color: 'var(--fg-primary)',
              border: '1px solid var(--line-2)',
              fontSize: 15, fontWeight: 600,
            }}
          >
            <Github size={16} />
            Star on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}

/* ─── Footer ─────────────────────────────────────────────────────── */
function Footer() {
  const year = new Date().getFullYear();
  const cols = [
    {
      title: 'Product',
      items: [
        { label: 'Features', href: '#features' },
        { label: 'How it works', href: '#how-it-works' },
        { label: 'Pricing', href: '#pricing' },
        { label: 'Changelog', href: '#' },
      ],
    },
    {
      title: 'Developers',
      items: [
        { label: 'Documentation', href: '#' },
        { label: 'API reference', href: '#' },
        { label: 'GitHub', href: 'https://github.com/lohi-trade/lohi-trade-oss' },
        { label: 'Self-hosting guide', href: '#' },
      ],
    },
    {
      title: 'Company',
      items: [
        { label: 'About', href: '#' },
        { label: 'Blog', href: '#' },
        { label: 'Contact', href: 'mailto:hello@lohi-trade.dev' },
        { label: 'Press kit', href: '#' },
      ],
    },
    {
      title: 'Legal',
      items: [
        { label: 'Privacy', href: '#' },
        { label: 'Terms', href: '#' },
        { label: 'AGPL-3.0', href: 'https://www.gnu.org/licenses/agpl-3.0.html' },
        { label: 'Security', href: '#' },
      ],
    },
  ];

  return (
    <footer style={{
      padding: '60px 32px 32px',
      borderTop: '1px solid var(--line-2)',
      background: 'var(--surface-1)',
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{
          display: 'grid', gap: 40,
          gridTemplateColumns: 'minmax(220px, 1fr) repeat(auto-fit, minmax(140px, 1fr))',
          marginBottom: 48,
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <div style={{
                width: 32, height: 32, borderRadius: 8,
                background: 'var(--accent-gradient)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <Activity size={16} color="#fff" strokeWidth={2.4} />
              </div>
              <span style={{ fontWeight: 900, fontSize: 16, letterSpacing: '-0.02em', color: 'var(--fg-primary)' }}>
                LOHI<span style={{ color: 'var(--accent-2)' }}>-TRADE</span>
              </span>
            </div>
            <p style={{ fontSize: 13, color: 'var(--fg-muted)', lineHeight: 1.6, margin: '0 0 20px', maxWidth: 260 }}>
              Open-source algorithmic trading terminal for the Indian markets.
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              {[
                { icon: Github, href: 'https://github.com/lohi-trade/lohi-trade-oss', label: 'GitHub' },
                { icon: Twitter, href: '#', label: 'Twitter' },
                { icon: Linkedin, href: '#', label: 'LinkedIn' },
              ].map((s) => (
                <a
                  key={s.label}
                  href={s.href}
                  target={s.href.startsWith('http') ? '_blank' : undefined}
                  rel={s.href.startsWith('http') ? 'noreferrer' : undefined}
                  aria-label={s.label}
                  style={{
                    width: 36, height: 36, borderRadius: 'var(--r-sm)',
                    background: 'var(--surface-2)', border: '1px solid var(--line-2)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--fg-secondary)', textDecoration: 'none',
                  }}
                >
                  <s.icon size={15} />
                </a>
              ))}
            </div>
          </div>

          {cols.map((col) => (
            <div key={col.title}>
              <p style={{
                fontSize: 11, fontWeight: 700, letterSpacing: '0.14em',
                color: 'var(--fg-muted)', textTransform: 'uppercase', marginBottom: 16,
              }}>
                {col.title}
              </p>
              <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {col.items.map((item) => (
                  <li key={item.label}>
                    <a
                      href={item.href}
                      target={item.href.startsWith('http') ? '_blank' : undefined}
                      rel={item.href.startsWith('http') ? 'noreferrer' : undefined}
                      style={{ fontSize: 13, color: 'var(--fg-secondary)', textDecoration: 'none' }}
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div style={{
          padding: '24px 0 0', borderTop: '1px solid var(--line-2)',
          display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
        }}>
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: 0 }}>
            © {year} LOHI-TRADE · Open-source under AGPL-3.0
          </p>
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: 0 }}>
            <BarChart3 size={11} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />
            Not investment advice. Trade responsibly.
          </p>
        </div>
      </div>
    </footer>
  );
}

/* ─── Page export ────────────────────────────────────────────────── */
export default function LandingPage() {
  // Force dark theme for the landing page — it's designed for it.
  const theme = useThemeStore((s) => s.theme);

  return (
    <div
      data-theme={theme}
      style={{
        minHeight: '100vh',
        background: 'var(--surface-0)',
        color: 'var(--fg-primary)',
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, sans-serif',
      }}
    >
      <Navbar />
      <Hero />
      <LogoBar />
      <Features />
      <HowItWorks />
      <PlatformPreview />
      <Pricing />
      <Testimonial />
      <FinalCTA />
      <Footer />
    </div>
  );
}
