import { Component } from 'react';
import type { ReactNode, ErrorInfo } from 'react';

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleRetry = () => { this.setState({ hasError: false, error: null }); };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{ padding: 48, textAlign: 'center' }}>
          <div style={{
            background: 'var(--bg-card, #0f172a)',
            border: '1px solid #dc2626',
            borderRadius: 14, padding: 32, maxWidth: 420, margin: '0 auto',
          }}>
            <div style={{
              width: 48, height: 48, borderRadius: '50%',
              background: 'rgba(239,68,68,0.1)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 16px',
            }}>
              <span style={{ fontSize: 24 }}>⚠</span>
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary, #e2e8f0)', margin: '0 0 8px' }}>Something went wrong</h3>
            <p style={{ fontSize: 12, color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.5, marginBottom: 8 }}>
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <p style={{ fontSize: 10, color: 'var(--text-muted, #475569)', marginBottom: 20, fontFamily: 'ui-monospace,monospace' }}>
              {this.state.error?.name}
            </p>
            <button
              onClick={this.handleRetry}
              style={{ padding: '10px 24px', fontSize: 13, fontWeight: 600, color: '#fff', background: '#2563eb', borderRadius: 8, border: 'none', cursor: 'pointer' }}
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
