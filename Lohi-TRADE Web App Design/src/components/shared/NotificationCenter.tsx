/**
 * NotificationCenter component.
 * Bell icon with unread count badge in the header.
 * Dropdown panel showing last 100 notifications in reverse chronological order.
 *
 * Requirements: 4.1, 4.2, 4.4, 4.5, 4.6
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell } from 'lucide-react';
import { useNotificationStore } from '../../stores/notification-store';
import { useThemeColors } from '../../hooks/use-theme-colors';
import type { Notification } from '../../lib/types';

const TYPE_LABELS: Record<Notification['type'], { label: string; color: string; bg: string }> = {
  trade: { label: 'Trade', color: '#34d399', bg: 'rgba(52,211,153,0.15)' },
  system: { label: 'System', color: '#60a5fa', bg: 'rgba(96,165,250,0.15)' },
  alert: { label: 'Alert', color: '#f87171', bg: 'rgba(248,113,113,0.15)' },
  user: { label: 'User', color: '#94a3b8', bg: 'rgba(148,163,184,0.15)' },
};

function formatTimestamp(ts: number): string {
  const diff = Date.now() - ts;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const t = useThemeColors();

  const notifications = useNotificationStore((s) => s.notifications);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const markAllRead = useNotificationStore((s) => s.markAllRead);

  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
      setOpen(false);
    }
  }, []);

  useEffect(() => {
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open, handleClickOutside]);

  const handleNotificationClick = (notification: Notification) => {
    if (notification.link) { navigate(notification.link); setOpen(false); }
  };

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((prev) => !prev)}
        style={{
          position: 'relative', padding: 8, borderRadius: 8,
          background: 'none', border: 'none', cursor: 'pointer',
          color: t.textMuted, transition: 'color 0.15s, background 0.15s',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = t.textPrimary; e.currentTarget.style.background = t.bgHover; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = t.textMuted; e.currentTarget.style.background = 'none'; }}
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span style={{
            position: 'absolute', top: 2, right: 2, minWidth: 16, height: 16,
            borderRadius: 8, background: '#ef4444', color: '#fff',
            fontSize: 10, fontWeight: 700, display: 'flex', alignItems: 'center',
            justifyContent: 'center', padding: '0 4px', lineHeight: 1,
          }}>
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 8,
          width: 380, maxHeight: 480,
          background: t.bgCard, border: `1px solid ${t.borderPrimary}`,
          borderRadius: 12, boxShadow: t.cardShadow,
          zIndex: 100, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 16px', borderBottom: `1px solid ${t.borderPrimary}`,
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: t.textPrimary }}>Notifications</span>
            {notifications.length > 0 && (
              <button
                onClick={markAllRead}
                style={{
                  fontSize: 11, color: t.accentText, background: 'none',
                  border: 'none', cursor: 'pointer', fontWeight: 600,
                  padding: '2px 6px', borderRadius: 4,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = t.accentBg; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'none'; }}
              >
                Mark all as read
              </button>
            )}
          </div>

          <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
            {notifications.length === 0 ? (
              <div style={{ padding: '40px 16px', textAlign: 'center', color: t.textMuted, fontSize: 12 }}>
                No notifications
              </div>
            ) : (
              notifications.map((n) => {
                const typeInfo = TYPE_LABELS[n.type] || TYPE_LABELS.user;
                return (
                  <div
                    key={n.id}
                    onClick={() => handleNotificationClick(n)}
                    style={{
                      display: 'flex', alignItems: 'flex-start', gap: 10,
                      padding: '10px 16px', borderBottom: `1px solid ${t.borderPrimary}`,
                      cursor: n.link ? 'pointer' : 'default',
                      background: n.read ? 'transparent' : (t.isLight ? 'rgba(59,130,246,0.04)' : 'rgba(59,130,246,0.05)'),
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={(e) => { if (n.link) e.currentTarget.style.background = t.bgHover; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = n.read ? 'transparent' : (t.isLight ? 'rgba(59,130,246,0.04)' : 'rgba(59,130,246,0.05)'); }}
                  >
                    <div style={{ paddingTop: 4, width: 8, flexShrink: 0 }}>
                      {!n.read && <div style={{ width: 6, height: 6, borderRadius: 3, background: '#3b82f6' }} />}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{
                          fontSize: 10, fontWeight: 600, color: typeInfo.color,
                          background: typeInfo.bg, padding: '1px 6px', borderRadius: 4,
                          textTransform: 'uppercase', letterSpacing: '0.05em',
                        }}>
                          {typeInfo.label}
                        </span>
                        <span style={{ fontSize: 10, color: t.textMuted, marginLeft: 'auto', flexShrink: 0 }}>
                          {formatTimestamp(n.timestamp)}
                        </span>
                      </div>
                      <p style={{
                        fontSize: 12, color: n.read ? t.textSecondary : t.textPrimary,
                        lineHeight: 1.4, margin: 0, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {n.message}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}