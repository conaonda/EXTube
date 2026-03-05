const API_BASE = '/api'

export interface JobResult {
  video_title: string
  total_frames: number
  filtered_frames: number
  num_registered: number
  num_points3d: number
  steps_completed: string[]
  has_potree?: boolean
}

export interface Job {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  url: string
  error: string | null
  result: JobResult | null
}

export async function createJob(url: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `요청 실패: ${res.status}`)
  }
  return res.json()
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`)
  if (!res.ok) {
    throw new Error(`작업 조회 실패: ${res.status}`)
  }
  return res.json()
}

export function getResultUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/result`
}

export function getPotreeUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/potree/metadata.json`
}
