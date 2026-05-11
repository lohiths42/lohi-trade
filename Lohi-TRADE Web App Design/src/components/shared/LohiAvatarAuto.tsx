/**
 * LohiAvatarAuto — picks the right Lohi skin for the current surface.
 *
 * Uses the app-mode store to decide between the Trade avatar (emerald
 * neon, trader headset) and the Research avatar (monochrome, reading
 * glasses, serif pen, coral Edge accent). The contract is identical to
 * both underlying avatars so callers can drop this in anywhere a Lohi
 * was rendered before.
 */
import { useAppModeStore } from '../../stores/mode-store';
import LohiAvatar, { type LohiAction, type LohiMood } from '../onboarding/LohiAvatar';
import LohiAvatarResearch from '../research/LohiAvatarResearch';

export interface LohiAvatarAutoProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  speaking?: boolean;
  thinking?: boolean;
  action?: LohiAction;
  actionKey?: number;
  mood?: LohiMood;
  /** Force a specific surface regardless of the current app mode. */
  forceSurface?: 'trade' | 'research';
}

export default function LohiAvatarAuto({ forceSurface, ...rest }: LohiAvatarAutoProps) {
  const surface = useAppModeStore((s) => s.surface);
  const resolved = forceSurface ?? surface;
  return resolved === 'research'
    ? <LohiAvatarResearch {...rest} />
    : <LohiAvatar {...rest} />;
}
