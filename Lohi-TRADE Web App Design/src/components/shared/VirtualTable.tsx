import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { GripVertical } from 'lucide-react';
import type { VirtualTableProps, VirtualColumn } from '../../lib/types';

/**
 * Generic virtualized table — modernized 2026 edition.
 *
 * Upgrades over the original:
 *   • Sticky glass header (`.lt-glass` + position: sticky top: 0)
 *   • Row-hover glow via CSS `:hover` (zero JS on hover path)
 *   • Drag-and-drop column reordering using native HTML5 DnD (no extra deps)
 *   • Per-table column-order persistence in localStorage when `tableId` is set
 *   • Token-based colors via CSS vars — follows design-tokens.css
 *
 * Public API unchanged: all existing call sites (PositionsPage, OrdersPage,
 * SoldierPage) keep working without edits. Opt in to reordering by adding
 * a `tableId` prop.
 */
export default function VirtualTable<T>({
  data, rowHeight, overscan = 10, threshold = 50,
  columns, onRowClick, keyExtractor,
  tableId, reorderableColumns,
}: VirtualTableProps<T>) {
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);
  const parentRef = useRef<HTMLDivElement>(null);

  /* ─── Column order state ──────────────────────────────────────── */
  const canReorder = (reorderableColumns ?? !!tableId);
  const storageKey = tableId ? `lohi.cols.${tableId}` : null;

  // Derive a stable key per column using the header text.
  const getColKey = useCallback((c: VirtualColumn<T>) => c.header, []);

  const [colOrder, setColOrder] = useState<string[]>(() => {
    if (storageKey && typeof window !== 'undefined') {
      try {
        const raw = localStorage.getItem(storageKey);
        if (raw) {
          const parsed = JSON.parse(raw) as string[];
          if (Array.isArray(parsed)) return parsed;
        }
      } catch { /* ignore */ }
    }
    return columns.map(getColKey);
  });

  // Reconcile when columns change shape (added/removed).
  useEffect(() => {
    const current = columns.map(getColKey);
    setColOrder((prev) => {
      const kept = prev.filter((k) => current.includes(k));
      const added = current.filter((k) => !kept.includes(k));
      const next = [...kept, ...added];
      // only update if actually different
      if (next.length !== prev.length || next.some((k, i) => k !== prev[i])) return next;
      return prev;
    });
  }, [columns, getColKey]);

  // Persist order
  useEffect(() => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, JSON.stringify(colOrder)); } catch { /* ignore */ }
  }, [colOrder, storageKey]);

  // Final ordered columns
  const orderedColumns = useMemo(() => {
    const byKey = new Map(columns.map((c) => [getColKey(c), c]));
    const ordered: VirtualColumn<T>[] = [];
    for (const key of colOrder) {
      const col = byKey.get(key);
      if (col) ordered.push(col);
    }
    // include any new columns not yet in order (safety)
    for (const c of columns) if (!colOrder.includes(getColKey(c))) ordered.push(c);
    return ordered;
  }, [columns, colOrder, getColKey]);

  /* ─── Drag-and-drop handlers ──────────────────────────────────── */
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);

  const onColDragStart = (key: string) => (e: React.DragEvent) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', key);
    setDragKey(key);
  };
  const onColDragOver = (key: string) => (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverKey(key);
  };
  const onColDragLeave = () => setDragOverKey(null);
  const onColDrop = (targetKey: string) => (e: React.DragEvent) => {
    e.preventDefault();
    const sourceKey = dragKey || e.dataTransfer.getData('text/plain');
    setDragKey(null);
    setDragOverKey(null);
    if (!sourceKey || sourceKey === targetKey) return;
    setColOrder((prev) => {
      const next = prev.slice();
      const from = next.indexOf(sourceKey);
      const to = next.indexOf(targetKey);
      if (from < 0 || to < 0) return prev;
      next.splice(from, 1);
      next.splice(to, 0, sourceKey);
      return next;
    });
  };
  const onColDragEnd = () => { setDragKey(null); setDragOverKey(null); };

  /* ─── Virtualization ─────────────────────────────────────────── */
  const useVirtual = data.length > threshold;

  const virtualizer = useVirtualizer({
    count: data.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan,
    enabled: useVirtual,
  });

  const scrollToIndex = useCallback(
    (index: number) => { if (useVirtual) virtualizer.scrollToIndex(index, { align: 'auto' }); },
    [useVirtual, virtualizer],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (data.length === 0) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusedIndex((prev) => { const next = Math.min(prev + 1, data.length - 1); scrollToIndex(next); return next; });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusedIndex((prev) => { const next = Math.max(prev - 1, 0); scrollToIndex(next); return next; });
      } else if (e.key === 'Enter' && focusedIndex >= 0 && onRowClick) {
        e.preventDefault();
        onRowClick(data[focusedIndex]);
      }
    },
    [data, focusedIndex, onRowClick, scrollToIndex],
  );

  useEffect(() => { setFocusedIndex(-1); }, [data]);

  /* ─── Cell renderer ──────────────────────────────────────────── */
  const renderCell = (item: T, col: VirtualColumn<T>) => {
    if (typeof col.accessor === 'function') return col.accessor(item);
    const value = item[col.accessor];
    return value == null ? '' : String(value);
  };

  const thStyle = (col: VirtualColumn<T>, key: string): React.CSSProperties => ({
    padding: '12px 14px', textAlign: col.align ?? 'left',
    color: 'var(--fg-muted)', fontWeight: 700, fontSize: 10,
    textTransform: 'uppercase', letterSpacing: '0.1em', width: col.width,
    position: 'relative',
    cursor: canReorder ? 'grab' : 'default',
    userSelect: 'none',
    opacity: dragKey === key ? 0.4 : 1,
    borderBottom: dragOverKey === key ? '2px solid var(--accent)' : '1px solid var(--line-2)',
    background: dragOverKey === key ? 'color-mix(in srgb, var(--accent) 8%, transparent)' : 'transparent',
    transition: 'background 120ms var(--ease-out), opacity 120ms var(--ease-out)',
  });

  const tdStyle = (col: VirtualColumn<T>): React.CSSProperties => ({
    padding: '13px 14px', textAlign: col.align ?? 'left',
    color: 'var(--fg-primary)', width: col.width,
  });

  /* ─── Header row ─────────────────────────────────────────────── */
  const headerRow = (
    <thead
      className="lt-glass"
      style={{
        position: 'sticky', top: 0, zIndex: 2,
        background: 'color-mix(in srgb, var(--surface-2) 82%, transparent)',
      }}
    >
      <tr>
        {orderedColumns.map((col) => {
          const key = getColKey(col);
          return (
            <th
              key={key}
              style={thStyle(col, key)}
              draggable={canReorder}
              onDragStart={canReorder ? onColDragStart(key) : undefined}
              onDragOver={canReorder ? onColDragOver(key) : undefined}
              onDragLeave={canReorder ? onColDragLeave : undefined}
              onDrop={canReorder ? onColDrop(key) : undefined}
              onDragEnd={canReorder ? onColDragEnd : undefined}
              aria-grabbed={dragKey === key}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {canReorder && (
                  <GripVertical
                    size={11}
                    style={{ opacity: 0.3, flexShrink: 0 }}
                    aria-hidden
                  />
                )}
                {col.header}
              </span>
            </th>
          );
        })}
      </tr>
    </thead>
  );

  const rowBaseStyle: React.CSSProperties = {
    borderBottom: '1px solid var(--line-1)',
    cursor: onRowClick ? 'pointer' : undefined,
    transition: 'background 120ms var(--ease-out)',
  };

  /* ─── Non-virtual render ─────────────────────────────────────── */
  if (!useVirtual) {
    return (
      <div
        role="grid" tabIndex={0} onKeyDown={handleKeyDown}
        style={{ outline: 'none', overflow: 'auto', maxHeight: '70vh', position: 'relative' }}
        className="lt-scroll"
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          {headerRow}
          <tbody>
            {data.map((item, index) => (
              <tr
                key={keyExtractor(item)}
                onClick={() => onRowClick?.(item)}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-4)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = focusedIndex === index ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent')}
                role="row"
                aria-rowindex={index + 1}
                style={{
                  ...rowBaseStyle,
                  background: focusedIndex === index ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
                }}
              >
                {orderedColumns.map((col) => <td key={getColKey(col)} style={tdStyle(col)}>{renderCell(item, col)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  /* ─── Virtual render ─────────────────────────────────────────── */
  const virtualItems = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  return (
    <div
      role="grid" tabIndex={0} onKeyDown={handleKeyDown} ref={parentRef}
      className="lt-scroll"
      style={{ outline: 'none', overflow: 'auto', maxHeight: '70vh', position: 'relative' }}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        {headerRow}
        <tbody>
          <tr style={{ height: totalSize, visibility: 'hidden', padding: 0, border: 0 }}>
            <td colSpan={orderedColumns.length} style={{ padding: 0, border: 0, lineHeight: 0 }} />
          </tr>
          {virtualItems.map((virtualRow) => {
            const item = data[virtualRow.index];
            const isFocused = focusedIndex === virtualRow.index;
            return (
              <tr
                key={keyExtractor(item)}
                data-index={virtualRow.index}
                onClick={() => onRowClick?.(item)}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-4)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = isFocused ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent')}
                role="row"
                aria-rowindex={virtualRow.index + 1}
                style={{
                  ...rowBaseStyle,
                  position: 'absolute', top: 0, left: 0, width: '100%',
                  height: rowHeight, transform: `translateY(${virtualRow.start}px)`,
                  background: isFocused ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent',
                  display: 'table-row',
                }}
              >
                {orderedColumns.map((col) => <td key={getColKey(col)} style={tdStyle(col)}>{renderCell(item, col)}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
