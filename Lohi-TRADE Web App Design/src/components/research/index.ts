/**
 * Barrel exports for Lohi-Research UI components.
 *
 * Keeps imports in pages + tests concise:
 *
 * ```ts
 * import { RunTraceDrawer, BriefViewer } from '../components/research';
 * ```
 *
 * Task 20.3 — Req 13.3, 13.4, design §15.
 */

export { default as AgentCard } from './AgentCard';
export { default as BriefViewer, tokenizeSection } from './BriefViewer';
export { default as CitationDrawer } from './CitationDrawer';
export { default as JudgeVerifyingBadge } from './JudgeVerifyingBadge';
export { default as NoDataState } from './NoDataState';
export { default as RefusalBanner } from './RefusalBanner';
export {
  default as RunTraceDrawer,
  formatWallTime,
  minGroundednessScore,
  chunkCountFor,
} from './RunTraceDrawer';

export type {
  RunTraceDrawerProps,
  RunTracePayload,
  TraceBody,
  TraceProvenanceEntry,
  TraceGuardrailDecision,
  TraceJudgeReport,
} from './RunTraceDrawer';
