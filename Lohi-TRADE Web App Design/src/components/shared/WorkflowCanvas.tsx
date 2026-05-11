/**
 * WorkflowCanvas — interactive DAG diagram for an agentic architecture.
 *
 * This is a real graph, not a pipeline:
 *
 *   • Nodes (agent roles) are laid out topologically into *columns*. The
 *     column index of a node is the longest path from any root to that
 *     node, which pushes parallel siblings into the same column so
 *     fan-out/fan-in reads correctly.
 *
 *   • Within a column, siblings stack vertically. Parallel sub-agents
 *     render side-by-side, not as a single snake.
 *
 *   • Every edge is drawn. Primary edges (from `upstreams`) are solid
 *     with a filled arrowhead. Sideband edges — memory reads, cache
 *     writes, Redis stream side channels, feedback loops — are dashed
 *     and colored by channel kind.
 *
 *   • Cubes only ride the edges that touch the currently-selected node.
 *     When no node is selected (or a node with no edges is selected),
 *     the canvas is completely still so the user can read the graph.
 *     Cube on a feedback edge travels backwards.
 *
 *   • The SVG viewBox is computed from the actual path bounding boxes,
 *     not just the node grid — so feedback curves that dip below the
 *     node rows are always fully visible.
 *
 *   • Responsive: node width and column gap scale with the container.
 *     When the content would still overflow at the minimum readable
 *     size, the canvas scrolls horizontally inside its own box rather
 *     than clipping the graph.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Shield } from 'lucide-react';
import type { WorkflowStep } from './WorkflowSimulator';

// ─── Sideband channel kinds ────────────────────────────────────────────────

export type SidebandKind =
  | 'memory'
  | 'cache'
  | 'stream'
  | 'feedback'
  | 'telemetry';

export interface Sideband {
  to: number;
  label?: string;
  kind?: SidebandKind;
}

// ─── Layout primitives ────────────────────────────────────────────────────

interface NodePos {
  x: number;
  y: number;
  w: number;
  h: number;
  col: number;
  rowInCol: number;
}

interface Layout {
  nodes: NodePos[];
  /** Tight extent of the node grid — not the final viewBox. */
  gridWidth: number;
  gridHeight: number;
}

// ─── Layout constants ─────────────────────────────────────────────────────

const PAD_X = 20;
const PAD_Y = 28;
const NODE_MIN_W = 148;
const NODE_MAX_W = 200;
const NODE_H = 78;
const GAP_X_MIN = 28;
const GAP_X_MAX = 64;
const GAP_Y = 22;
/** Extra vertical headroom we reserve for backward/feedback curves
 *  routing below the lowest row. */
const FEEDBACK_DROP_BELOW = 90;
/** Extra horizontal headroom we reserve for same-column loop-around curves. */
const LOOP_SIDE_PAD = 32;

// ─── Topological column assignment ────────────────────────────────────────

function computeColumns(steps: WorkflowStep[]): number[] {
  const cols = new Array(steps.length).fill(0);
  const visited = new Array(steps.length).fill(false);

  function visit(i: number, stack: Set<number>): number {
    if (stack.has(i)) return cols[i];
    if (visited[i]) return cols[i];
    stack.add(i);
    const ups = steps[i].upstreams ?? (i > 0 ? [i - 1] : []);
    let level = 0;
    for (const u of ups) {
      if (u < 0 || u >= steps.length) continue;
      level = Math.max(level, visit(u, stack) + 1);
    }
    cols[i] = level;
    visited[i] = true;
    stack.delete(i);
    return level;
  }
  for (let i = 0; i < steps.length; i++) visit(i, new Set());
  return cols;
}

// ─── Grid layout ──────────────────────────────────────────────────────────

function layoutGraph(
  steps: WorkflowStep[],
  cols: number[],
  width: number,
): Layout {
  const colCount = Math.max(0, ...cols) + 1;

  const buckets: number[][] = Array.from({ length: colCount }, () => []);
  for (let i = 0; i < steps.length; i++) buckets[cols[i]].push(i);

  // Pick a node width + gap that uses the available canvas width well.
  // When the container is narrow, shrink the node width toward NODE_MIN_W
  // and the gap toward GAP_X_MIN. When it's wide, grow both toward the max.
  const usable = Math.max(NODE_MIN_W * colCount + GAP_X_MIN * (colCount - 1) + PAD_X * 2, width);
  // Solve for `w` given `w * n + gap * (n-1) + 2*pad = usable`, assuming
  // gap is halfway between min/max.
  const gapX = Math.min(
    GAP_X_MAX,
    Math.max(
      GAP_X_MIN,
      Math.floor((usable - PAD_X * 2 - colCount * NODE_MIN_W) / Math.max(1, colCount - 1)),
    ),
  );
  const nodeW = Math.min(
    NODE_MAX_W,
    Math.max(
      NODE_MIN_W,
      Math.floor(
        (usable - PAD_X * 2 - gapX * Math.max(0, colCount - 1)) / Math.max(1, colCount),
      ),
    ),
  );

  const columnX: number[] = Array.from(
    { length: colCount },
    (_, c) => PAD_X + c * (nodeW + gapX),
  );

  const maxRows = Math.max(1, ...buckets.map((b) => b.length));
  const gridHeight = PAD_Y * 2 + maxRows * NODE_H + Math.max(0, maxRows - 1) * GAP_Y;

  const nodes: NodePos[] = new Array(steps.length);
  for (let c = 0; c < colCount; c++) {
    const bucket = buckets[c];
    const colHeight = bucket.length * NODE_H + Math.max(0, bucket.length - 1) * GAP_Y;
    const colY = PAD_Y + (gridHeight - PAD_Y * 2 - colHeight) / 2;
    bucket.forEach((nodeIdx, rowInCol) => {
      nodes[nodeIdx] = {
        x: columnX[c],
        y: colY + rowInCol * (NODE_H + GAP_Y),
        w: nodeW,
        h: NODE_H,
        col: c,
        rowInCol,
      };
    });
  }

  // Fallback for any missing node.
  for (let i = 0; i < nodes.length; i++) {
    if (!nodes[i]) nodes[i] = { x: PAD_X, y: PAD_Y, w: nodeW, h: NODE_H, col: 0, rowInCol: 0 };
  }

  const gridWidth = PAD_X * 2 + colCount * nodeW + Math.max(0, colCount - 1) * gapX;
  return { nodes, gridWidth, gridHeight };
}

// ─── Edge path geometry ───────────────────────────────────────────────────

interface EdgeGeometry {
  path: string;
  /** Axis-aligned bounding box of the path for viewBox extension. */
  bbox: { minX: number; minY: number; maxX: number; maxY: number };
}

function forwardEdge(a: NodePos, b: NodePos): EdgeGeometry {
  const ax = a.x + a.w;
  const ay = a.y + a.h / 2;
  const bx = b.x;
  const by = b.y + b.h / 2;

  if (b.col > a.col) {
    const mid = (ax + bx) / 2;
    return {
      path: `M ${ax} ${ay} C ${mid} ${ay}, ${mid} ${by}, ${bx} ${by}`,
      bbox: {
        minX: Math.min(ax, bx),
        maxX: Math.max(ax, bx),
        minY: Math.min(ay, by),
        maxY: Math.max(ay, by),
      },
    };
  }
  if (b.col === a.col) {
    const pad = LOOP_SIDE_PAD;
    const outX = ax + pad;
    const inX = bx - pad;
    const midY = (ay + by) / 2;
    return {
      path: `M ${ax} ${ay} C ${outX} ${ay}, ${outX} ${midY}, ${ax + pad / 2} ${midY}
             L ${bx - pad / 2} ${midY}
             C ${inX} ${midY}, ${inX} ${by}, ${bx} ${by}`,
      bbox: {
        minX: Math.min(ax, bx) - pad,
        maxX: Math.max(ax, bx) + pad,
        minY: Math.min(ay, by),
        maxY: Math.max(ay, by),
      },
    };
  }
  // b.col < a.col  → backward / feedback — dip below the node rows.
  const dropY = Math.max(ay, by) + FEEDBACK_DROP_BELOW;
  return {
    path: `M ${ax} ${ay}
           C ${ax + LOOP_SIDE_PAD} ${ay}, ${ax + LOOP_SIDE_PAD} ${dropY}, ${ax} ${dropY}
           L ${bx} ${dropY}
           C ${bx - LOOP_SIDE_PAD} ${dropY}, ${bx - LOOP_SIDE_PAD} ${by}, ${bx} ${by}`,
    bbox: {
      minX: Math.min(ax, bx) - LOOP_SIDE_PAD,
      maxX: Math.max(ax, bx) + LOOP_SIDE_PAD,
      minY: Math.min(ay, by),
      maxY: dropY + 2,
    },
  };
}

// ─── Canvas ───────────────────────────────────────────────────────────────

export interface WorkflowCanvasProps {
  steps: WorkflowStep[];
  activeIndex: number;
  onNodeClick?: (index: number) => void;
}

export default function WorkflowCanvas({
  steps,
  activeIndex,
  onNodeClick,
}: WorkflowCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(960);

  useLayoutEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.floor(entry.contentRect.width);
        if (w > 0) setContainerWidth(w);
      }
    });
    ro.observe(el);
    setContainerWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const cols = useMemo(() => computeColumns(steps), [steps]);
  const layout = useMemo(
    () => layoutGraph(steps, cols, containerWidth),
    [steps, cols, containerWidth],
  );
  const activeCol = cols[activeIndex] ?? 0;

  const uid = useMemo(() => `wfc-${Math.random().toString(36).slice(2, 9)}`, []);

  // Build edges with geometry + bbox in one pass.
  const primaryEdges = useMemo(() => {
    const out: {
      from: number;
      to: number;
      path: string;
      bbox: EdgeGeometry['bbox'];
    }[] = [];
    for (let i = 0; i < steps.length; i++) {
      const ups = steps[i].upstreams ?? (i > 0 ? [i - 1] : []);
      for (const u of ups) {
        if (u < 0 || u >= steps.length) continue;
        const { path, bbox } = forwardEdge(layout.nodes[u], layout.nodes[i]);
        out.push({ from: u, to: i, path, bbox });
      }
    }
    return out;
  }, [steps, layout]);

  const sidebandEdges = useMemo(() => {
    const out: {
      from: number;
      to: number;
      path: string;
      bbox: EdgeGeometry['bbox'];
      kind: SidebandKind;
      label?: string;
    }[] = [];
    for (let i = 0; i < steps.length; i++) {
      const bands = steps[i].sidebands ?? [];
      for (const b of bands) {
        if (b.to < 0 || b.to >= steps.length) continue;
        const { path, bbox } = forwardEdge(layout.nodes[i], layout.nodes[b.to]);
        out.push({
          from: i,
          to: b.to,
          path,
          bbox,
          kind: b.kind ?? 'stream',
          label: b.label,
        });
      }
    }
    return out;
  }, [steps, layout]);

  // ── Compute a generous viewBox from the union of node + edge bboxes ──
  const viewBox = useMemo(() => {
    let minX = 0;
    let minY = 0;
    let maxX = layout.gridWidth;
    let maxY = layout.gridHeight;
    for (const n of layout.nodes) {
      maxX = Math.max(maxX, n.x + n.w);
      maxY = Math.max(maxY, n.y + n.h);
    }
    for (const e of primaryEdges) {
      minX = Math.min(minX, e.bbox.minX);
      minY = Math.min(minY, e.bbox.minY);
      maxX = Math.max(maxX, e.bbox.maxX);
      maxY = Math.max(maxY, e.bbox.maxY);
    }
    for (const e of sidebandEdges) {
      minX = Math.min(minX, e.bbox.minX);
      minY = Math.min(minY, e.bbox.minY);
      maxX = Math.max(maxX, e.bbox.maxX);
      maxY = Math.max(maxY, e.bbox.maxY);
    }
    // Leave a small outer margin so strokes / arrowheads never kiss the edge.
    const MARGIN = 12;
    return {
      x: minX - MARGIN,
      y: minY - MARGIN,
      w: maxX - minX + MARGIN * 2,
      h: maxY - minY + MARGIN * 2,
    };
  }, [layout, primaryEdges, sidebandEdges]);

  // Identify edges that touch the active node. Only these animate.
  const activeEdgeKey = useMemo(() => {
    const key = new Set<string>();
    for (let i = 0; i < primaryEdges.length; i++) {
      const e = primaryEdges[i];
      if (e.from === activeIndex || e.to === activeIndex) key.add(`p-${i}`);
    }
    for (let i = 0; i < sidebandEdges.length; i++) {
      const e = sidebandEdges[i];
      if (e.from === activeIndex || e.to === activeIndex) key.add(`s-${i}`);
    }
    return key;
  }, [primaryEdges, sidebandEdges, activeIndex]);

  // When the content is wider than the container, scroll horizontally rather
  // than clip. Cover both the natural grid width and the widest edge bbox.
  const needsScroll = viewBox.w > containerWidth;
  const svgPixelWidth = needsScroll ? viewBox.w : containerWidth;
  const svgPixelHeight = (viewBox.h * svgPixelWidth) / Math.max(1, viewBox.w);

  return (
    <div
      ref={hostRef}
      style={{
        width: '100%',
        background: 'var(--surface-2)',
        border: '1px solid var(--line-3)',
        borderRadius: 4,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--line-2)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
        }}
      >
        <span
          aria-hidden
          style={{
            width: 8,
            height: 8,
            borderRadius: 2,
            background: 'var(--fg-primary)',
          }}
        />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--fg-muted)',
          }}
        >
          Pipeline canvas · DAG view
        </span>
        <span style={{ flex: 1 }} />
        <Legend />
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: 'var(--fg-muted)',
            fontFeatureSettings: '"tnum" 1',
          }}
        >
          Column {activeCol + 1} · Step {activeIndex + 1} of {steps.length}
        </span>
      </div>

      {/* Scrollable canvas: scrolls horizontally only if content is wider
          than the container. Otherwise behaves as a fixed-width block. */}
      <div
        className="lt-scroll"
        style={{
          width: '100%',
          overflowX: needsScroll ? 'auto' : 'hidden',
          overflowY: 'hidden',
        }}
      >
        <svg
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
          width={svgPixelWidth}
          height={svgPixelHeight}
          preserveAspectRatio="xMidYMid meet"
          style={{ display: 'block' }}
          role="img"
          aria-label="Architecture DAG"
        >
          <defs>
            <filter id={`${uid}-glow`} x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="3" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient id={`${uid}-top`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--fg-secondary)" stopOpacity="0.9" />
              <stop offset="100%" stopColor="var(--fg-primary)" stopOpacity="1" />
            </linearGradient>
            <linearGradient id={`${uid}-right`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="var(--fg-primary)" stopOpacity="0.9" />
              <stop offset="100%" stopColor="var(--fg-primary)" stopOpacity="0.7" />
            </linearGradient>
            <marker
              id={`${uid}-arrow`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--fg-muted)" />
            </marker>
            <marker
              id={`${uid}-arrow-active`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--fg-primary)" />
            </marker>
            <marker
              id={`${uid}-arrow-feedback`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--warn)" />
            </marker>
            <marker
              id={`${uid}-arrow-memory`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--accent-2)" />
            </marker>
          </defs>

          {/* Sideband edges (under primary edges) */}
          {sidebandEdges.map((edge, i) => {
            const color = sidebandColor(edge.kind);
            const marker =
              edge.kind === 'feedback'
                ? `${uid}-arrow-feedback`
                : edge.kind === 'memory' || edge.kind === 'cache'
                  ? `${uid}-arrow-memory`
                  : `${uid}-arrow`;
            return (
              <g key={`sb-${i}`} opacity={0.85}>
                <path
                  d={edge.path}
                  fill="none"
                  stroke={color}
                  strokeWidth={1}
                  strokeDasharray="2 4"
                  markerEnd={`url(#${marker})`}
                />
                {edge.label && (
                  <EdgeLabel
                    path={edge.path}
                    text={edge.label}
                    color={color}
                    uid={`${uid}-sb-${i}`}
                  />
                )}
              </g>
            );
          })}

          {/* Primary edges */}
          {primaryEdges.map((edge, i) => {
            const isActive =
              edge.to === activeIndex || edge.from === activeIndex;
            return (
              <g key={`pe-${i}`}>
                <path
                  d={edge.path}
                  fill="none"
                  stroke={isActive ? 'var(--fg-primary)' : 'var(--line-3)'}
                  strokeWidth={isActive ? 1.6 : 1}
                  markerEnd={
                    isActive
                      ? `url(#${uid}-arrow-active)`
                      : `url(#${uid}-arrow)`
                  }
                />
              </g>
            );
          })}

          {/* Node boxes */}
          {layout.nodes.map((n, i) => {
            const step = steps[i];
            if (!step) return null;
            const activeUpstreams = steps[activeIndex]?.upstreams ?? [];
            return (
              <NodeBox
                key={`node-${i}`}
                n={n}
                step={step}
                index={i}
                uid={uid}
                isActive={i === activeIndex}
                isUpstreamOfActive={activeUpstreams.includes(i)}
                onClick={() => onNodeClick?.(i)}
              />
            );
          })}

          {/* Travelling cubes — only on edges that touch the active node */}
          {primaryEdges.map((edge, i) => {
            if (!activeEdgeKey.has(`p-${i}`)) return null;
            return (
              <TravelCube
                key={`cube-p-${i}`}
                path={edge.path}
                label={steps[edge.from].outgoing?.name ?? ''}
                tone="primary"
                uid={uid}
              />
            );
          })}
          {sidebandEdges.map((edge, i) => {
            if (!activeEdgeKey.has(`s-${i}`)) return null;
            return (
              <TravelCube
                key={`cube-sb-${i}`}
                path={edge.path}
                label={edge.label ?? ''}
                tone={edge.kind}
                uid={uid}
              />
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function sidebandColor(kind: SidebandKind): string {
  switch (kind) {
    case 'feedback':
      return 'var(--warn)';
    case 'memory':
    case 'cache':
      return 'var(--accent-2)';
    case 'telemetry':
      return 'var(--fg-muted)';
    case 'stream':
    default:
      return 'var(--fg-muted)';
  }
}

// ─── Legend ────────────────────────────────────────────────────────────────

function Legend() {
  const items: { label: string; color: string; dashed?: boolean }[] = [
    { label: 'Primary', color: 'var(--fg-primary)' },
    { label: 'Stream', color: 'var(--fg-muted)', dashed: true },
    { label: 'Memory / cache', color: 'var(--accent-2)', dashed: true },
    { label: 'Feedback', color: 'var(--warn)', dashed: true },
  ];
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      {items.map((it) => (
        <span
          key={it.label}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            fontSize: 10,
            fontWeight: 600,
            color: 'var(--fg-muted)',
          }}
        >
          <svg width={18} height={6} aria-hidden>
            <line
              x1={0}
              y1={3}
              x2={18}
              y2={3}
              stroke={it.color}
              strokeWidth={1.4}
              strokeDasharray={it.dashed ? '2 3' : undefined}
            />
          </svg>
          {it.label}
        </span>
      ))}
    </div>
  );
}

// ─── Node box ──────────────────────────────────────────────────────────────

function NodeBox({
  n,
  step,
  index,
  uid,
  isActive,
  isUpstreamOfActive,
  onClick,
}: {
  n: NodePos;
  step: WorkflowStep;
  index: number;
  uid: string;
  isActive: boolean;
  isUpstreamOfActive: boolean;
  onClick: () => void;
}) {
  const topStripH = 16;
  const topFill = step.deterministic
    ? 'var(--warn)'
    : isActive
      ? 'var(--fg-primary)'
      : 'var(--fg-secondary)';
  const strokeColor = isActive
    ? 'var(--fg-primary)'
    : isUpstreamOfActive
      ? 'var(--accent-2)'
      : 'var(--line-3)';
  const strokeWidth = isActive ? 2 : 1;

  return (
    <g
      onClick={onClick}
      style={{ cursor: 'pointer' }}
      role="button"
      aria-label={`Step ${index + 1}: ${step.role}`}
      filter={isActive ? `url(#${uid}-glow)` : undefined}
    >
      {/* Drop shadow for the isometric lift */}
      <rect
        x={n.x + 3}
        y={n.y + 5}
        width={n.w}
        height={n.h}
        rx={2}
        fill="var(--fg-primary)"
        opacity="0.06"
      />

      <rect
        x={n.x}
        y={n.y}
        width={n.w}
        height={n.h}
        rx={2}
        fill="var(--surface-2)"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
      />

      <rect
        x={n.x}
        y={n.y}
        width={n.w}
        height={topStripH}
        rx={2}
        fill={topFill}
      />

      <text
        x={n.x + 10}
        y={n.y + 11.5}
        fontSize={9}
        fontWeight={800}
        letterSpacing="0.1em"
        fill="var(--surface-2)"
        style={{ textTransform: 'uppercase' }}
      >
        STEP {index + 1}
        {step.parallelGroup ? ` · ${step.parallelGroup}` : ''}
      </text>
      {step.deterministic && (
        <g transform={`translate(${n.x + n.w - 20}, ${n.y + 2})`}>
          <Shield size={11} color="var(--surface-2)" />
        </g>
      )}

      <foreignObject
        x={n.x + 10}
        y={n.y + topStripH + 6}
        width={n.w - 20}
        height={n.h - topStripH - 8}
      >
        <div
          // eslint-disable-next-line react/no-unknown-property
          xmlns="http://www.w3.org/1999/xhtml"
          style={{
            fontSize: 12.5,
            lineHeight: 1.25,
            fontWeight: isActive ? 700 : 600,
            color: 'var(--fg-primary)',
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            letterSpacing: '-0.005em',
          }}
        >
          {step.role}
        </div>
        <div
          // eslint-disable-next-line react/no-unknown-property
          xmlns="http://www.w3.org/1999/xhtml"
          style={{
            marginTop: 4,
            fontSize: 10,
            fontWeight: 600,
            color: 'var(--fg-muted)',
            letterSpacing: '0.04em',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            overflow: 'hidden',
            whiteSpace: 'nowrap',
            textOverflow: 'ellipsis',
          }}
        >
          {step.outgoing?.shape ? '→ ' + step.outgoing.shape : '—'}
        </div>
      </foreignObject>
    </g>
  );
}

// ─── Edge label (rides the path via textPath) ─────────────────────────────

function EdgeLabel({
  path,
  text,
  color,
  uid,
}: {
  path: string;
  text: string;
  color: string;
  uid: string;
}) {
  const pathId = `${uid}-labelpath`;
  return (
    <g>
      <path id={pathId} d={path} fill="none" stroke="none" />
      <text fontSize={9} fontWeight={600} fill={color} letterSpacing="0.04em">
        <textPath href={`#${pathId}`} startOffset="50%" textAnchor="middle">
          {text}
        </textPath>
      </text>
    </g>
  );
}

// ─── Travelling cube ──────────────────────────────────────────────────────
// Only rendered when the parent flagged its edge as active-touching, so a
// mounted cube is always moving.

function TravelCube({
  path,
  label,
  tone,
  uid,
}: {
  path: string;
  label: string;
  tone: 'primary' | SidebandKind;
  uid: string;
}) {
  const gRef = useRef<SVGGElement>(null);
  const pathRef = useRef<SVGPathElement>(null);

  useEffect(() => {
    const el = gRef.current;
    const p = pathRef.current;
    if (!el || !p) return;

    let raf = 0;
    let start: number | null = null;
    // A freshly-activated edge travels at a calm pace so the user can read
    // it. Feedback edges run the path in reverse to correctly depict the
    // retry direction.
    const duration = 2000;
    const reverse = tone === 'feedback';

    const tick = (ts: number) => {
      if (start === null) start = ts;
      const elapsed = ts - start;
      const raw = (elapsed % duration) / duration;
      const progress = reverse ? 1 - raw : raw;
      try {
        const total = p.getTotalLength();
        const pt = p.getPointAtLength(total * progress);
        el.setAttribute('transform', `translate(${pt.x}, ${pt.y})`);
      } catch {
        /* path not yet measurable */
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [path, tone]);

  const ringColor =
    tone === 'feedback'
      ? 'var(--warn)'
      : tone === 'memory' || tone === 'cache'
        ? 'var(--accent-2)'
        : tone === 'telemetry'
          ? 'var(--fg-muted)'
          : tone === 'stream'
            ? 'var(--fg-muted)'
            : 'var(--fg-primary)';

  return (
    <g>
      <path ref={pathRef} d={path} fill="none" stroke="none" />
      <g ref={gRef} style={{ willChange: 'transform' }}>
        <g transform="translate(-8, -8)">
          <ellipse cx="8" cy="17" rx="8" ry="2" fill="rgba(0,0,0,0.18)" />
          <path
            d="M 8 0 L 16 4 L 8 8 L 0 4 Z"
            fill={`url(#${uid}-top)`}
            stroke="var(--fg-primary)"
            strokeWidth="0.6"
          />
          <path
            d="M 0 4 L 8 8 L 8 16 L 0 12 Z"
            fill="var(--fg-secondary)"
            stroke="var(--fg-primary)"
            strokeWidth="0.6"
          />
          <path
            d="M 16 4 L 8 8 L 8 16 L 16 12 Z"
            fill={`url(#${uid}-right)`}
            stroke="var(--fg-primary)"
            strokeWidth="0.6"
          />
          {tone !== 'primary' && (
            <circle
              cx="8"
              cy="4"
              r="1.6"
              fill="none"
              stroke={ringColor}
              strokeWidth="0.9"
            />
          )}
        </g>

        {label && (
          <g>
            <rect
              x={-48}
              y={-28}
              width={96}
              height={15}
              rx={2}
              fill="var(--surface-2)"
              stroke="var(--fg-primary)"
              strokeWidth="0.6"
            />
            <text
              x={0}
              y={-17.5}
              textAnchor="middle"
              fontSize={9}
              fontWeight={700}
              fill="var(--fg-primary)"
              letterSpacing="0.04em"
            >
              {label.length > 18 ? label.slice(0, 17) + '…' : label}
            </text>
          </g>
        )}
      </g>
    </g>
  );
}
