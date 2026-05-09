/**
 * `/research/chat` — ResearchChatPage.
 *
 * Multi-turn research chat with tool-call transparency. Every Sub_Agent
 * invocation renders as a collapsible `AgentCard` beside the assistant's
 * turn so users can see exactly which tools were called, what chunks
 * were retrieved, and how long each agent took.
 *
 * Task 17.5 — Requirements: 6.3, design §3.13.
 */

import { useMemo, useState } from 'react';
import { Brain, Loader2, Send, User, Bot } from 'lucide-react';
import PageHeader from '../../components/shared/PageHeader';
import RefusalBanner from '../../components/research/RefusalBanner';
import BriefViewer from '../../components/research/BriefViewer';
import AgentCard from '../../components/research/AgentCard';
import { useThemeColors } from '../../hooks/use-theme-colors';
import { useResearchStream } from '../../hooks/use-research-stream';
import { useResearchStore } from '../../stores/research-store';
import { researchApi } from '../../lib/research-api';
import type { AgentResult } from '../../lib/research-types';

interface ChatTurn {
  role: 'user' | 'assistant';
  text?: string;
  runId?: string;
}

export default function ResearchChatPage() {
  const t = useThemeColors();
  const [input, setInput] = useState('');
  const [symbol, setSymbol] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);

  const startRun = useResearchStore((s) => s.startRun);
  const runs = useResearchStore((s) => s.runs);
  const activeRunId = useResearchStore((s) => s.activeRunId);
  useResearchStream(activeRunId);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await researchApi.startResearchRun({
        prompt: text,
        symbol: symbol.trim() || undefined,
      });
      startRun({ runId: res.run_id, symbol: symbol.trim() || null, prompt: text });
      setTurns((prev) => [
        ...prev,
        { role: 'user', text },
        { role: 'assistant', runId: res.run_id },
      ]);
      setInput('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to send message.');
    } finally {
      setSubmitting(false);
    }
  }

  const card: React.CSSProperties = {
    background: t.bgCardGradient,
    border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<Brain size={16} />}
        title="Research Chat"
        subtitle="Multi-turn research with tool-call transparency"
      />

      <RefusalBanner compact />

      <div
        style={{
          ...card,
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          minHeight: 320,
        }}
      >
        {turns.length === 0 ? (
          <p style={{ fontSize: 13, color: t.textMuted, margin: '12px 0' }}>
            Ask about a symbol, a sector, or a filing. Each Sub_Agent call is rendered
            inline so you can audit the tool calls.
          </p>
        ) : (
          turns.map((turn, i) => (
            <Turn key={i} turn={turn} runs={runs} />
          ))
        )}

        {error ? (
          <p style={{ fontSize: 12, color: t.warn as string, margin: 0 }}>{error}</p>
        ) : null}
      </div>

      <form
        onSubmit={handleSend}
        style={{
          ...card,
          padding: 14,
          display: 'flex',
          gap: 8,
          alignItems: 'center',
        }}
      >
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="Symbol"
          style={{
            flex: '0 0 120px',
            background: t.inputBg,
            border: `1px solid ${t.inputBorder}`,
            borderRadius: 10,
            padding: '10px 12px',
            fontSize: 13,
            color: t.textPrimary,
            outline: 'none',
          }}
          aria-label="Symbol"
        />
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a research question…"
          style={{
            flex: 1,
            background: t.inputBg,
            border: `1px solid ${t.inputBorder}`,
            borderRadius: 10,
            padding: '10px 12px',
            fontSize: 13,
            color: t.textPrimary,
            outline: 'none',
          }}
          aria-label="Chat message"
        />
        <button
          type="submit"
          disabled={!input.trim() || submitting}
          style={{
            all: 'unset',
            cursor: !input.trim() || submitting ? 'not-allowed' : 'pointer',
            padding: '10px 16px',
            borderRadius: 10,
            fontSize: 13,
            fontWeight: 600,
            color: '#fff',
            background: 'var(--accent)',
            opacity: !input.trim() || submitting ? 0.6 : 1,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          {submitting ? <Loader2 size={14} className="spin" aria-hidden /> : <Send size={14} aria-hidden />}
          Send
        </button>
      </form>
    </div>
  );
}

function Turn({
  turn,
  runs,
}: {
  turn: ChatTurn;
  runs: Record<string, ReturnType<typeof useResearchStore.getState>['runs'][string]>;
}) {
  const t = useThemeColors();
  const isUser = turn.role === 'user';
  const run = turn.runId ? runs[turn.runId] : null;
  const partials = useMemo<AgentResult[]>(
    () => (run ? (Object.values(run.partials).filter(Boolean) as AgentResult[]) : []),
    [run],
  );

  if (isUser) {
    return (
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: t.bgMuted,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: t.textSecondary,
            flexShrink: 0,
          }}
        >
          <User size={14} aria-hidden />
        </div>
        <div
          style={{
            flex: 1,
            fontSize: 13,
            color: t.textPrimary,
            lineHeight: 1.5,
            padding: '6px 0',
          }}
        >
          {turn.text}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: '50%',
          background: t.accentBg,
          color: t.accentText,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Bot size={14} aria-hidden />
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {partials.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {partials.map((p) => (
              <AgentCard key={p.agent} result={p} />
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 12, color: t.textMuted, margin: 0 }}>
            {run?.error
              ? run.error.message
              : run?.streamingState === 'error'
                ? 'Stream error.'
                : 'Waiting for agents…'}
          </p>
        )}
        {run?.brief ? (
          <BriefViewer
            brief={run.brief}
            streaming={
              run.streamingState === 'streaming' || run.streamingState === 'starting'
            }
          />
        ) : null}
      </div>
    </div>
  );
}
