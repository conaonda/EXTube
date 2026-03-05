import type { Job } from '../api'
import type { JobProgress } from '../hooks/useJobWebSocket'

const STATUS_LABELS: Record<string, string> = {
  pending: '대기 중...',
  processing: '처리 중...',
  completed: '완료',
  failed: '실패',
}

const STAGE_LABELS: Record<string, string> = {
  download: '다운로드',
  extraction: '프레임 추출',
  reconstruction: '3D 복원',
}

interface JobStatusProps {
  job: Job
  progress?: JobProgress | null
}

export default function JobStatus({ job, progress }: JobStatusProps) {
  const label = STATUS_LABELS[job.status] ?? job.status

  return (
    <div
      className={`job-status ${job.status === 'failed' ? 'job-status--failed' : 'job-status--default'}`}
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
    </div>
  )
}
