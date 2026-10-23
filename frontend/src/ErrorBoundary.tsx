import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('RaceProof UI error caught by ErrorBoundary:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <main style={{ padding: '60px 24px', maxWidth: '720px', margin: 'auto' }}>
          <div className="panel" style={{ borderColor: '#692e30', background: '#1c1110', padding: '32px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#ff8d7a', marginBottom: '16px' }}>
              <AlertTriangle size={28} />
              <h2 style={{ margin: 0, fontSize: '18px', color: '#ffd5ce' }}>Application Interface Error</h2>
            </div>
            <p style={{ color: '#c4aba8', fontSize: '13px', lineHeight: 1.6, margin: '0 0 18px 0' }}>
              A rendering issue occurred while processing live concurrency events. The interface prevented a crash and preserved your backend state.
            </p>
            {this.state.error?.message && (
              <pre
                style={{
                  background: '#0d0707',
                  border: '1px solid #4a2122',
                  padding: '14px',
                  borderRadius: '4px',
                  color: '#ff9d9d',
                  fontSize: '11px',
                  overflow: 'auto',
                  fontFamily: 'DM Mono, monospace',
                  marginBottom: '20px',
                }}
              >
                {this.state.error.message}
              </pre>
            )}
            <button
              onClick={this.handleReset}
              className="run-button"
              style={{ background: '#ff8d7a', color: '#1c1110', cursor: 'pointer' }}
            >
              <RotateCcw size={14} />
              Reload Dashboard
            </button>
          </div>
        </main>
      )
    }

    return this.props.children
  }
}
