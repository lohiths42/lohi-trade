import { motion, AnimatePresence } from 'motion/react';
import { Lightbulb, X } from 'lucide-react';
import { useEffect } from 'react';
import LohiAvatar from './LohiAvatar';

/**
 * KnowledgeBomb — Lohi's celebratory finance tip after a tough task.
 *
 * Slides up from the bottom-right, auto-dismisses after 7s, manual close
 * button available. A tiny sparkle animation plays on entry. The whole
 * thing is opt-in — only renders when `bomb` is non-null.
 */
export default function KnowledgeBomb({
  bomb,
  onDismiss,
}: {
  bomb: { title: string; tip: string } | null;
  onDismiss?: () => void;
}) {
  useEffect(() => {
    if (!bomb) return;
    const t = setTimeout(() => onDismiss?.(), 7000);
    return () => clearTimeout(t);
  }, [bomb, onDismiss]);

  return (
    <AnimatePresence>
      {bomb && (
        <motion.div
          key="bomb"
          initial={{ opacity: 0, y: 40, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.95 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          style={{
            position: 'fixed',
            right: 24,
            bottom: 24,
            zIndex: 9999,
            maxWidth: 380,
          }}
        >
          <div
            className="ob-glass"
            style={{
              padding: '18px 18px 18px 16px',
              display: 'flex',
              gap: 12,
              borderColor: 'color-mix(in srgb, var(--ob-growth) 35%, transparent)',
              boxShadow:
                '0 1px 0 rgba(255,255,255,0.04) inset, 0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px var(--ob-growth-line)',
            }}
          >
            <div style={{ position: 'relative', flexShrink: 0 }}>
              <LohiAvatar size="sm" speaking />
              {/* Sparkle */}
              <motion.div
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: [0, 1.4, 1], opacity: [0, 1, 0] }}
                transition={{ duration: 1.2, times: [0, 0.4, 1] }}
                style={{
                  position: 'absolute',
                  top: -4,
                  right: -4,
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  background:
                    'radial-gradient(circle, #fff 0%, var(--ob-growth) 60%, transparent 70%)',
                  pointerEvents: 'none',
                }}
              />
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  marginBottom: 6,
                }}
              >
                <Lightbulb size={12} style={{ color: 'var(--ob-growth)' }} />
                <p
                  style={{
                    fontSize: 10,
                    fontWeight: 800,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    color: 'var(--ob-growth)',
                    margin: 0,
                  }}
                >
                  Knowledge Bomb
                </p>
              </div>
              <p
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: 'var(--ob-silver-text)',
                  margin: 0,
                  letterSpacing: '-0.01em',
                }}
              >
                {bomb.title}
              </p>
              <p
                style={{
                  fontSize: 12,
                  color: 'var(--ob-silver-muted)',
                  margin: '4px 0 0',
                  lineHeight: 1.55,
                }}
              >
                {bomb.tip}
              </p>
            </div>

            <button
              onClick={onDismiss}
              aria-label="Dismiss"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--ob-silver-muted)',
                cursor: 'pointer',
                padding: 2,
                alignSelf: 'flex-start',
              }}
            >
              <X size={14} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
