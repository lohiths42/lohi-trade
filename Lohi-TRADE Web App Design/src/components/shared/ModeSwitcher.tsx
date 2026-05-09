/**
 * Mode switcher — toggles between the Trade and Research surfaces.
 *
 * Renders a two-segment pill that mirrors the ambient surface. On click it
 * flips `useAppModeStore`, which rewrites `<html data-surface>` and pushes
 * the router to the matching landing route so the user always lands on a
 * page that visually belongs to the chosen surface.
 *
 * The switcher works from either shell (Trade or Research) so it can be
 * placed in the top chrome of both. Styled with the current surface
 * tokens so it adopts the correct palette automatically — monochrome
 * in Research, glassy-indigo in Trade.
 */
import { useNavigate } from 'react-router-dom';
import { BarChart3, Brain } from 'lucide-react';
import { useAppModeStore, type AppSurface } from '../../stores/mode-store';

interface ModeSwitcherProps {
  /** Optional override: where to send the user when switching to Trade. */
  tradeHomePath?: string;
  /** Optional override: where to send the user when switching to Research. */
  researchHomePath?: string;
  /** Condensed mode — icons only, for narrow chrome. */
  compact?: boolean;
}

export default function ModeSwitcher({
  tradeHomePath = '/',
  researchHomePath = '/research',
  compact = false,
}: ModeSwitcherProps) {
  const surface = useAppModeStore((s) => s.surface);
  const setSurface = useAppModeStore((s) => s.setSurface);
  const navigate = useNavigate();

  function select(next: AppSurface) {
    if (next === surface) return;
    setSurface(next);
    navigate(next === 'research' ? researchHomePath : tradeHomePath);
  }

  return (
    <div
      role="tablist"
      aria-label="Application surface"
      style={{
        display: 'inline-flex',
        padding: 2,
        background: 'transparent',
        border: '1px solid var(--line-3)',
        borderRadius: 999,
        gap: 0,
      }}
    >
      <Segment
        active={surface === 'trade'}
        onClick={() => select('trade')}
        label="Trade"
        icon={<BarChart3 size={12} strokeWidth={2.4} />}
        compact={compact}
      />
      <Segment
        active={surface === 'research'}
        onClick={() => select('research')}
        label="Research"
        icon={<Brain size={12} strokeWidth={2.4} />}
        compact={compact}
      />
    </div>
  );
}

function Segment({
  active,
  onClick,
  label,
  icon,
  compact,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: React.ReactNode;
  compact: boolean;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      style={{
        all: 'unset',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        padding: compact ? '4px 8px' : '6px 14px',
        fontSize: compact ? 10.5 : 11,
        fontWeight: 700,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        cursor: 'pointer',
        borderRadius: 999,
        background: active ? 'var(--fg-primary)' : 'transparent',
        color: active ? 'var(--surface-2)' : 'var(--fg-muted)',
        transition: 'all var(--dur-2) var(--ease-out)',
      }}
    >
      {icon}
      {!compact && <span>{label}</span>}
    </button>
  );
}
