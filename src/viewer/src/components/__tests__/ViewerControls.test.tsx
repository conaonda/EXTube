import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ViewerControls from '../ViewerControls'

const defaultProps = {
  pointSize: 0.05,
  onPointSizeChange: vi.fn(),
  bgColor: '#000000',
  onBgColorChange: vi.fn(),
  showBoundingBox: false,
  onToggleBoundingBox: vi.fn(),
  onResetCamera: vi.fn(),
  pointCount: null,
}

describe('ViewerControls', () => {
  it('renders toolbar with aria-label', () => {
    render(<ViewerControls {...defaultProps} />)
    expect(screen.getByRole('toolbar', { name: '3D 뷰어 컨트롤' })).toBeInTheDocument()
  })

  it('renders point size slider with current value', () => {
    render(<ViewerControls {...defaultProps} pointSize={0.05} />)
    expect(screen.getByText(/포인트 크기: 0.050/)).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: '포인트 크기 조절' })).toBeInTheDocument()
  })

  it('calls onPointSizeChange when slider changes', () => {
    const onPointSizeChange = vi.fn()
    render(<ViewerControls {...defaultProps} onPointSizeChange={onPointSizeChange} />)
    const slider = screen.getByRole('slider', { name: '포인트 크기 조절' })
    fireEvent.change(slider, { target: { value: '0.1' } })
    expect(onPointSizeChange).toHaveBeenCalledWith(0.1)
  })

  it('renders background color buttons with aria-label', () => {
    render(<ViewerControls {...defaultProps} />)
    expect(screen.getByRole('button', { name: '배경색 검정' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '배경색 그레이' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '배경색 흰색' })).toBeInTheDocument()
  })

  it('marks active background color button with aria-pressed', () => {
    render(<ViewerControls {...defaultProps} bgColor="#808080" />)
    expect(screen.getByRole('button', { name: '배경색 그레이' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '배경색 검정' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('calls onBgColorChange when bg color button clicked', async () => {
    const onBgColorChange = vi.fn()
    render(<ViewerControls {...defaultProps} onBgColorChange={onBgColorChange} />)
    await userEvent.click(screen.getByRole('button', { name: '배경색 흰색' }))
    expect(onBgColorChange).toHaveBeenCalledWith('#ffffff')
  })

  it('calls onResetCamera when reset button clicked', async () => {
    const onResetCamera = vi.fn()
    render(<ViewerControls {...defaultProps} onResetCamera={onResetCamera} />)
    await userEvent.click(screen.getByRole('button', { name: '카메라 위치 초기화' }))
    expect(onResetCamera).toHaveBeenCalled()
  })

  it('marks bounding box button with aria-pressed based on showBoundingBox', () => {
    const { rerender } = render(<ViewerControls {...defaultProps} showBoundingBox={false} />)
    expect(screen.getByRole('button', { name: '바운딩 박스 표시 토글' })).toHaveAttribute('aria-pressed', 'false')

    rerender(<ViewerControls {...defaultProps} showBoundingBox={true} />)
    expect(screen.getByRole('button', { name: '바운딩 박스 표시 토글' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('calls onToggleBoundingBox when bounding box button clicked', async () => {
    const onToggleBoundingBox = vi.fn()
    render(<ViewerControls {...defaultProps} onToggleBoundingBox={onToggleBoundingBox} />)
    await userEvent.click(screen.getByRole('button', { name: '바운딩 박스 표시 토글' }))
    expect(onToggleBoundingBox).toHaveBeenCalled()
  })

  it('does not show point count when pointCount is null', () => {
    render(<ViewerControls {...defaultProps} pointCount={null} />)
    expect(screen.queryByText(/포인트 수:/)).not.toBeInTheDocument()
  })

  it('shows point count when pointCount is provided', () => {
    render(<ViewerControls {...defaultProps} pointCount={12345} />)
    expect(screen.getByText(/12,345/)).toBeInTheDocument()
  })

  it('shows LoD label when isPotree is true', () => {
    render(<ViewerControls {...defaultProps} pointCount={1000} isPotree={true} />)
    expect(screen.getByText(/LoD/)).toBeInTheDocument()
  })
})
