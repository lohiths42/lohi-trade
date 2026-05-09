/**
 * App-mode store.
 *
 * Toggles the whole application shell between the Trade surface and the
 * Research surface. The active mode is persisted to `localStorage` so the
 * user lands back in the surface they last used. The mode is also reflected
 * on `<html data-surface="trade|research">` which flips the theme token
 * block defined in `research-theme.css`.
 *
 * Surfaces inherit all tokens from `design-tokens.css`; the `research`
 * attribute simply overrides the palette, typography, and editorial
 * primitives for the Research product identity.
 */
import { create } from 'zustand';

export type AppSurface = 'trade' | 'research';

const STORAGE_KEY = 'lohi_app_surface';

/** Read the last-used surface from localStorage, defaulting to 'trade'. */
function readInitial(): AppSurface {
  if (typeof window === 'undefined') return 'trade';
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (value === 'research' || value === 'trade') return value;
  } catch {
    /* ignored — SSR or storage-disabled environments */
  }
  return 'trade';
}

/** Apply the surface to the <html> element so CSS tokens flip. */
function applyToDocument(surface: AppSurface): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.surface = surface;
}

export interface AppModeState {
  surface: AppSurface;
  setSurface: (surface: AppSurface) => void;
  toggle: () => void;
}

export const useAppModeStore = create<AppModeState>((set, get) => {
  const initial = readInitial();
  applyToDocument(initial);

  return {
    surface: initial,
    setSurface: (surface) => {
      if (surface === get().surface) return;
      try {
        window.localStorage.setItem(STORAGE_KEY, surface);
      } catch {
        /* ignored */
      }
      applyToDocument(surface);
      set({ surface });
    },
    toggle: () => {
      const next: AppSurface = get().surface === 'trade' ? 'research' : 'trade';
      get().setSurface(next);
    },
  };
});

/** Selector for components that only care about the current surface. */
export const selectSurface = (s: AppModeState): AppSurface => s.surface;
