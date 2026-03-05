import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class Viewer3DErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[Viewer3D] Rendering error:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div role="alert" style={{ padding: '2rem', textAlign: 'center', color: '#e74c3c' }}>
          <h3>3D 뷰어 로드 실패</h3>
          <p>{this.state.error?.message ?? '알 수 없는 오류가 발생했습니다.'}</p>
          <button onClick={() => this.setState({ hasError: false, error: null })}>
            다시 시도
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
