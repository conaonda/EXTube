import { authFetch, getAccessToken } from './auth'

const API_BASE = '/api'

export interface JobResult {
  video_title: string
  total_frames: number
  filtered_frames: number
  num_registered: number
  num_points3d: number
  steps_completed: string[]
  has_potree?: boolean
  has_gaussian_splatting?: boolean
  gaussian_splatting_format?: string
}

export interface Job {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  url: string
  error: string | null
  result: JobResult | null
}

export async function createJob(url: string): Promise<Job> {
  const res = await authFetch(`${API_BASE}/jobs`, {
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
  const res = await authFetch(`${API_BASE}/jobs/${jobId}`)
  if (!res.ok) {
    throw new Error(`작업 조회 실패: ${res.status}`)
  }
  return res.json()
}

export interface JobListResponse {
  items: Job[]
  total: number
}

export async function getJobs(
  status?: string,
  limit = 20,
  offset = 0,
): Promise<JobListResponse> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  const res = await authFetch(`${API_BASE}/jobs?${params}`)
  if (!res.ok) {
    throw new Error(`Job 목록 조회 실패: ${res.status}`)
  }
  return res.json()
}

function appendToken(url: string): string {
  const token = getAccessToken()
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

export function getResultUrl(jobId: string): string {
  return appendToken(`${API_BASE}/jobs/${jobId}/result`)
}

export function getPotreeUrl(jobId: string): string {
  return appendToken(`${API_BASE}/jobs/${jobId}/potree/metadata.json`)
}

export function getSplatUrl(jobId: string): string {
  return appendToken(`${API_BASE}/jobs/${jobId}/splat`)
}

export function isSplatFormat(url: string): boolean {
  return /\.(splat|spz|ksplat)$/i.test(url)
}
