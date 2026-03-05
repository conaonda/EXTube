import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Job } from '../../api'

vi.mock('../../api', () => ({
  getJobs: vi.fn(),
}))

import { getJobs } from '../../api'
import JobHistory from '../JobHistory'

const mockGetJobs = vi.mocked(getJobs)

function renderWithRouter(initialEntries = ['/history']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <JobHistory />
    </MemoryRouter>,
  )
}

const mockJobs: Job[] = [
  {
    id: 'aabbccddee01',
    status: 'completed',
    url: 'https://youtube.com/watch?v=1',
    error: null,
    result: { video_title: 'Video 1', total_frames: 100, filtered_frames: 80, num_registered: 50, num_points3d: 1000, steps_completed: [] },
  },
  {
    id: 'aabbccddee02',
    status: 'failed',
    url: 'https://youtube.com/watch?v=2',
    error: 'err',
    result: null,
  },
  {
    id: 'aabbccddee03',
    status: 'processing',
    url: 'https://youtube.com/watch?v=3',
    error: null,
    result: null,
  },
]

describe('JobHistory', () => {
  it('shows loading state initially', () => {
    mockGetJobs.mockReturnValue(new Promise(() => {})) // never resolves
    renderWithRouter()
    expect(screen.getByText('로딩 중...')).toBeInTheDocument()
  })

  it('renders job list after loading', async () => {
    mockGetJobs.mockResolvedValue({ items: mockJobs, total: 3 })
    renderWithRouter()

    await waitFor(() => {
      expect(screen.getByText('Video 1')).toBeInTheDocument()
    })
    expect(screen.getByText('aabbccddee02')).toBeInTheDocument()
    expect(screen.getByText('aabbccddee03')).toBeInTheDocument()
  })

  it('shows empty state when no jobs', async () => {
    mockGetJobs.mockResolvedValue({ items: [], total: 0 })
    renderWithRouter()

    await waitFor(() => {
      expect(screen.getByText('작업이 없습니다.')).toBeInTheDocument()
    })
  })

  it('shows error message on fetch failure', async () => {
    mockGetJobs.mockRejectedValue(new Error('Network error'))
    renderWithRouter()

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('renders status filter buttons', async () => {
    mockGetJobs.mockResolvedValue({ items: [], total: 0 })
    renderWithRouter()

    expect(screen.getByRole('button', { name: '전체' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '완료' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '처리 중' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '대기' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '실패' })).toBeInTheDocument()
  })

  it('calls getJobs with status filter when filter button clicked', async () => {
    const user = userEvent.setup()
    mockGetJobs.mockResolvedValue({ items: [], total: 0 })
    renderWithRouter()

    await waitFor(() => {
      expect(mockGetJobs).toHaveBeenCalledWith(undefined, 20, 0)
    })

    await user.click(screen.getByRole('button', { name: '완료' }))

    await waitFor(() => {
      expect(mockGetJobs).toHaveBeenCalledWith('completed', 20, 0)
    })
  })

  it('renders pagination when total exceeds page size', async () => {
    mockGetJobs.mockResolvedValue({ items: mockJobs, total: 45 })
    renderWithRouter()

    await waitFor(() => {
      expect(screen.getByText('1 / 3')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: '이전' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '다음' })).toBeEnabled()
  })

  it('does not render pagination when total fits one page', async () => {
    mockGetJobs.mockResolvedValue({ items: mockJobs, total: 3 })
    renderWithRouter()

    await waitFor(() => {
      expect(screen.getByText('Video 1')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '이전' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다음' })).not.toBeInTheDocument()
  })
})
