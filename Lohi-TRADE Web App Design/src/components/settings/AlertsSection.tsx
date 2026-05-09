/**
 * P&L Alerts configuration section for SettingsPage.
 */

import { useState } from 'react';
import { Bell, Plus, Trash2, Edit2, Check, X } from 'lucide-react';
import { useAlertStore } from '../../stores/alert-store';
import { useThemeColors } from '../../hooks/use-theme-colors';
import type { AlertRule } from '../../lib/types';

const ALERT_TYPES: { value: AlertRule['type']; label: string }[] = [
  { value: 'absolute_profit', label: 'Absolute Profit (₹)' },
  { value: 'absolute_loss', label: 'Absolute Loss (₹)' },
  { value: 'percent_profit', label: 'Percent Profit (%)' },
  { value: 'percent_loss', label: 'Percent Loss (%)' },
];

export default function AlertsSection() {
  const rules = useAlertStore((s) => s.rules);
  const addRule = useAlertStore((s) => s.addRule);
  const editRule = useAlertStore((s) => s.editRule);
  const deleteRule = useAlertStore((s) => s.deleteRule);
  const t = useThemeColors();

  const [newType, setNewType] = useState<AlertRule['type']>('absolute_profit');
  const [newThreshold, setNewThreshold] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editThreshold, setEditThreshold] = useState(0);

  const handleAdd = () => {
    if (newThreshold <= 0) return;
    addRule({ type: newType, threshold: newThreshold, enabled: true });
    setNewThreshold(0);
  };

  const handleSaveEdit = (id: string) => { editRule(id, { threshold: editThreshold }); setEditingId(null); };

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textPrimary,
  };

  return (
    <div className="rounded-xl p-5" style={{ background: t.bgCard, border: `1px solid ${t.borderPrimary}` }}>
      <div className="flex items-center space-x-2 mb-4">
        <Bell size={16} className="text-amber-400" />
        <h3 className="text-sm font-semibold" style={{ color: t.textPrimary }}>P&L Alerts</h3>
      </div>

      {rules.length > 0 && (
        <div className="space-y-2 mb-4">
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center justify-between px-3 py-2 rounded-lg"
              style={{ background: t.bgMuted, border: `1px solid ${t.borderPrimary}` }}>
              {editingId === rule.id ? (
                <div className="flex items-center space-x-2 flex-1">
                  <span className="text-xs" style={{ color: t.textMuted }}>{ALERT_TYPES.find((at) => at.value === rule.type)?.label}</span>
                  <input type="number" value={editThreshold}
                    onChange={(e) => setEditThreshold(Number(e.target.value))}
                    className="w-24 rounded px-2 py-1 text-xs" style={inputStyle} min={0} />
                  <button onClick={() => handleSaveEdit(rule.id)} style={{ color: '#34d399', background: 'none', border: 'none', cursor: 'pointer' }}><Check size={14} /></button>
                  <button onClick={() => setEditingId(null)} style={{ color: t.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}><X size={14} /></button>
                </div>
              ) : (
                <>
                  <div className="flex items-center space-x-3">
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input type="checkbox" checked={rule.enabled}
                        onChange={(e) => editRule(rule.id, { enabled: e.target.checked })}
                        className="sr-only peer" />
                      <div className="w-8 h-4 rounded-full peer-checked:bg-emerald-600 transition-colors"
                        style={{ background: rule.enabled ? undefined : (t.isLight ? '#cbd5e1' : '#334155') }} />
                      <div className="absolute left-0.5 top-0.5 w-3 h-3 bg-white rounded-full transition-transform peer-checked:translate-x-4" />
                    </label>
                    <span className="text-xs" style={{ color: t.textSecondary }}>
                      {ALERT_TYPES.find((at) => at.value === rule.type)?.label}: {rule.threshold}
                    </span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <button onClick={() => { setEditingId(rule.id); setEditThreshold(rule.threshold); }}
                      className="p-1" style={{ color: t.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}><Edit2 size={12} /></button>
                    <button onClick={() => deleteRule(rule.id)}
                      className="p-1" style={{ color: t.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}><Trash2 size={12} /></button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center space-x-2">
        <select value={newType} onChange={(e) => setNewType(e.target.value as AlertRule['type'])}
          className="rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:border-blue-500" style={inputStyle}>
          {ALERT_TYPES.map((at) => <option key={at.value} value={at.value}>{at.label}</option>)}
        </select>
        <input type="number" value={newThreshold}
          onChange={(e) => setNewThreshold(Number(e.target.value))}
          placeholder="Threshold"
          className="w-24 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:border-blue-500"
          style={inputStyle} min={0} />
        <button onClick={handleAdd}
          className="flex items-center space-x-1 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded text-xs font-medium transition-colors">
          <Plus size={12} /><span>Add</span>
        </button>
      </div>
    </div>
  );
}