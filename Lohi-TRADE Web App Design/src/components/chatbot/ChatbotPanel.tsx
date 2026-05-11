/**
 * ChatbotPanel — Lohi, your personal quant, in a slide-out panel.
 *
 * Lohi handles every conversation: she waves when the panel opens,
 * shifts to a "focused" mood while thinking, gives a thumbs-up after
 * each successful reply, and stays "happy" at rest. The UI mirrors
 * the rest of the app's dark-glass aesthetic via design tokens.
 *
 * Requirements: 18.1, 20.5, 20.7
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  X, Send, Trash2, Loader2, User,
  TrendingUp, BarChart3, Activity, Zap,
  HelpCircle, RefreshCw, Sparkles,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { api } from '../../lib/api-client';
import type { ChatMessage } from '../../lib/types';
import LohiAvatar, { type LohiAction, type LohiMood } from '../onboarding/LohiAvatar';
import '../../styles/onboarding.css';

/* ─── Quick-action suggestions ───────────────────────────────────────────── */

const QUICK_ACTIONS = [
  { label: "📊 Today's P&L", prompt: 'What is my P&L today?' },
  { label: '📈 Open positions', prompt: 'Show my open positions' },
  { label: '🏆 Best trade', prompt: 'What was my best trade this week?' },
  { label: '📉 Win rate', prompt: 'What is my overall win rate?' },
  { label: '⚡ Recent signals', prompt: 'Show recent trading signals' },
  { label: '🔍 Performance', prompt: 'Show my performance summary for this month' },
];

/* ─── Chart Renderer ─────────────────────────────────────────────────────── */

function ChatChart({ data, type }: { data: string; type?: string | null }) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const isSvg = data.trimStart().startsWith('<svg') || data.trimStart().startsWith('<?xml');

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as SVGElement | HTMLElement;
    const title = target.getAttribute('title') ||
      target.closest('[title]')?.getAttribute('title') ||
      target.querySelector('title')?.textContent ||
      target.getAttribute('data-value');

    if (title) {
      const rect = containerRef.current?.getBoundingClientRect();
      if (rect) {
        setTooltip({
          x: e.clientX - rect.left,
          y: e.clientY - rect.top - 30,
          text: title,
        });
      }
    } else {
      setTooltip(null);
    }
  }, []);

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  if (isSvg) {
    return (
      <div
        ref={containerRef}
        style={{
          marginTop: 8, borderRadius: 'var(--r-sm)', overflow: 'hidden',
          border: '1px solid var(--line-2)', background: 'var(--surface-1)',
          position: 'relative',
        }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        dangerouslySetInnerHTML={{ __html: data }}
      />
    );
  }

  const mimeType = type === 'png' ? 'image/png' : type === 'jpeg' ? 'image/jpeg' : 'image/svg+xml';
  const src = data.startsWith('data:') ? data : `data:${mimeType};base64,${data}`;

  return (
    <div ref={containerRef} style={{
      marginTop: 8, borderRadius: 'var(--r-sm)', overflow: 'hidden',
      border: '1px solid var(--line-2)', position: 'relative',
    }}>
      <img src={src} alt="Chart" style={{ width: '100%', maxHeight: 300, display: 'block' }} />
      {tooltip && (
        <div
          style={{
            position: 'absolute', pointerEvents: 'none', zIndex: 10,
            padding: '4px 8px', borderRadius: 4,
            fontSize: 11, fontFamily: 'ui-monospace, monospace',
            left: tooltip.x, top: tooltip.y,
            background: 'rgba(0,0,0,0.9)', color: '#fff',
            transform: 'translateX(-50%)', whiteSpace: 'nowrap',
          }}
        >
          {tooltip.text}
        </div>
      )}
    </div>
  );
}

/* ─── Markdown-lite renderer for Lohi's messages ─────────────────────────── */

function FormattedContent({ text }: { text: string }) {
  const lines = text.split('\n');
  return (
    <div style={{ fontSize: 13, lineHeight: 1.55 }}>
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={i} style={{ height: 4 }} />;

        if (trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
          return (
            <div key={i} style={{ display: 'flex', gap: 6, paddingLeft: 4, marginTop: 2 }}>
              <span style={{ opacity: 0.5, color: 'var(--accent-2)' }}>•</span>
              <span>{renderInline(trimmed.slice(2))}</span>
            </div>
          );
        }

        const numMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
        if (numMatch) {
          return (
            <div key={i} style={{ display: 'flex', gap: 6, paddingLeft: 4, marginTop: 2 }}>
              <span style={{
                opacity: 0.5, fontSize: 11, fontFamily: 'ui-monospace, monospace',
                color: 'var(--accent-2)', fontWeight: 700,
              }}>
                {numMatch[1]}.
              </span>
              <span>{renderInline(numMatch[2])}</span>
            </div>
          );
        }

        return <p key={i} style={{ margin: '0 0 2px' }}>{renderInline(trimmed)}</p>;
      })}
    </div>
  );
}

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(₹[\d,]+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?%|\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <span key={i} style={{ fontWeight: 700, color: 'var(--fg-primary)' }}>{part.slice(2, -2)}</span>;
    }
    if (part.startsWith('₹')) {
      return (
        <span key={i} className="lt-tabular" style={{ fontWeight: 700, color: 'var(--fg-primary)' }}>
          {part}
        </span>
      );
    }
    if (part.match(/^[+-]?\d+(?:\.\d+)?%$/)) {
      const isPositive = !part.startsWith('-');
      return (
        <span key={i} className="lt-tabular" style={{
          fontWeight: 700, color: isPositive ? 'var(--bull)' : 'var(--bear)',
        }}>
          {part}
        </span>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

/* ─── Message Bubble ─────────────────────────────────────────────────────── */

function MessageBubble({ msg, index }: { msg: ChatMessage; index: number }) {
  const isUser = msg.role === 'user';

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.02, 0.1), ease: [0.22, 1, 0.36, 1] }}
      style={{
        display: 'flex', gap: 10,
        flexDirection: isUser ? 'row-reverse' : 'row',
        alignItems: 'flex-end',
      }}
    >
      {/* Avatar */}
      <div style={{ flexShrink: 0 }}>
        {isUser ? (
          <div
            style={{
              width: 30, height: 30, borderRadius: 'var(--r-sm)',
              display: 'grid', placeItems: 'center',
              background: 'var(--accent-gradient)',
              boxShadow: '0 4px 10px var(--accent-glow)',
            }}
          >
            <User size={14} color="#fff" />
          </div>
        ) : (
          <div style={{ width: 30, height: 30 * 1.35, display: 'grid', placeItems: 'center' }}>
            <LohiAvatar size="sm" speaking={false} mood="happy" />
          </div>
        )}
      </div>

      {/* Bubble */}
      <div
        style={{
          maxWidth: '82%',
          borderRadius: 'var(--r-md)',
          padding: '10px 14px',
          background: isUser
            ? 'var(--accent-gradient)'
            : 'color-mix(in srgb, var(--surface-3) 92%, transparent)',
          color: isUser ? '#fff' : 'var(--fg-primary)',
          border: isUser ? 'none' : '1px solid var(--line-2)',
          boxShadow: isUser
            ? '0 4px 14px var(--accent-glow)'
            : '0 2px 8px rgba(0,0,0,0.25)',
          borderBottomRightRadius: isUser ? 4 : 'var(--r-md)',
          borderBottomLeftRadius: isUser ? 'var(--r-md)' : 4,
        }}
      >
        {isUser ? (
          <p style={{
            fontSize: 13, lineHeight: 1.55, whiteSpace: 'pre-wrap', margin: 0,
          }}>
            {msg.content}
          </p>
        ) : (
          <FormattedContent text={msg.content} />
        )}

        {msg.chartData && <ChatChart data={msg.chartData} type={msg.chartType} />}

        {msg.sources && msg.sources.length > 0 && (
          <div style={{
            marginTop: 10, paddingTop: 8,
            borderTop: isUser ? '1px solid rgba(255,255,255,0.2)' : '1px solid var(--line-2)',
          }}>
            <p style={{
              fontSize: 10, fontWeight: 700, opacity: 0.7, margin: '0 0 4px',
              letterSpacing: '0.1em', textTransform: 'uppercase',
            }}>
              Sources
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {msg.sources.map((s, i) => (
                <span
                  key={i}
                  style={{
                    fontSize: 10, padding: '2px 6px', borderRadius: 4,
                    background: isUser ? 'rgba(255,255,255,0.2)' : 'color-mix(in srgb, var(--accent) 14%, transparent)',
                    color: isUser ? '#fff' : 'var(--accent-2)',
                    fontWeight: 600,
                  }}
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
          <p style={{ fontSize: 9, opacity: 0.5, margin: 0 }}>
            {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </p>
          {!isUser && msg.responseTimeMs && msg.responseTimeMs > 0 && (
            <p style={{ fontSize: 9, opacity: 0.4, margin: 0 }}>
              {msg.responseTimeMs}ms
            </p>
          )}
        </div>
      </div>
    </motion.div>
  );
}

/* ─── Quick Action Chips ─────────────────────────────────────────────────── */

function QuickActionChips({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '0 4px' }}>
      {QUICK_ACTIONS.map((action, i) => (
        <motion.button
          key={action.label}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: i * 0.04 }}
          whileHover={{ y: -1 }}
          whileTap={{ scale: 0.97 }}
          onClick={() => onSelect(action.prompt)}
          style={{
            fontSize: 11, padding: '6px 12px', borderRadius: 'var(--r-pill)',
            background: 'color-mix(in srgb, var(--accent) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent) 22%, transparent)',
            color: 'var(--accent-2)', cursor: 'pointer', fontWeight: 600,
          }}
        >
          {action.label}
        </motion.button>
      ))}
    </div>
  );
}

/* ─── Connection Banner ──────────────────────────────────────────────────── */

function ConnectionBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      style={{
        margin: '8px 16px 0',
        padding: '8px 12px', borderRadius: 'var(--r-sm)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: 'var(--warn-soft)',
        border: '1px solid color-mix(in srgb, var(--warn) 28%, transparent)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <HelpCircle size={13} color="var(--warn)" />
        <span style={{ fontSize: 11, color: 'var(--warn)', fontWeight: 600 }}>
          Lohi can&apos;t reach the brain right now
        </span>
      </div>
      <button
        onClick={onRetry}
        aria-label="Retry connection"
        style={{
          padding: 4, borderRadius: 4, background: 'transparent',
          border: 'none', cursor: 'pointer', display: 'flex',
        }}
      >
        <RefreshCw size={12} color="var(--warn)" />
      </button>
    </motion.div>
  );
}

/* ─── Typing dots ────────────────────────────────────────────────────────── */

function TypingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', padding: '0 2px' }}>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ y: [0, -3, 0], opacity: [0.4, 1, 0.4] }}
          transition={{
            duration: 1, repeat: Infinity,
            ease: 'easeInOut', delay: i * 0.15,
          }}
          style={{
            width: 5, height: 5, borderRadius: '50%',
            background: 'var(--accent-2)',
            boxShadow: '0 0 6px var(--accent-glow)',
          }}
        />
      ))}
    </span>
  );
}

/* ─── ChatbotPanel ───────────────────────────────────────────────────────── */

export default function ChatbotPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Lohi gesture state
  const [lohiAction, setLohiAction] = useState<LohiAction>('wave');
  const [lohiActionKey, setLohiActionKey] = useState(0);
  const [lohiMood, setLohiMood] = useState<LohiMood>('happy');

  const trigger = (a: LohiAction, mood: LohiMood = 'happy') => {
    setLohiAction(a);
    setLohiMood(mood);
    setLohiActionKey((k) => k + 1);
  };

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Focus input when panel opens + wave hello
  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
      trigger('wave', 'happy');
    }
  }, [open]);

  // Load history when panel first opens
  useEffect(() => {
    if (open && !historyLoaded) {
      setHistoryLoaded(true);
      api.getChatHistory().then((res) => {
        const loaded: ChatMessage[] = res.messages.map((m, i) => ({
          id: `hist-${i}`,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: m.timestamp || new Date().toISOString(),
        }));
        setMessages(loaded);
        setConnectionError(false);
      }).catch(() => {
        setConnectionError(true);
      });
    }
  }, [open, historyLoaded]);

  const sendMessage = async (text?: string) => {
    const msgText = (text ?? input).trim();
    if (!msgText || loading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: msgText,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setConnectionError(false);
    trigger('idle', 'focused'); // Lohi thinks

    try {
      const res = await api.sendChatMessage(msgText);
      const botMsg: ChatMessage = {
        id: `bot-${Date.now()}`,
        role: 'assistant',
        content: res.text,
        chartData: res.chart_data ?? undefined,
        chartType: res.chart_type ?? undefined,
        sources: res.sources,
        responseTimeMs: res.response_time_ms,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, botMsg]);
      trigger('thumbsUp', 'happy'); // Lohi celebrates success
    } catch {
      setConnectionError(true);
      const errMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: "Hmm, something stalled on my end. The brain might be taking a breather. Mind trying that again?",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
      trigger('idle', 'neutral');
    } finally {
      setLoading(false);
    }
  };

  const clearSession = async () => {
    try {
      await api.clearChatSession();
      setMessages([]);
      setHistoryLoaded(false);
      setConnectionError(false);
      trigger('wave', 'happy');
    } catch {
      /* ignore */
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleRetry = () => {
    setHistoryLoaded(false);
    setConnectionError(false);
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          {/* Scrim */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            style={{
              position: 'fixed', inset: 0, zIndex: 49,
              background: 'var(--scrim)',
              backdropFilter: 'saturate(140%) blur(6px)',
              WebkitBackdropFilter: 'saturate(140%) blur(6px)',
            }}
          />

          <motion.div
            initial={{ x: 420, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 420, opacity: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            style={{
              position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 50,
              width: 420, maxWidth: '100vw',
              display: 'flex', flexDirection: 'column',
              background: 'color-mix(in srgb, var(--surface-1) 88%, transparent)',
              backdropFilter: 'saturate(140%) blur(22px)',
              WebkitBackdropFilter: 'saturate(140%) blur(22px)',
              borderLeft: '1px solid var(--line-2)',
              boxShadow: '-12px 0 40px rgba(0,0,0,0.5)',
            }}
          >
            {/* Ambient orb */}
            <div
              aria-hidden
              style={{
                position: 'absolute', top: -80, right: -60,
                width: 260, height: 260, borderRadius: '50%',
                background: 'radial-gradient(circle, color-mix(in srgb, var(--accent) 22%, transparent) 0%, transparent 70%)',
                filter: 'blur(40px)', pointerEvents: 'none',
              }}
            />

            {/* Header */}
            <div
              style={{
                position: 'relative', zIndex: 1,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 18px',
                borderBottom: '1px solid var(--line-2)',
                background: 'color-mix(in srgb, var(--surface-1) 72%, transparent)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 44, height: 44 * 1.35, display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                  <LohiAvatar
                    size="sm"
                    speaking={loading}
                    thinking={loading}
                    action={lohiAction}
                    actionKey={lohiActionKey}
                    mood={lohiMood}
                  />
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <p style={{
                      fontSize: 15, fontWeight: 800, margin: 0,
                      color: 'var(--fg-primary)', letterSpacing: '-0.01em',
                    }}>
                      Lohi
                    </p>
                    <span style={{
                      fontSize: 9, fontWeight: 700, letterSpacing: '0.12em',
                      padding: '2px 6px', borderRadius: 4,
                      background: loading
                        ? 'var(--warn-soft)'
                        : 'color-mix(in srgb, var(--bull) 14%, transparent)',
                      color: loading ? 'var(--warn)' : 'var(--bull)',
                      textTransform: 'uppercase',
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                    }}>
                      <span style={{
                        width: 5, height: 5, borderRadius: '50%',
                        background: loading ? 'var(--warn)' : 'var(--bull)',
                        boxShadow: `0 0 6px ${loading ? 'var(--warn)' : 'var(--bull)'}`,
                      }} />
                      {loading ? 'Thinking' : 'Live'}
                    </span>
                  </div>
                  <p style={{
                    fontSize: 11, margin: '2px 0 0', color: 'var(--fg-muted)',
                  }}>
                    Your personal quant · Trades · P&L · Signals
                  </p>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <button
                  onClick={clearSession}
                  aria-label="Clear chat"
                  title="Clear chat"
                  style={{
                    padding: 7, borderRadius: 'var(--r-sm)',
                    color: 'var(--fg-muted)',
                    background: 'transparent', border: '1px solid transparent',
                    cursor: 'pointer', transition: 'all var(--dur-2) var(--ease-out)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-3)'; e.currentTarget.style.borderColor = 'var(--line-2)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'transparent'; }}
                >
                  <Trash2 size={14} />
                </button>
                <button
                  onClick={onClose}
                  aria-label="Close"
                  style={{
                    padding: 7, borderRadius: 'var(--r-sm)',
                    color: 'var(--fg-secondary)',
                    background: 'transparent', border: '1px solid transparent',
                    cursor: 'pointer', transition: 'all var(--dur-2) var(--ease-out)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-3)'; e.currentTarget.style.borderColor = 'var(--line-2)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'transparent'; }}
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <AnimatePresence>
              {connectionError && <ConnectionBanner onRetry={handleRetry} />}
            </AnimatePresence>

            {/* Messages area */}
            <div
              className="lt-scroll"
              style={{
                flex: 1, overflowY: 'auto', overflowX: 'hidden',
                padding: '20px 18px',
                display: 'flex', flexDirection: 'column', gap: 14,
                position: 'relative', zIndex: 1,
              }}
            >
              {messages.length === 0 && !loading && <EmptyState onPick={sendMessage} />}

              {messages.map((msg, i) => (
                <MessageBubble key={msg.id} msg={msg} index={i} />
              ))}

              {loading && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}
                >
                  <div style={{ width: 30, height: 30 * 1.35, display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                    <LohiAvatar size="sm" thinking mood="focused" />
                  </div>
                  <div
                    style={{
                      padding: '10px 14px', borderRadius: 'var(--r-md)',
                      borderBottomLeftRadius: 4,
                      background: 'color-mix(in srgb, var(--surface-3) 92%, transparent)',
                      border: '1px solid var(--line-2)',
                      display: 'inline-flex', alignItems: 'center', gap: 10,
                    }}
                  >
                    <TypingDots />
                    <span style={{ fontSize: 11, color: 'var(--fg-muted)', fontWeight: 500 }}>
                      Lohi is thinking…
                    </span>
                  </div>
                </motion.div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Quick actions below messages when conversation is active */}
            {messages.length > 0 && !loading && (
              <div
                className="lt-scroll"
                style={{
                  flexShrink: 0, padding: '8px 18px 10px',
                  overflowX: 'auto',
                  borderTop: '1px solid var(--line-1)',
                  background: 'color-mix(in srgb, var(--surface-1) 60%, transparent)',
                }}
              >
                <div style={{ display: 'flex', gap: 6, paddingBottom: 2 }}>
                  {QUICK_ACTIONS.slice(0, 4).map((action) => (
                    <button
                      key={action.label}
                      onClick={() => sendMessage(action.prompt)}
                      style={{
                        fontSize: 10, padding: '5px 10px', borderRadius: 'var(--r-pill)',
                        whiteSpace: 'nowrap',
                        background: 'color-mix(in srgb, var(--accent) 8%, transparent)',
                        border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)',
                        color: 'var(--accent-2)', cursor: 'pointer', fontWeight: 600,
                        flexShrink: 0,
                      }}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Input area */}
            <div
              style={{
                flexShrink: 0, padding: '14px 18px 18px',
                borderTop: '1px solid var(--line-2)',
                background: 'color-mix(in srgb, var(--surface-1) 72%, transparent)',
                position: 'relative', zIndex: 1,
              }}
            >
              <div
                style={{
                  display: 'flex', alignItems: 'flex-end', gap: 10,
                  borderRadius: 'var(--r-md)', padding: '8px 8px 8px 14px',
                  background: 'var(--surface-2)',
                  border: `1px solid ${input.trim() ? 'color-mix(in srgb, var(--accent) 38%, var(--line-2))' : 'var(--line-2)'}`,
                  boxShadow: input.trim()
                    ? '0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent)'
                    : 'none',
                  transition: 'border-color var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out)',
                }}
              >
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask Lohi anything…"
                  disabled={loading}
                  rows={1}
                  style={{
                    flex: 1, background: 'transparent', border: 'none', outline: 'none',
                    fontSize: 13, color: 'var(--fg-primary)',
                    resize: 'none', fontFamily: 'inherit',
                    maxHeight: 120, minHeight: 22, lineHeight: 1.5,
                    padding: '4px 0',
                  }}
                />
                <button
                  onClick={() => sendMessage()}
                  disabled={!input.trim() || loading}
                  aria-label="Send message"
                  style={{
                    padding: 8, borderRadius: 'var(--r-sm)',
                    background: input.trim() && !loading ? 'var(--accent-gradient)' : 'var(--surface-3)',
                    border: 'none', display: 'grid', placeItems: 'center',
                    cursor: input.trim() && !loading ? 'pointer' : 'default',
                    opacity: input.trim() && !loading ? 1 : 0.45,
                    boxShadow: input.trim() && !loading ? '0 4px 12px var(--accent-glow)' : 'none',
                    transition: 'all var(--dur-2) var(--ease-out)',
                    flexShrink: 0,
                  }}
                >
                  {loading
                    ? <Loader2 size={14} color="var(--fg-muted)" className="animate-spin" />
                    : <Send size={14} color={input.trim() ? '#fff' : 'var(--fg-muted)'} />}
                </button>
              </div>
              <p style={{
                fontSize: 10, color: 'var(--fg-muted)', margin: '8px 0 0',
                textAlign: 'center',
              }}>
                <kbd style={{
                  fontSize: 9, padding: '1px 5px', borderRadius: 3,
                  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
                  fontFamily: 'ui-monospace, monospace', color: 'var(--fg-muted)',
                }}>↵</kbd>
                {' '}to send · {' '}
                <kbd style={{
                  fontSize: 9, padding: '1px 5px', borderRadius: 3,
                  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
                  fontFamily: 'ui-monospace, monospace', color: 'var(--fg-muted)',
                }}>Shift + ↵</kbd>
                {' '}for a new line
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/* ─── Empty state ─────────────────────────────────────────────────────── */

function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  const caps = [
    { icon: TrendingUp, label: 'P&L analysis', desc: 'Daily, weekly, monthly' },
    { icon: Activity, label: 'Positions', desc: 'Open & closed trades' },
    { icon: BarChart3, label: 'Charts', desc: 'Equity & candlestick' },
    { icon: Zap, label: 'Signals', desc: 'Why trades fired' },
  ];
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', textAlign: 'center',
        paddingTop: 12,
      }}
    >
      <div style={{ marginBottom: 16 }}>
        <LohiAvatar size="md" speaking mood="happy" action="wave" actionKey={1} />
      </div>

      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 10,
        padding: '4px 12px', borderRadius: 'var(--r-pill)',
        background: 'color-mix(in srgb, var(--accent) 10%, transparent)',
        border: '1px solid color-mix(in srgb, var(--accent) 22%, transparent)',
      }}>
        <Sparkles size={11} color="var(--accent-2)" />
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.12em',
          color: 'var(--accent-2)', textTransform: 'uppercase',
        }}>
          I&apos;m Lohi
        </span>
      </div>

      <p style={{
        fontSize: 18, fontWeight: 700, color: 'var(--fg-primary)',
        margin: '0 0 6px', letterSpacing: '-0.02em',
      }}>
        Hey there — how can I help?
      </p>
      <p style={{
        fontSize: 13, color: 'var(--fg-muted)', margin: '0 0 20px',
        maxWidth: 300, lineHeight: 1.5,
      }}>
        Ask about your trades, P&L, strategies, or any stock. I see your whole terminal.
      </p>

      {/* Capability grid */}
      <div style={{
        width: '100%',
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
        marginBottom: 20,
      }}>
        {caps.map((cap, i) => (
          <motion.div
            key={cap.label}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.05 * i }}
            className="lt-bento"
            style={{ padding: 12, textAlign: 'left' }}
          >
            <div style={{
              width: 26, height: 26, borderRadius: 'var(--r-xs)',
              background: 'color-mix(in srgb, var(--accent) 14%, transparent)',
              border: '1px solid color-mix(in srgb, var(--accent) 22%, transparent)',
              display: 'grid', placeItems: 'center', marginBottom: 8,
            }}>
              <cap.icon size={13} color="var(--accent-2)" />
            </div>
            <p style={{
              fontSize: 12, fontWeight: 700, margin: 0,
              color: 'var(--fg-primary)', letterSpacing: '-0.01em',
            }}>
              {cap.label}
            </p>
            <p style={{
              fontSize: 10, color: 'var(--fg-muted)', margin: '2px 0 0',
            }}>
              {cap.desc}
            </p>
          </motion.div>
        ))}
      </div>

      {/* Quick actions */}
      <div style={{ width: '100%' }}>
        <p style={{
          fontSize: 10, fontWeight: 800, letterSpacing: '0.14em',
          textTransform: 'uppercase', color: 'var(--fg-muted)',
          margin: '0 0 8px', textAlign: 'left',
        }}>
          Try one of these
        </p>
        <QuickActionChips onSelect={onPick} />
      </div>
    </motion.div>
  );
}
