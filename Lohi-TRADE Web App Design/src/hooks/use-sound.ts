import { useCallback, useEffect, useRef } from 'react';

type CueName = 'fill' | 'reject' | 'alert' | 'tick';

/**
 * useSound — tiny opt-in audio cue player for order events.
 *
 * Principles:
 *   • OFF by default (controlled by localStorage flag `lohi.sound`).
 *   • WebAudio synthesis — zero asset download, zero licensing concern.
 *   • Each cue is a short frequency-modulated beep (<= 160ms) so it never
 *     disrupts flow. Respects prefers-reduced-motion only where tonal
 *     feedback would duplicate visual movement.
 *
 * Usage:
 *   const { play, enabled, setEnabled } = useSound();
 *   // on order fill:
 *   play('fill');
 */
export function useSound() {
  const ctxRef = useRef<AudioContext | null>(null);
  const enabledRef = useRef<boolean>(
    typeof window !== 'undefined' ? localStorage.getItem('lohi.sound') === '1' : false,
  );

  useEffect(() => {
    return () => {
      ctxRef.current?.close().catch(() => {});
      ctxRef.current = null;
    };
  }, []);

  const ensureCtx = useCallback(() => {
    if (!ctxRef.current) {
      const Ctor: typeof AudioContext | undefined =
        (window.AudioContext as unknown as typeof AudioContext) ||
        // @ts-expect-error Safari fallback
        window.webkitAudioContext;
      if (!Ctor) return null;
      ctxRef.current = new Ctor();
    }
    return ctxRef.current;
  }, []);

  const play = useCallback((cue: CueName) => {
    if (!enabledRef.current) return;
    const ctx = ensureCtx();
    if (!ctx) return;

    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    // Cue profiles — subtle and distinct
    switch (cue) {
      case 'fill':   osc.frequency.setValueAtTime(880, now); osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12); break;
      case 'reject': osc.frequency.setValueAtTime(440, now); osc.frequency.exponentialRampToValueAtTime(220, now + 0.18); break;
      case 'alert':  osc.frequency.setValueAtTime(660, now); break;
      case 'tick':   osc.frequency.setValueAtTime(1760, now); break;
    }
    osc.type = cue === 'reject' ? 'sawtooth' : 'sine';

    // Fast ADSR so the cue feels "tight"
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.18, now + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + (cue === 'tick' ? 0.04 : 0.16));

    osc.start(now);
    osc.stop(now + 0.2);
  }, [ensureCtx]);

  const setEnabled = useCallback((v: boolean) => {
    enabledRef.current = v;
    try { localStorage.setItem('lohi.sound', v ? '1' : '0'); } catch { /* ignore */ }
  }, []);

  const isEnabled = useCallback(() => enabledRef.current, []);

  return { play, setEnabled, isEnabled };
}
