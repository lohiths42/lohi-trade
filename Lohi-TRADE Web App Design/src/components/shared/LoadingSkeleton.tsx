/**
 * Reusable loading skeleton component.
 * Validates: Requirements 3.5
 */

import { useThemeColors } from '../../hooks/use-theme-colors';

interface LoadingSkeletonProps {
  lines?: number;
  className?: string;
}

export default function LoadingSkeleton({ lines = 5, className = '' }: LoadingSkeletonProps) {
  const t = useThemeColors();
  return (
    <div className={`animate-pulse space-y-3 ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="h-8 rounded"
          style={{ width: `${85 + Math.round((i * 17) % 15)}%`, background: t.isLight ? '#e2e8f0' : '#1e293b' }}
        />
      ))}
    </div>
  );
}
