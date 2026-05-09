/**
 * Hook that returns theme-aware color tokens — all derived from our
 * design-tokens.css custom properties so every page inherits the
 * "LOHI-TRADE 2026" ultra-modern glass aesthetic for free.
 *
 * Every field maps to a `var(--…)` token. Changing a token in
 * design-tokens.css propagates to every page automatically.
 */
import { useThemeStore } from '../stores/theme-store';

export interface ThemeColors {
  isLight: boolean;
  // Backgrounds
  bgPrimary: string;       // page background
  bgSecondary: string;     // sidebar / header background
  bgCard: string;          // card surface
  bgCardGradient: string;  // card CSS gradient (used by legacy pages)
  bgHover: string;         // hover state
  bgOverlay: string;       // modal overlay
  bgMuted: string;         // subtle bg for badges/pills
  // Text
  textPrimary: string;     // headings, values
  textSecondary: string;   // body text, labels
  textMuted: string;       // captions, timestamps
  // Borders
  borderPrimary: string;   // card borders
  borderSecondary: string; // dividers inside cards
  borderSubtle: string;    // very faint separators
  // Inputs
  inputBg: string;
  inputBorder: string;
  // Shadows
  cardShadow: string;
  // Accent helpers
  accentBg: string;        // accent background
  accentText: string;      // accent text
  // Semantic (bull / bear / warn)
  bull: string;
  bullSoft: string;
  bear: string;
  bearSoft: string;
  warn: string;
  warnSoft: string;
}

/**
 * The shape is identical across themes — values come from CSS vars that
 * flip via `:root[data-theme='light' | 'dark']` in design-tokens.css.
 * We still expose `isLight` and a few concrete hex values for legacy
 * chart libraries (lightweight-charts, recharts) that can't accept vars.
 */
function tokens(isLight: boolean): ThemeColors {
  return {
    isLight,
    // Backgrounds — use tokens so the whole app shares surfaces
    bgPrimary: 'var(--surface-1)',
    bgSecondary: 'var(--surface-0)',
    bgCard: 'var(--surface-2)',
    bgCardGradient:
      'radial-gradient(120% 120% at 100% 0%, color-mix(in srgb, var(--accent) 7%, transparent) 0%, transparent 55%), var(--surface-2)',
    bgHover: 'color-mix(in srgb, var(--surface-3) 60%, transparent)',
    bgOverlay: 'var(--scrim)',
    bgMuted: 'var(--surface-4)',
    // Text
    textPrimary: 'var(--fg-primary)',
    textSecondary: 'var(--fg-secondary)',
    textMuted: 'var(--fg-muted)',
    // Borders
    borderPrimary: 'var(--line-2)',
    borderSecondary: 'var(--line-3)',
    borderSubtle: 'var(--line-1)',
    // Inputs
    inputBg: 'var(--surface-2)',
    inputBorder: 'var(--line-2)',
    // Shadows — reuse elevation tokens
    cardShadow: 'var(--elev-1)',
    // Accent
    accentBg: 'color-mix(in srgb, var(--accent) 12%, transparent)',
    accentText: 'var(--accent-2)',
    // Semantic
    bull: 'var(--bull)',
    bullSoft: 'var(--bull-soft)',
    bear: 'var(--bear)',
    bearSoft: 'var(--bear-soft)',
    warn: 'var(--warn)',
    warnSoft: 'var(--warn-soft)',
  };
}

const dark = tokens(false);
const light = tokens(true);

export function useThemeColors(): ThemeColors {
  const theme = useThemeStore((s) => s.theme);
  return theme === 'light' ? light : dark;
}

/**
 * Concrete hex values for chart libraries that cannot consume CSS vars
 * at runtime (lightweight-charts, recharts configs). These mirror the
 * primary design tokens but must stay in sync with design-tokens.css.
 */
export function chartPalette(isLight: boolean) {
  return isLight
    ? {
        background: '#ffffff',
        text: '#6b7280',
        grid: 'rgba(15, 23, 42, 0.08)',
        border: 'rgba(15, 23, 42, 0.14)',
        bull: '#00a76a',
        bear: '#e11d48',
      }
    : {
        background: '#0f1012',
        text: '#7b828d',
        grid: 'rgba(255, 255, 255, 0.08)',
        border: 'rgba(255, 255, 255, 0.14)',
        bull: '#00e38c',
        bear: '#ff4d6d',
      };
}
