import { AlertTriangle, Beaker, Radio } from 'lucide-react';
import { motion } from 'motion/react';
import { useTradingModeStore } from '../../stores/trading-mode-store';

/**
 * ModeBanner — sticky page-top ribbon that always communicates the
 * current trading mode. PAPER is amber-soft, LIVE is red with a
 * pulsing indicator to reinforce that real money is at stake.
 *
 * Matches the spec: "Mode banner (amber PAPER / red LIVE, prominently displayed)"
 */
export default function ModeBanner() {
  const mode = useTradingModeStore((s) => s.mode);
  const killSwitch = useTradingModeStore((s) => s.killSwitchActive);

  if (killSwitch) {
    return (
      <Banner
        icon={<AlertTriangle size={14} />}
        label="SYSTEM HALTED"
        text="Kill switch active · all order placement suspended"
        color="var(--bear)"
        soft="var(--bear-soft)"
        pulse
      />
    );
  }

  if (mode === 'LIVE') {
    return (
      <Banner
        icon={<Radio size={14} />}
        label="LIVE"
        text="Real money at stake · every order is binding"
        color="var(--bear)"
        soft="var(--bear-soft)"
        pulse
      />
    );
  }

  return (
    <Banner
      icon={<Beaker size={14} />}
      label="PAPER"
      text="Simulated trading · no real orders routed to the broker"
      color="var(--warn)"
      soft="var(--warn-soft)"
    />
  );
}

function Banner({
  icon, label, text, color, soft, pulse = false,
}: {
  icon: React.ReactNode;
  label: string;
  text: string;
  color: string;
  soft: string;
  pulse?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
      role="status"
      aria-live="polite"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 14px',
        borderRadius: 'var(--r-sm)',
        background: soft,
        border: `1px solid color-mix(in srgb, ${color} 28%, transparent)`,
        fontSize: 12,
      }}
    >
      <span
        style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 22, height: 22, borderRadius: '50%',
          background: `color-mix(in srgb, ${color} 18%, transparent)`,
          color,
        }}
      >
        {icon}
      </span>
      {pulse && (
        <motion.span
          aria-hidden
          animate={{ scale: [1, 1.4, 1], opacity: [0.7, 0, 0.7] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
          style={{
            width: 8, height: 8, borderRadius: '50%',
            background: color, marginLeft: -4,
          }}
        />
      )}
      <strong style={{ fontWeight: 800, letterSpacing: '0.12em', color }}>{label}</strong>
      <span style={{ color: 'var(--fg-secondary)' }}>·</span>
      <span style={{ color: 'var(--fg-secondary)' }}>{text}</span>
    </motion.div>
  );
}
