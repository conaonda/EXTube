import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { ToastProvider } from '../Toast'
import { useToast } from '../../hooks/useToast'

// addToast를 외부에서 직접 호출할 수 있도록 ref 방식 사용
let _addToast: ReturnType<typeof useToast>['addToast'] | undefined

function ToastTrigger() {
  const { addToast } = useToast()
  _addToast = addToast
  return null
}

function renderWithToast() {
  _addToast = undefined
  return render(
    <ToastProvider>
      <ToastTrigger />
    </ToastProvider>,
  )
}

function addToast(...args: Parameters<ReturnType<typeof useToast>['addToast']>) {
  act(() => {
    _addToast!(...args)
  })
}

describe('ToastProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it('renders children without any toast', () => {
    renderWithToast()
    expect(screen.queryByText(/.+/)).not.toBeInTheDocument()
  })

  it('shows toast message when addToast is called', () => {
    renderWithToast()
    addToast('테스트 메시지', 'error')
    expect(screen.getByText('테스트 메시지')).toBeInTheDocument()
  })

  it('auto-dismisses toast after 5 seconds', () => {
    renderWithToast()
    addToast('사라지는 메시지', 'info')
    expect(screen.getByText('사라지는 메시지')).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(5000))
    expect(screen.queryByText('사라지는 메시지')).not.toBeInTheDocument()
  })

  // BUG(#144): onDismiss가 toasts 배열 변경 시마다 새 함수로 생성되어 기존 toast 타이머가 리셋됨
  // 수정 방법: onDismissRef를 사용해 useEffect의 dependency를 빈 배열([])로 만들어야 함
  it.fails('first toast timer is NOT reset when second toast is added', () => {
    renderWithToast()
    addToast('첫 번째 toast', 'error')
    expect(screen.getByText('첫 번째 toast')).toBeInTheDocument()

    // 4초 후 두 번째 toast 추가
    act(() => vi.advanceTimersByTime(4000))
    addToast('두 번째 toast', 'info')
    expect(screen.getByText('두 번째 toast')).toBeInTheDocument()

    // 1초 더 경과 — 첫 번째 toast는 총 5초가 되어 사라져야 함
    act(() => vi.advanceTimersByTime(1000))

    // 버그 존재 시 이 assertion 실패 (첫 번째 toast가 아직 남아있음)
    expect(screen.queryByText('첫 번째 toast')).not.toBeInTheDocument()
    expect(screen.getByText('두 번째 toast')).toBeInTheDocument()
  })

  it('dismisses toast when close button is clicked', () => {
    renderWithToast()
    addToast('닫기 테스트', 'warning')
    expect(screen.getByText('닫기 테스트')).toBeInTheDocument()

    act(() => fireEvent.click(screen.getByRole('button', { name: '닫기' })))
    expect(screen.queryByText('닫기 테스트')).not.toBeInTheDocument()
  })

  it('calls action callback and dismisses when action button clicked', () => {
    const actionFn = vi.fn()
    renderWithToast()
    addToast('액션 toast', 'error', { label: '재시도', onClick: actionFn })

    act(() => fireEvent.click(screen.getByRole('button', { name: '재시도' })))
    expect(actionFn).toHaveBeenCalledOnce()
    expect(screen.queryByText('액션 toast')).not.toBeInTheDocument()
  })

  it('shows multiple toasts simultaneously', () => {
    renderWithToast()
    addToast('메시지 1', 'error')
    addToast('메시지 2', 'success')
    addToast('메시지 3', 'warning')
    expect(screen.getByText('메시지 1')).toBeInTheDocument()
    expect(screen.getByText('메시지 2')).toBeInTheDocument()
    expect(screen.getByText('메시지 3')).toBeInTheDocument()
  })
})

describe('useToast', () => {
  it('throws error when used outside ToastProvider', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<ToastTrigger />)).toThrow('useToast must be used within ToastProvider')
    consoleError.mockRestore()
  })
})
