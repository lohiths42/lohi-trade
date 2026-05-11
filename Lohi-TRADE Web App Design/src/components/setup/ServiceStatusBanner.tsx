import { useState } from 'react';
import { AlertTriangle, X, ArrowRight } from 'lucide-react';

/**
 * ServiceStatusBanner — Inline banner for pages with unconfigured service
 * dependencies.
 *
 * Shows which service is needed and provides a direct link to
 * `/settings` (Credentials tab) to configure it. The banner is dismissible
 * but re-appears on page reload (state is not persisted).
 *
 * Requirements: 4.2, 4.3
 */

export interface ServiceStatusBannerProps {
  /** The display name of the required service (e.g., "NVIDIA NIM") */
  serviceName: string;
  /** Optional description of what the service enables */
  featureDescription?: string;
  /** Link to configure the service. Defaults to /settings */
  configureLink?: string;
}

export function ServiceStatusBanner({
  serviceName,
  featureDescription,
  configureLink = '/settings',
}: ServiceStatusBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) {
    return null;
  }

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
        padding: '14px 16px',
        borderRadius: 'var(--r-md)',
        background: 'color-mix(in srgb, var(--warn) 8%, var(--surface-2))',
        border: '1px solid color-mix(in srgb, var(--warn) 20%, transparent)',
      }}
    >
      <AlertTriangle
        size={18}
        style={{ color: 'var(--warn)', flexShrink: 0, marginTop: 1 }}
        aria-hidden="true"
      />

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--fg-primary)',
          margin: 0,
        }}>
          {serviceName} is not configured
        </p>
        <p style={{
          fontSize: 12,
          color: 'var(--fg-muted)',
          margin: '4px 0 0',
          lineHeight: 1.5,
        }}>
          {featureDescription
            ? featureDescription
            : `This feature requires ${serviceName} to be configured.`}{' '}
          <a
            href={configureLink}
            style={{
              color: 'var(--accent-2)',
              fontWeight: 600,
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            Configure now
            <ArrowRight size={12} />
          </a>
        </p>
      </div>

      <button
        onClick={() => setDismissed(true)}
        aria-label={`Dismiss ${serviceName} configuration banner`}
        style={{
          display: 'grid',
          placeItems: 'center',
          width: 28,
          height: 28,
          borderRadius: 'var(--r-sm)',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--fg-muted)',
          flexShrink: 0,
        }}
      >
        <X size={16} />
      </button>
    </div>
  );
}

export default ServiceStatusBanner;
