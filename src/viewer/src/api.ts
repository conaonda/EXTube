import { authFetch, getAccessToken } from './auth'

const API_BASE = '/api'

export type ApiErrorKind = 'network' | 'auth' | 'rate_limit' | 'server' | 'client'

export class ApiError extends Error {
  kind: ApiErrorKind
  status: number | null
  retryable: boolean

  constructor(message: string, kind: ApiErrorKind, status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.retryable = kind === 'network' || kind === 'rate_limit' || kind === 'server'
  }
}

function classifyError(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return 'auth'
  if (status === 429) return 'rate_limit'
  if (status >= 500) return 'server'
  return 'client'
}

async function handleResponse<T>(res: Response, fallbackMsg: string): Promise<T> {
  if (res.ok) return res.json()
  const detail = await res.json().catch(() => null)
  const kind = classifyError(res.status)
  const messages: Record<ApiErrorKind, string> = {
    network: '네트워크 연결을 확인해 주세요',
    auth: '인증이 만료되었습니다. 다시 로그인해 주세요',
    rate_limit: '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요',
    server: '서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요',
    client: detail?.detail ?? `${fallbackMsg}: ${res.status}`,
  }
  throw new ApiError(
    kind === 'client' ? messages.client : messages[kind],
    kind,
    res.status,
  )
}

function wrapNetworkError(err: unknown): never {
  if (err instanceof ApiError) throw err
  throw new ApiError(
    '네트워크 연결을 확인해 주세요',
    'network',
  )
}

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
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'retrying'
  url: string
  error: string | null
  result: JobResult | null
}

export async function createJob(url: string): Promise<Job> {
  try {
    const res = await authFetch(`${API_BASE}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
    return handleResponse<Job>(res, '작업 생성 실패')
  } catch (err) {
    throw wrapNetworkError(err)
  }
}

export async function getJob(jobId: string): Promise<Job> {
  try {
    const res = await authFetch(`${API_BASE}/jobs/${jobId}`)
    return handleResponse<Job>(res, '작업 조회 실패')
  } catch (err) {
    throw wrapNetworkError(err)
  }
}

export interface JobListResponse {
  items: Job[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export async function getJobs(
  status?: string,
  page = 1,
  per_page = 20,
  sort_by = 'created_at',
  order: 'asc' | 'desc' = 'desc',
): Promise<JobListResponse> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('page', String(page))
  params.set('per_page', String(per_page))
  params.set('sort_by', sort_by)
  params.set('order', order)
  try {
    const res = await authFetch(`${API_BASE}/jobs?${params}`)
    return handleResponse<JobListResponse>(res, 'Job 목록 조회 실패')
  } catch (err) {
    throw wrapNetworkError(err)
  }
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

export async function cancelJob(jobId: string): Promise<Job> {
  try {
    const res = await authFetch(`${API_BASE}/jobs/${jobId}/cancel`, {
      method: 'POST',
    })
    return handleResponse<Job>(res, '작업 취소 실패')
  } catch (err) {
    throw wrapNetworkError(err)
  }
}
