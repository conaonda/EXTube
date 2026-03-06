import type { Job } from '../api'
import type { JobProgress } from '../hooks/useJobWebSocket'

const STATUS_LABELS: Record<string, string> = {
  pending: '대기 중...',
  processing: '처리 중...',
  completed: '완료',
  failed: '실패',
  cancelled: '취소됨',
  retrying: '재시도 중...',
}

const STAGE_LABELS: Record<string, string> = {
  download: '다운로드',
  extraction: '프레임 추출',
  reconstruction: '3D 복원',
}

const CANCELLABLE_STATUSES = new Set(['pending', 'processing', 'retrying'])

interface JobStatusProps {
  job: Job
  progress?: JobProgress | null
  onCancel?: () => void
  cancelling?: boolean
}

export default function JobStatus({ job, progress, onCancel, cancelling }: JobStatusProps) {
  const label = STATUS_LABELS[job.status] ?? job.status
  const showCancel = onCancel && CANCELLABLE_STATUSES.has(job.status)

  return (
    <div
      className={`job-status ${job.status === 'failed' ? 'job-status--failed' : job.status === 'cancelled' ? 'job-status--cancelled' : 'job-status--default'}`}
      role="status"
      aria-label={`작업 상태: ${label}`}
      aria-live="polite"
    >
      <strong>{label}</strong>
      {progress && job.status === 'processing' && (
        <span className="job-status-progress">
          {STAGE_LABELS[progress.stage] ?? progress.stage} {progress.percent}%
          {progress.message && ` — ${progress.message}`}
        </span>
      )}
      {job.error && (
        <span className="job-status-error">
          {job.error}
        </span>
      )}
      {job.result && (
        <span className="job-status-result">
          포인트: {job.result.num_points3d.toLocaleString()} | 카메라:{' '}
          {job.result.num_registered}
        </span>
      )}
      {showCancel && (
        <button
          className="job-status-cancel"
          onClick={onCancel}
          disabled={cancelling}
          aria-label="작업 취소"
          data-testid="job-cancel"
        >
          {cancelling ? '취소 중...' : '취소'}
        </button>
      )}
    </div>
  )
}
