/**
 * Notification Zustand store.
 * Manages notification history with localStorage persistence (max 100 entries).
 * Auto-prunes notifications older than 7 days.
 */

import { create } from 'zustand';
import type { Notification } from '../lib/types';

export interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
}

export interface NotificationActions {
  addNotification: (n: Omit<Notification, 'id' | 'read'>) => void;
  markAllRead: () => void;
  pruneOld: () => void;
}

export type NotificationStore = NotificationState & NotificationActions;

const STORAGE_KEY = 'lohi_notifications';
const MAX_NOTIFICATIONS = 100;
const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function loadNotifications(): Notification[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

function persist(notifications: Notification[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications));
  } catch {
    // localStorage full or unavailable — keep in memory only
  }
}

function countUnread(notifications: Notification[]): number {
  return notifications.filter((n) => !n.read).length;
}

const initialNotifications = loadNotifications();

export const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: initialNotifications,
  unreadCount: countUnread(initialNotifications),

  addNotification: (n) => {
    set((state) => {
      const newNotification: Notification = {
        ...n,
        id: generateId(),
        read: false,
      };
      const updated = [newNotification, ...state.notifications].slice(0, MAX_NOTIFICATIONS);
      persist(updated);
      return {
        notifications: updated,
        unreadCount: countUnread(updated),
      };
    });
  },

  markAllRead: () => {
    set((state) => {
      const updated = state.notifications.map((n) => ({ ...n, read: true }));
      persist(updated);
      return { notifications: updated, unreadCount: 0 };
    });
  },

  pruneOld: () => {
    set((state) => {
      const cutoff = Date.now() - SEVEN_DAYS_MS;
      const updated = state.notifications.filter((n) => n.timestamp >= cutoff);
      persist(updated);
      return {
        notifications: updated,
        unreadCount: countUnread(updated),
      };
    });
  },
}));
