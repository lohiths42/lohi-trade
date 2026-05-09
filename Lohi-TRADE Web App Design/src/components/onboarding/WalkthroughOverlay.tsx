import { useState, useEffect, useCallback, useRef } from 'react';

/* ─── Types ──────────────────────────────────────────────────────────────── */

export interface WalkthroughStep {
  targetSelector: string;
  title: string;
  description: string;
  position: 'top' | 'bottom' | 'left' | 'right';
}

export interface WalkthroughOverlayProps {
  isOpen: boolean;
  onComplete: () => void;
  onSkip: () => void;
}

/* ─── Step Definitions ───────────────────────────────────────────────────── */

export const WALKTHROUGH_STEPS: WalkthroughStep[] = [
  {
    targetSelector: '[data-tour="dashboard-pnl"]',
    title: 'Dashboard Overview',
    description:
      'Your portfolio value, P&L, and key metrics are displayed here. Monitor your trading performance at a glance.',
    position: 'bottom',
  },
  {
    targetSelector: '[data-tour="positions"]',
    title: 'Manage Positions',
    description:
      'View all your open positions, unrealized P&L, and manage individual trades from this section.',
    position: 'right',
  },
  {
    targetSelector: '[data-tour="screener"]',
    title: 'Stock Screener',
    description:
      'Filter stocks by fundamental and technical parameters to discover investment opportunities.',
    position: 'bottom',
  },
  {
    targetSelector: '[data-tour="watchlist"]',
    title: 'Watchlists',
    description:
      'Create custom watchlists to track your favourite stocks with real-time prices and alerts.',
    position: 'right',
  },
  {
    targetSelector: '[data-tour="broker"]',
    title: 'Connect Broker',
    description:
      'Link your broker account (Zerodha, Groww, Angel One, or Shoonya) to start executing trades.',
    position: 'bottom',
  },
  {
    targetSelector: '[data-tour="chatbot"]',
    title: 'Meet Lohi',
    description:
      "Your personal quant in a chat panel. Ask about your trades, P&L, strategies, or any stock in plain English or Hinglish — she sees your whole terminal.",
    position: 'left',
  },
  {
    targetSelector: '[data-tour="kill-switch"]',
    title: 'Kill Switch',
    description:
      'Emergency stop — instantly halts all algorithms and cancels pending orders. Use with caution.',
    position: 'bottom',
  },
];

/* ─── Geometry helpers ───────────────────────────────────────────────────── */

export interface TargetRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const TOOLTIP_GAP = 16;
const SPOTLIGHT_PADDING = 8;

export function computeTooltipPosition(
  target: TargetRect,
  position: WalkthroughStep['position'],
  tooltipWidth: number,
  tooltipHeight: number,
  viewportWidth: number,
  viewportHeight: number,
): { top: number; left: number } {
  let top = 0;
  let left = 0;

  switch (position) {
    case 'bottom':
      top = target.top + target.height + SPOTLIGHT_PADDING + TOOLTIP_GAP;
      left = target.left + target.width / 2 - tooltipWidth / 2;
      break;
    case 'top':
      top = target.top - SPOTLIGHT_PADDING - TOOLTIP_GAP - tooltipHeight;
      left = target.left + target.width / 2 - tooltipWidth / 2;
      break;
    case 'right':
      top = target.top + target.height / 2 - tooltipHeight / 2;
      left = target.left + target.width + SPOTLIGHT_PADDING + TOOLTIP_GAP;
      break;
    case 'left':
      top = target.top + target.height / 2 - tooltipHeight / 2;
      left = target.left - SPOTLIGHT_PADDING - TOOLTIP_GAP - tooltipWidth;
      break;
  }

  // Clamp within viewport (ensure right/bottom edge doesn't exceed, then ensure left/top >= margin)
  const margin = 12;
  left = Math.min(left, viewportWidth - tooltipWidth - margin);
  left = Math.max(margin, left);
  top = Math.min(top, viewportHeight - tooltipHeight - margin);
  top = Math.max(margin, top);

  return { top, left };
}

export function computeSpotlightBoxShadow(target: TargetRect, padding: number = SPOTLIGHT_PADDING): string {
  const x = target.left - padding;
  const y = target.top - padding;
  const w = target.width + padding * 2;
  const h = target.height + padding * 2;
  const r = 12;

  // Use a large box-shadow spread to dim the rest of the screen.
  // The element itself is positioned/sized to match the spotlight cutout.
  return `0 0 0 9999px rgba(0, 0, 0, 0.65), inset 0 0 0 0 transparent`;
}

/* ─── CSS-in-JS styles (pure CSS transitions) ────────────────────────────── */

const styles = {
  overlay: {
    position: 'fixed' as const,
    inset: 0,
    zIndex: 10000,
    pointerEvents: 'none' as const,
  },
  spotlight: {
    position: 'absolute' as const,
    borderRadius: 12,
    boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.65)',
    transition: 'top 0.35s ease, left 0.35s ease, width 0.35s ease, height 0.35s ease, opacity 0.3s ease',
    pointerEvents: 'none' as const,
  },
  tooltip: {
    position: 'absolute' as const,
    width: 320,
    background: 'linear-gradient(145deg, #0f172a, #1e293b)',
    border: '1px solid rgba(59, 130, 246, 0.3)',
    borderRadius: 14,
    padding: '24px 24px 20px',
    color: '#e2e8f0',
    pointerEvents: 'auto' as const,
    transition: 'top 0.35s ease, left 0.35s ease, opacity 0.3s ease, transform 0.3s ease',
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
  },
  tooltipHidden: {
    opacity: 0,
    transform: 'scale(0.92)',
  },
  tooltipVisible: {
    opacity: 1,
    transform: 'scale(1)',
  },
  title: {
    fontSize: 16,
    fontWeight: 700 as const,
    margin: '0 0 8px',
    color: '#f1f5f9',
  },
  description: {
    fontSize: 13,
    lineHeight: 1.6,
    color: '#94a3b8',
    margin: '0 0 20px',
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  progress: {
    fontSize: 11,
    color: '#64748b',
    fontWeight: 600 as const,
  },
  buttons: {
    display: 'flex',
    gap: 8,
  },
  btnBase: {
    padding: '7px 16px',
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 600 as const,
    cursor: 'pointer',
    border: 'none',
    transition: 'background 0.15s, opacity 0.15s',
  },
  btnSkip: {
    background: 'transparent',
    color: '#64748b',
    border: '1px solid rgba(51, 65, 85, 0.6)',
  },
  btnBack: {
    background: 'rgba(30, 41, 59, 0.8)',
    color: '#94a3b8',
  },
  btnNext: {
    background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
    color: '#ffffff',
    boxShadow: '0 2px 8px rgba(59, 130, 246, 0.3)',
  },
  arrow: {
    position: 'absolute' as const,
    width: 0,
    height: 0,
    transition: 'opacity 0.3s ease',
  },
  progressDots: {
    display: 'flex',
    gap: 6,
    alignItems: 'center',
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    transition: 'background 0.2s ease, transform 0.2s ease',
  },
};

/* ─── Arrow component ────────────────────────────────────────────────────── */

function TooltipArrow({ position }: { position: WalkthroughStep['position'] }) {
  const size = 8;
  const color = '#0f172a';

  const arrowStyles: Record<string, React.CSSProperties> = {
    top: {
      bottom: -size,
      left: '50%',
      marginLeft: -size,
      borderLeft: `${size}px solid transparent`,
      borderRight: `${size}px solid transparent`,
      borderTop: `${size}px solid ${color}`,
    },
    bottom: {
      top: -size,
      left: '50%',
      marginLeft: -size,
      borderLeft: `${size}px solid transparent`,
      borderRight: `${size}px solid transparent`,
      borderBottom: `${size}px solid ${color}`,
    },
    left: {
      right: -size,
      top: '50%',
      marginTop: -size,
      borderTop: `${size}px solid transparent`,
      borderBottom: `${size}px solid transparent`,
      borderLeft: `${size}px solid ${color}`,
    },
    right: {
      left: -size,
      top: '50%',
      marginTop: -size,
      borderTop: `${size}px solid transparent`,
      borderBottom: `${size}px solid transparent`,
      borderRight: `${size}px solid ${color}`,
    },
  };

  return <div style={{ ...styles.arrow, ...arrowStyles[position] }} />;
}

/* ─── Main Component ─────────────────────────────────────────────────────── */

export default function WalkthroughOverlay({ isOpen, onComplete, onSkip }: WalkthroughOverlayProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [visible, setVisible] = useState(false);
  const [targetRect, setTargetRect] = useState<TargetRect | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const step = WALKTHROUGH_STEPS[currentStep];
  const totalSteps = WALKTHROUGH_STEPS.length;
  const isFirst = currentStep === 0;
  const isLast = currentStep === totalSteps - 1;

  // Locate the target element and measure its rect
  const measureTarget = useCallback(() => {
    if (!step) return;
    const el = document.querySelector(step.targetSelector);
    if (el) {
      const rect = el.getBoundingClientRect();
      setTargetRect({ top: rect.top, left: rect.left, width: rect.width, height: rect.height });
    } else {
      // Fallback: center of screen
      setTargetRect({ top: window.innerHeight / 2 - 30, left: window.innerWidth / 2 - 60, width: 120, height: 60 });
    }
  }, [step]);

  // Show/hide with animation delay
  useEffect(() => {
    if (isOpen) {
      setCurrentStep(0);
      // Small delay for enter animation
      const timer = setTimeout(() => setVisible(true), 50);
      return () => clearTimeout(timer);
    } else {
      setVisible(false);
    }
  }, [isOpen]);

  // Re-measure on step change or window resize
  useEffect(() => {
    if (!isOpen) return;
    measureTarget();
    const handleResize = () => measureTarget();
    window.addEventListener('resize', handleResize);
    window.addEventListener('scroll', handleResize, true);
    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('scroll', handleResize, true);
    };
  }, [isOpen, currentStep, measureTarget]);

  const handleNext = useCallback(() => {
    if (isLast) {
      onComplete();
    } else {
      setCurrentStep((s) => s + 1);
    }
  }, [isLast, onComplete]);

  const handleBack = useCallback(() => {
    if (!isFirst) {
      setCurrentStep((s) => s - 1);
    }
  }, [isFirst]);

  const handleSkip = useCallback(() => {
    onSkip();
  }, [onSkip]);

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'Enter') handleNext();
      else if (e.key === 'ArrowLeft') handleBack();
      else if (e.key === 'Escape') handleSkip();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, handleNext, handleBack, handleSkip]);

  if (!isOpen || !targetRect || !step) return null;

  // Compute tooltip position
  const tooltipWidth = 320;
  const tooltipHeight = 180; // approximate
  const tooltipPos = computeTooltipPosition(
    targetRect,
    step.position,
    tooltipWidth,
    tooltipHeight,
    window.innerWidth,
    window.innerHeight,
  );

  const spotlightStyle: React.CSSProperties = {
    ...styles.spotlight,
    top: targetRect.top - SPOTLIGHT_PADDING,
    left: targetRect.left - SPOTLIGHT_PADDING,
    width: targetRect.width + SPOTLIGHT_PADDING * 2,
    height: targetRect.height + SPOTLIGHT_PADDING * 2,
    opacity: visible ? 1 : 0,
  };

  const tooltipStyle: React.CSSProperties = {
    ...styles.tooltip,
    top: tooltipPos.top,
    left: tooltipPos.left,
    ...(visible ? styles.tooltipVisible : styles.tooltipHidden),
  };

  return (
    <div style={styles.overlay} data-testid="walkthrough-overlay" role="dialog" aria-label="Guided walkthrough">
      {/* Spotlight cutout */}
      <div style={spotlightStyle} data-testid="walkthrough-spotlight" />

      {/* Tooltip */}
      <div ref={tooltipRef} style={tooltipStyle} data-testid="walkthrough-tooltip">
        <TooltipArrow position={step.position} />

        <h3 style={styles.title}>{step.title}</h3>
        <p style={styles.description}>{step.description}</p>

        <div style={styles.footer}>
          {/* Progress dots */}
          <div style={styles.progressDots}>
            {WALKTHROUGH_STEPS.map((_, i) => (
              <div
                key={i}
                style={{
                  ...styles.dot,
                  background: i === currentStep ? '#3b82f6' : i < currentStep ? '#6366f1' : '#334155',
                  transform: i === currentStep ? 'scale(1.4)' : 'scale(1)',
                }}
              />
            ))}
            <span style={{ ...styles.progress, marginLeft: 8 }}>
              {currentStep + 1} of {totalSteps}
            </span>
          </div>

          {/* Buttons */}
          <div style={styles.buttons}>
            <button
              onClick={handleSkip}
              style={{ ...styles.btnBase, ...styles.btnSkip }}
              data-testid="walkthrough-skip"
            >
              Skip
            </button>
            {!isFirst && (
              <button
                onClick={handleBack}
                style={{ ...styles.btnBase, ...styles.btnBack }}
                data-testid="walkthrough-back"
              >
                Back
              </button>
            )}
            <button
              onClick={handleNext}
              style={{ ...styles.btnBase, ...styles.btnNext }}
              data-testid="walkthrough-next"
            >
              {isLast ? 'Finish' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
