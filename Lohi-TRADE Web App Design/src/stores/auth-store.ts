/**
 * Auth Zustand store.
 * Manages JWT token, user info, and login/logout state.
 */

import { create } from 'zustand';
import { markFreshLogin } from '../lib/api-client';

export interface AuthUser {
  username: string;
  role: string;
}

export interface AuthState {
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;
}

export interface AuthActions {
  setAuth: (token: string, user: AuthUser) => void;
  clearAuth: () => void;
}

export type AuthStore = AuthState & AuthActions;

const STORAGE_KEY = 'lohi_auth_token';
const USER_KEY = 'lohi_auth_user';

// Restore from localStorage on load
function getInitialState(): Pick<AuthState, 'token' | 'user' | 'isAuthenticated'> {
  try {
    const token = localStorage.getItem(STORAGE_KEY);
    const userStr = localStorage.getItem(USER_KEY);
    if (token && userStr) {
      const user = JSON.parse(userStr) as AuthUser;
      return { token, user, isAuthenticated: true };
    }
  } catch {
    // ignore
  }
  return { token: null, user: null, isAuthenticated: false };
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  ...getInitialState(),

  setAuth: (token: string, user: AuthUser) => {
    localStorage.setItem(STORAGE_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    set({ token, user, isAuthenticated: true });
    // Open a short grace window so the first data-load 401s (if any) don't
    // trip the session-expired modal while the backend propagates the token.
    markFreshLogin();
    startInactivityTimer(get, set);
  },

  clearAuth: () => {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(USER_KEY);
    stopInactivityTimer();
    set({ token: null, user: null, isAuthenticated: false });
  },
}));

// ─── Auto-logout after 24h inactivity ───────────────────────────────────────

const INACTIVITY_TIMEOUT = 24 * 60 * 60 * 1000; // 24 hours
let inactivityTimer: ReturnType<typeof setTimeout> | null = null;

function resetInactivityTimer(get: () => AuthStore, set: (s: Partial<AuthState>) => void) {
  if (inactivityTimer) clearTimeout(inactivityTimer);
  if (!get().isAuthenticated) return;
  inactivityTimer = setTimeout(() => {
    get().clearAuth();
  }, INACTIVITY_TIMEOUT);
}

function startInactivityTimer(get: () => AuthStore, set: (s: Partial<AuthState>) => void) {
  const reset = () => resetInactivityTimer(get, set);
  const events = ['mousedown', 'keydown', 'scroll', 'touchstart'] as const;
  events.forEach((e) => window.addEventListener(e, reset, { passive: true }));
  reset();
}

function stopInactivityTimer() {
  if (inactivityTimer) { clearTimeout(inactivityTimer); inactivityTimer = null; }
}

// Start timer on load if already authenticated
if (useAuthStore.getState().isAuthenticated) {
  startInactivityTimer(useAuthStore.getState, useAuthStore.setState);
}
