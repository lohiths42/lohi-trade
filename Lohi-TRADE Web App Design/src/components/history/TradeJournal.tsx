/**
 * Trade Journal — slide-open panel for adding notes to trades.
 */

import { useState, useEffect } from 'react';
import { X, Save, Trash2, Loader2 } from 'lucide-react';
import { api } from '../../lib/api-client';
import { showToast } from '../shared/Toast';
import { useThemeColors } from '../../hooks/use-theme-colors';
import type { TradeNote } from '../../lib/types';

interface TradeJournalProps { tradeId: string; symbol: string; onClose: () => void; }

export default function TradeJournal({ tradeId, symbol, onClose }: TradeJournalProps) {
  const [notes, setNotes] = useState<TradeNote[]>([]);
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const t = useThemeColors();
  const MAX_CHARS = 2000;

  useEffect(() => {
    setLoading(true);
    fetch(`/api/trades/${tradeId}/notes`)
      .then((r) => r.json())
      .then((data) => setNotes(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tradeId]);

  const handleSave = async () => {
    if (!text.trim()) return;
    setSaving(true);
    try {
      if (editingId) {
        const res = await fetch(`/api/trades/${tradeId}/notes/${editingId}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note_text: text.slice(0, MAX_CHARS) }),
        });
        if (!res.ok) throw new Error('Failed to update');
        const updated = await res.json();
        setNotes((prev) => prev.map((n) => (n.id === editingId ? updated : n)));
        setEditingId(null);
      } else {
        const res = await fetch(`/api/trades/${tradeId}/notes`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note_text: text.slice(0, MAX_CHARS) }),
        });
        if (!res.ok) throw new Error('Failed to save');
        const created = await res.json();
        setNotes((prev) => [created, ...prev]);
      }
      setText('');
      showToast('success', 'Note saved');
    } catch {
      showToast('error', 'Failed to save note');
    } finally { setSaving(false); }
  };

  const handleDelete = async (noteId: number) => {
    try {
      await fetch(`/api/trades/${tradeId}/notes/${noteId}`, { method: 'DELETE' });
      setNotes((prev) => prev.filter((n) => n.id !== noteId));
      showToast('success', 'Note deleted');
    } catch { showToast('error', 'Failed to delete note'); }
  };

  const handleEdit = (note: TradeNote) => { setEditingId(note.id); setText(note.noteText); };

  return (
    <div className="fixed right-0 top-0 h-full w-96 shadow-2xl z-[100] flex flex-col"
      style={{ background: t.bgCard, borderLeft: `1px solid ${t.borderPrimary}` }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: `1px solid ${t.borderPrimary}` }}>
        <div>
          <h3 className="text-sm font-semibold" style={{ color: t.textPrimary }}>Trade Journal</h3>
          <p className="text-xs" style={{ color: t.textMuted }}>{symbol} · {tradeId}</p>
        </div>
        <button onClick={onClose} className="p-1" style={{ color: t.textMuted, cursor: 'pointer', background: 'none', border: 'none' }}>
          <X size={18} />
        </button>
      </div>

      {/* Note input */}
      <div className="p-4" style={{ borderBottom: `1px solid ${t.borderPrimary}` }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
          placeholder="Add a note about this trade…"
          maxLength={MAX_CHARS}
          className="w-full h-24 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none"
          style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textPrimary }}
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-[10px]" style={{ color: t.textMuted }}>{text.length}/{MAX_CHARS}</span>
          <button
            onClick={handleSave}
            disabled={saving || !text.trim()}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded text-xs font-medium transition-colors"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            <span>{editingId ? 'Update' : 'Save'}</span>
          </button>
        </div>
      </div>

      {/* Notes list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading ? (
          <div className="text-center text-xs py-8" style={{ color: t.textMuted }}>Loading notes…</div>
        ) : notes.length === 0 ? (
          <div className="text-center text-xs py-8" style={{ color: t.textMuted }}>No notes yet</div>
        ) : (
          notes.map((note) => (
            <div key={note.id} className="rounded-lg p-3" style={{ background: t.bgMuted, border: `1px solid ${t.borderPrimary}` }}>
              <p className="text-xs whitespace-pre-wrap" style={{ color: t.textSecondary }}>{note.noteText}</p>
              <div className="flex items-center justify-between mt-2">
                <span className="text-[10px]" style={{ color: t.textMuted }}>
                  {new Date(note.updatedAt).toLocaleString()}
                </span>
                <div className="flex items-center space-x-1">
                  <button onClick={() => handleEdit(note)} className="text-[10px]" style={{ color: t.accentText, background: 'none', border: 'none', cursor: 'pointer' }}>Edit</button>
                  <button onClick={() => handleDelete(note.id)} style={{ color: t.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}>
                    <Trash2 size={10} />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
