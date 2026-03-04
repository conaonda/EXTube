import type { Job } from '../api'

const STATUS_LABELS: Record<string, string> = {
  pending: '대기 중...',
  processing: '처리 중...',
  completed: '완료',
  failed: '실패',
}

interface JobStatusProps {
  job: Job
}

export default function JobStatus({ job }: JobStatusProps) {
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
