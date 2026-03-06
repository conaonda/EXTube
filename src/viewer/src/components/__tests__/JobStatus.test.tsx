import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Job } from '../../api'
import JobStatus from '../JobStatus'

const baseJob: Job = {
  id: 'abc123',
  status: 'pending',
  url: 'https://youtube.com/watch?v=test',
  error: null,
  result: null,
}

describe('JobStatus', () => {
  it('renders pending status', () => {
    render(<JobStatus job={{ ...baseJob, status: 'pending' }} />)
    expect(screen.getByText('대기 중...')).toBeInTheDocument()
  })

  it('renders processing status', () => {
    render(<JobStatus job={{ ...baseJob, status: 'processing' }} />)
    expect(screen.getByText('처리 중...')).toBeInTheDocument()
  })

  it('renders completed status', () => {
    render(<JobStatus job={{ ...baseJob, status: 'completed' }} />)
    expect(screen.getByText('완료')).toBeInTheDocument()
  })

  it('renders failed status', () => {
    render(<JobStatus job={{ ...baseJob, status: 'failed' }} />)
    expect(screen.getByText('실패')).toBeInTheDocument()
  })

  it('shows error message when job has error', () => {
    render(
      <JobStatus job={{ ...baseJob, status: 'failed', error: 'COLMAP 실패' }} />,
    )
    expect(screen.getByText('COLMAP 실패')).toBeInTheDocument()
  })

  it('shows result info when job is completed', () => {
    render(
      <JobStatus
        job={{
          ...baseJob,
          status: 'completed',
          result: {
            video_title: 'Test',
            total_frames: 100,
            filtered_frames: 80,
            num_registered: 50,
            num_points3d: 10000,
            steps_completed: ['sparse'],
          },
        }}
      />,
    )
    expect(screen.getByText(/10,000/)).toBeInTheDocument()
    expect(screen.getByText(/50/)).toBeInTheDocument()
  })

  it('shows progress when processing with progress data', () => {
    render(
      <JobStatus
        job={{ ...baseJob, status: 'processing' }}
        progress={{ stage: 'download', percent: 50, message: '다운로드 중' }}
      />,
    )
    expect(screen.getByText(/다운로드/)).toBeInTheDocument()
    expect(screen.getByText(/50%/)).toBeInTheDocument()
    expect(screen.getByText(/다운로드 중/)).toBeInTheDocument()
  })

  it('shows cancel button for pending job when onCancel is provided', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'pending' }} onCancel={onCancel} />)
    expect(screen.getByText('취소')).toBeInTheDocument()
  })

  it('shows cancel button for processing job when onCancel is provided', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'processing' }} onCancel={onCancel} />)
    expect(screen.getByText('취소')).toBeInTheDocument()
  })

  it('shows cancel button for retrying job when onCancel is provided', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'retrying' }} onCancel={onCancel} />)
    expect(screen.getByText('취소')).toBeInTheDocument()
  })

  it('does not show cancel button for completed job', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'completed' }} onCancel={onCancel} />)
    expect(screen.queryByText('취소')).not.toBeInTheDocument()
  })

  it('does not show cancel button when onCancel is not provided', () => {
    render(<JobStatus job={{ ...baseJob, status: 'pending' }} />)
    expect(screen.queryByText('취소')).not.toBeInTheDocument()
  })

  it('calls onCancel when cancel button is clicked', async () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'processing' }} onCancel={onCancel} />)
    await userEvent.click(screen.getByText('취소'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('does not show progress when status is not processing', () => {
    const { container } = render(
      <JobStatus
        job={{ ...baseJob, status: 'completed' }}
        progress={{ stage: 'download', percent: 50, message: '다운로드 중' }}
      />,
    )
    expect(container.textContent).not.toContain('50%')
  })
})
