import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** 에러 발생 시 렌더링할 대체 UI. 미제공 시 기본 에러 UI를 표시한다. */
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * 3D 뷰어 렌더링 에러를 포착하는 React Error Boundary.
 *
 * 자식 컴포넌트에서 렌더링 오류가 발생하면 기본 에러 UI(또는 `fallback` prop)를 표시한다.
 * "다시 시도" 버튼으로 에러 상태를 초기화할 수 있다.
 *
 * @example
 * ```tsx
 * <Viewer3DErrorBoundary>
 *   <ViewerCanvas plyUrl={url} />
 * </Viewer3DErrorBoundary>
 * ```
 */
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
