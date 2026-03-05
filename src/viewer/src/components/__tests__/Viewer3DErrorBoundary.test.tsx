import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Viewer3DErrorBoundary from '../Viewer3DErrorBoundary'

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error('test render error')
  return <div>child content</div>
}

describe('Viewer3DErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <Viewer3DErrorBoundary>
        <ThrowingChild shouldThrow={false} />
      </Viewer3DErrorBoundary>,
    )
    expect(screen.getByText('child content')).toBeInTheDocument()
  })

  it('renders fallback UI on error', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <Viewer3DErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </Viewer3DErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('3D 뷰어 로드 실패')).toBeInTheDocument()
    expect(screen.getByText('test render error')).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('resets error state when retry button is clicked', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    let shouldThrow = true
    function ConditionalThrow() {
      if (shouldThrow) throw new Error('test error')
      return <div>recovered</div>
    }

    render(
      <Viewer3DErrorBoundary>
        <ConditionalThrow />
      </Viewer3DErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()

    shouldThrow = false
    await userEvent.click(screen.getByText('다시 시도'))
    expect(screen.getByText('recovered')).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('renders custom fallback when provided', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <Viewer3DErrorBoundary fallback={<div>custom fallback</div>}>
        <ThrowingChild shouldThrow={true} />
      </Viewer3DErrorBoundary>,
    )
    expect(screen.getByText('custom fallback')).toBeInTheDocument()
    vi.restoreAllMocks()
  })
})
