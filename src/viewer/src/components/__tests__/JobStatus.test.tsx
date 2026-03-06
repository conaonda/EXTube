import { fireEvent, render, screen } from '@testing-library/react'
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
    expect(screen.getAllByText(/다운로드/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/50%/)).toBeInTheDocument()
    expect(screen.getByText(/다운로드 중/)).toBeInTheDocument()
  })

  it('renders progress bar with aria attributes', () => {
    render(
      <JobStatus
        job={{ ...baseJob, status: 'processing' }}
        progress={{ stage: 'feature_matching', percent: 75, message: '특징점 매칭 중' }}
      />,
    )
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '75')
    expect(bar).toHaveAttribute('aria-label', '특징점 매칭 75%')
  })

  it('renders all 5 pipeline stages', () => {
    const { container } = render(
      <JobStatus
        job={{ ...baseJob, status: 'processing' }}
        progress={{ stage: 'reconstruction', percent: 30, message: 'Sparse 복원 중' }}
      />,
    )
    const stages = container.querySelectorAll('.job-status-stage')
    expect(stages).toHaveLength(5)
    // download, extraction should be done; feature_matching should be done; reconstruction active
    expect(stages[0]).toHaveClass('job-status-stage--done')
    expect(stages[1]).toHaveClass('job-status-stage--done')
    expect(stages[2]).toHaveClass('job-status-stage--done')
    expect(stages[3]).toHaveClass('job-status-stage--active')
    expect(stages[4]).not.toHaveClass('job-status-stage--done')
    expect(stages[4]).not.toHaveClass('job-status-stage--active')
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

  it('renders cancelled status', () => {
    render(<JobStatus job={{ ...baseJob, status: 'cancelled' }} />)
    expect(screen.getByText('취소됨')).toBeInTheDocument()
  })

  it('renders retrying status', () => {
    render(<JobStatus job={{ ...baseJob, status: 'retrying' }} />)
    expect(screen.getByText('재시도 중...')).toBeInTheDocument()
  })

  it('shows cancel button for pending status', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'pending' }} onCancel={onCancel} />)
    const btn = screen.getByTestId('job-cancel')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('shows cancel button for processing status', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'processing' }} onCancel={onCancel} />)
    expect(screen.getByTestId('job-cancel')).toBeInTheDocument()
  })

  it('shows cancel button for retrying status', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'retrying' }} onCancel={onCancel} />)
    expect(screen.getByTestId('job-cancel')).toBeInTheDocument()
  })

  it('does not show cancel button for completed status', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'completed' }} onCancel={onCancel} />)
    expect(screen.queryByTestId('job-cancel')).not.toBeInTheDocument()
  })

  it('does not show cancel button for failed status', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'failed' }} onCancel={onCancel} />)
    expect(screen.queryByTestId('job-cancel')).not.toBeInTheDocument()
  })

  it('does not show cancel button for cancelled status', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'cancelled' }} onCancel={onCancel} />)
    expect(screen.queryByTestId('job-cancel')).not.toBeInTheDocument()
  })

  it('does not show cancel button when onCancel is not provided', () => {
    render(<JobStatus job={{ ...baseJob, status: 'pending' }} />)
    expect(screen.queryByTestId('job-cancel')).not.toBeInTheDocument()
  })

  it('disables cancel button when cancelling', () => {
    const onCancel = vi.fn()
    render(<JobStatus job={{ ...baseJob, status: 'processing' }} onCancel={onCancel} cancelling />)
    const btn = screen.getByTestId('job-cancel')
    expect(btn).toBeDisabled()
    expect(btn).toHaveTextContent('취소 중...')
  })
})
