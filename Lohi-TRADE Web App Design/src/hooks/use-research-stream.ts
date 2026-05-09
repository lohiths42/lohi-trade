/**
 * `useResearchStream` — subscribes to the `research:<run_id>` Socket.IO
 * channel and dispatches events into the `useResearchStore`.
 *
 * Wraps the existing `use-websocket` lifecycle so the caller just needs
 * a `runId` and the hook takes care of:
 *
 *   - attaching event listeners on mount (one per Socket.IO event)
 *   - filtering every payload by `runId` (defensive against cross-run bleed)
 *   - handling reconnect gracefully — on reconnect the server replays the
 *     run's current state; we keep appending, relying on
 *     `mergeAgentPartial` / `mergeCitations` to dedupe citations by chunk_id
 *   - cleaning up listeners on unmount / runId change
 *
 * Task 17.2 — Requirements: 6.4, design §3.13, §5.2.
 */

import { useEffect } from 'react';
import { ws } from '../lib/websocket-client';
import { useResearchStore } from '../stores/research-store';
import type {
  ResearchAgentDoneEvent,
  ResearchAgentPartialEvent,
  ResearchDoneEvent,
  ResearchErrorEvent,
  ResearchGuardrailDecisionEvent,
  ResearchJudgeReportEvent,
  ResearchLatencyBudgetExceededEvent,
  ResearchTokenEvent,
} from '../lib/research-types';

// Socket.IO events the backend emits on the research channel (design §5.2).
const EV_TOKEN = 'research:token';
const EV_AGENT_PARTIAL = 'research:agent_partial';
const EV_AGENT_DONE = 'research:agent_done';
const EV_GUARDRAIL = 'research:guardrail_decision';
const EV_JUDGE = 'research:judge_report';
const EV_DONE = 'research:done';
const EV_ERROR = 'research:error';
const EV_LATENCY = 'research:latency_budget_exceeded';

type ResearchEventPayload =
  | ResearchTokenEvent
  | ResearchAgentPartialEvent
  | ResearchAgentDoneEvent
  | ResearchGuardrailDecisionEvent
  | ResearchJudgeReportEvent
  | ResearchDoneEvent
  | ResearchErrorEvent
  | ResearchLatencyBudgetExceededEvent;

function hasRunId(payload: unknown): payload is { run_id: string } {
  return (
    typeof payload === 'object'
    && payload !== null
    && typeof (payload as { run_id?: unknown }).run_id === 'string'
  );
}

/**
 * Subscribe to the live research stream for a single `runId`.
 *
 * @param runId The active run to monitor. When `null`/`undefined`, the hook
 *              is a no-op — useful for conditional mounts before a run has
 *              started.
 */
export function useResearchStream(runId: string | null | undefined): void {
  useEffect(() => {
    if (!runId) return;

    const store = useResearchStore;

    // Ensure the socket is connected. `useWebSocket` at the App shell also
    // calls connect(); socket.io-client is idempotent.
    ws.connect();

    // ── Handlers ─────────────────────────────────────────────────────
    const onToken = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      store.getState().recordToken(runId);
    };

    const onAgentPartial = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      const { result } = payload as ResearchAgentPartialEvent;
      if (!result) return;
      store.getState().mergeAgentPartial(runId, result);
    };

    const onAgentDone = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      const { result } = payload as ResearchAgentDoneEvent;
      if (!result) return;
      store.getState().mergeAgentPartial(runId, result);
    };

    const onGuardrail = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      const { decision } = payload as ResearchGuardrailDecisionEvent;
      if (!decision) return;
      store.getState().applyGuardrailDecision(runId, decision);
    };

    const onJudge = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      const { report } = payload as ResearchJudgeReportEvent;
      if (!report) return;
      store.getState().applyJudgeReport(runId, report);
    };

    const onDone = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      const { brief } = payload as ResearchDoneEvent;
      if (!brief) return;
      store.getState().completeRun(runId, brief);
    };

    const onError = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      const err = payload as ResearchErrorEvent;
      store.getState().setError(runId, {
        code: err.code,
        message: err.message,
        provider: err.provider,
        model: err.model,
      });
    };

    const onLatencyBudget = (payload: ResearchEventPayload) => {
      if (!hasRunId(payload) || payload.run_id !== runId) return;
      // Surface as a soft error-like signal; keep streaming state untouched
      // so the brief can still finish. The run trace drawer shows this.
      // For now we just log — UI hooks can subscribe to the store directly.
      const ev = payload as ResearchLatencyBudgetExceededEvent;
      // eslint-disable-next-line no-console
      console.warn(
        `[research] latency budget exceeded: phase=${ev.phase} observed=${ev.observed_ms}ms budget=${ev.budget_ms}ms`,
      );
    };

    // ── Subscribe. We use the raw socket.on API (via the typed shim) ──
    // The existing `ws.on` is strongly typed to WebSocketEventMap and we
    // don't want to pollute that map with research events. Cast per event.
    /* eslint-disable @typescript-eslint/no-explicit-any */
    (ws.on as any)(EV_TOKEN, onToken);
    (ws.on as any)(EV_AGENT_PARTIAL, onAgentPartial);
    (ws.on as any)(EV_AGENT_DONE, onAgentDone);
    (ws.on as any)(EV_GUARDRAIL, onGuardrail);
    (ws.on as any)(EV_JUDGE, onJudge);
    (ws.on as any)(EV_DONE, onDone);
    (ws.on as any)(EV_ERROR, onError);
    (ws.on as any)(EV_LATENCY, onLatencyBudget);
    /* eslint-enable @typescript-eslint/no-explicit-any */

    return () => {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      (ws.off as any)(EV_TOKEN, onToken);
      (ws.off as any)(EV_AGENT_PARTIAL, onAgentPartial);
      (ws.off as any)(EV_AGENT_DONE, onAgentDone);
      (ws.off as any)(EV_GUARDRAIL, onGuardrail);
      (ws.off as any)(EV_JUDGE, onJudge);
      (ws.off as any)(EV_DONE, onDone);
      (ws.off as any)(EV_ERROR, onError);
      (ws.off as any)(EV_LATENCY, onLatencyBudget);
      /* eslint-enable @typescript-eslint/no-explicit-any */
    };
  }, [runId]);
}

export default useResearchStream;
