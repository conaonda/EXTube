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
      style={{
        padding: '0.5rem 0.75rem',
        background: job.status === 'failed' ? '#fef2f2' : '#f0f9ff',
        borderRadius: '4px',
        fontSize: '0.875rem',
      }}
    >
      <strong>{label}</strong>
      {progress && job.status === 'processing' && (
        <span style={{ marginLeft: '0.5rem', color: '#1d4ed8' }}>
          {STAGE_LABELS[progress.stage] ?? progress.stage} {progress.percent}%
          {progress.message && ` — ${progress.message}`}
        </span>
      )}
      {job.error && (
        <span style={{ color: '#dc2626', marginLeft: '0.5rem' }}>
          {job.error}
        </span>
      )}
      {job.result && (
        <span style={{ color: '#666', marginLeft: '0.5rem' }}>
          포인트: {job.result.num_points3d.toLocaleString()} | 카메라:{' '}
          {job.result.num_registered}
        </span>
      )}
    </div>
  )
}
