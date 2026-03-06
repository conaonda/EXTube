import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../ViewerCanvas', () => ({
  default: ({ plyUrl, potreeUrl, splatUrl }: { plyUrl: string | null; potreeUrl: string | null; splatUrl: string | null }) => (
    <div
      data-testid="viewer-canvas"
      data-ply-url={plyUrl ?? ''}
      data-potree-url={potreeUrl ?? ''}
      data-splat-url={splatUrl ?? ''}
    />
  ),
}))

vi.mock('../../Gallery.css', () => ({}))

import GalleryPage from '../GalleryPage'
import { sampleItems } from '../../sampleGallery'

describe('GalleryPage', () => {
  it('renders gallery title and subtitle', () => {
    render(<GalleryPage />)
    expect(screen.getByText('Sample Gallery')).toBeInTheDocument()
    expect(screen.getByText(/사전 복원된 3D 결과물/)).toBeInTheDocument()
  })

  it('renders all sample item cards', () => {
    render(<GalleryPage />)
    for (const item of sampleItems) {
      expect(screen.getByRole('button', { name: `${item.title} 샘플 보기` })).toBeInTheDocument()
    }
  })

  it('renders card title, description and type badge', () => {
    render(<GalleryPage />)
    const firstItem = sampleItems[0]
    expect(screen.getByText(firstItem.title)).toBeInTheDocument()
    expect(screen.getByText(firstItem.description)).toBeInTheDocument()
    expect(screen.getAllByText(firstItem.type.toUpperCase()).length).toBeGreaterThanOrEqual(1)
  })

  it('switches to viewer on card click', async () => {
    const user = userEvent.setup()
    render(<GalleryPage />)

    const firstItem = sampleItems[0]
    await user.click(screen.getByRole('button', { name: `${firstItem.title} 샘플 보기` }))

    expect(screen.queryByText('Sample Gallery')).not.toBeInTheDocument()
    expect(screen.getByText('갤러리로 돌아가기', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(firstItem.title)).toBeInTheDocument()
    expect(screen.getByTestId('viewer-canvas')).toBeInTheDocument()
  })

  it('passes splatUrl when item type is splat', async () => {
    const user = userEvent.setup()
    render(<GalleryPage />)

    const splatItem = sampleItems.find((i) => i.type === 'splat')!
    await user.click(screen.getByRole('button', { name: `${splatItem.title} 샘플 보기` }))

    const canvas = screen.getByTestId('viewer-canvas')
    expect(canvas).toHaveAttribute('data-splat-url', splatItem.dataUrl)
    expect(canvas).toHaveAttribute('data-ply-url', '')
    expect(canvas).toHaveAttribute('data-potree-url', '')
  })

  it('passes plyUrl when item type is ply', async () => {
    const user = userEvent.setup()
    render(<GalleryPage />)

    const plyItem = sampleItems.find((i) => i.type === 'ply')!
    await user.click(screen.getByRole('button', { name: `${plyItem.title} 샘플 보기` }))

    const canvas = screen.getByTestId('viewer-canvas')
    expect(canvas).toHaveAttribute('data-ply-url', plyItem.dataUrl)
    expect(canvas).toHaveAttribute('data-splat-url', '')
    expect(canvas).toHaveAttribute('data-potree-url', '')
  })

  it('shows type badge in viewer header', async () => {
    const user = userEvent.setup()
    render(<GalleryPage />)

    const firstItem = sampleItems[0]
    await user.click(screen.getByRole('button', { name: `${firstItem.title} 샘플 보기` }))

    const badges = screen.getAllByText(firstItem.type.toUpperCase())
    expect(badges.length).toBeGreaterThanOrEqual(1)
  })

  it('returns to gallery on back button click', async () => {
    const user = userEvent.setup()
    render(<GalleryPage />)

    const firstItem = sampleItems[0]
    await user.click(screen.getByRole('button', { name: `${firstItem.title} 샘플 보기` }))
    expect(screen.getByTestId('viewer-canvas')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /갤러리로 돌아가기/ }))

    expect(screen.getByText('Sample Gallery')).toBeInTheDocument()
    expect(screen.queryByTestId('viewer-canvas')).not.toBeInTheDocument()
  })
})
