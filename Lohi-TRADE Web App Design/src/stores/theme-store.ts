/**
 * Theme Zustand store.
 * Manages dark/light theme state with localStorage persistence.
 */

import { create } from 'zustand';
import type { Theme } from '../lib/types';

export interface ThemeState {
  theme: Theme;
}

export interface ThemeActions {
  toggleTheme: () => void;
}

export type ThemeStore = ThemeState & ThemeActions;

const STORAGE_KEY = 'lohi_theme';

function isValidTheme(value: unknown): value is Theme {
  return value === 'dark' || value === 'light';
}

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isValidTheme(stored)) {
      return stored;
    }
  } catch {
    // localStorage unavailable — fall through to default
  }
  return 'dark';
}

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: getInitialTheme(),

  toggleTheme: () => {
    set((state) => {
      const next: Theme = state.theme === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // localStorage full or unavailable — theme still updates in memory
      }
      return { theme: next };
    });
  },
}));
