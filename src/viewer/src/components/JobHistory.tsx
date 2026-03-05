import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, getJobs } from '../api'
import type { Job } from '../api'
import { useToast } from '../hooks/useToast'

const STATUS_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'completed', label: '완료' },
  { value: 'processing', label: '처리 중' },
  { value: 'pending', label: '대기' },
  { value: 'failed', label: '실패' },
]

const PAGE_SIZE = 20

const statusColors: Record<string, string> = {
  completed: '#16a34a',
  processing: '#2563eb',
  pending: '#d97706',
  failed: '#dc2626',
}

const statusLabels: Record<string, string> = {
  completed: '완료',
  processing: '처리 중',
  pending: '대기',
  failed: '실패',
}

export default function JobHistory() {
  const navigate = useNavigate()
  const { addToast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()

  const currentStatus = searchParams.get('status') || ''
  const currentPage = Math.max(1, Number(searchParams.get('page') || '1'))
  const currentSortBy = searchParams.get('sort_by') || 'created_at'
  const currentOrder = (searchParams.get('order') || 'desc') as 'asc' | 'desc'

  const [jobs, setJobs] = useState<Job[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getJobs(
        currentStatus || undefined,
        currentPage,
        PAGE_SIZE,
        currentSortBy,
        currentOrder,
      )
      setJobs(data.items)
      setTotalPages(data.total_pages)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Job 목록 조회 실패'
      setError(msg)
      if (err instanceof ApiError && err.retryable) {
        addToast(msg, 'warning', { label: '재시도', onClick: fetchJobs })
      }
    } finally {
      setLoading(false)
    }
  }, [currentStatus, currentPage, currentSortBy, currentOrder, addToast])

  useEffect(() => {
    fetchJobs()
  }, [fetchJobs])

  const updateParams = (updates: Record<string, string>) => {
    const params: Record<string, string> = {}
    if (currentStatus) params.status = currentStatus
    if (currentPage > 1) params.page = String(currentPage)
    if (currentSortBy !== 'created_at') params.sort_by = currentSortBy
    if (currentOrder !== 'desc') params.order = currentOrder
    Object.assign(params, updates)
    // Remove default values
    if (params.page === '1') delete params.page
    if (params.sort_by === 'created_at') delete params.sort_by
    if (params.order === 'desc') delete params.order
    if (!params.status) delete params.status
    setSearchParams(params)
  }

  const setFilter = (status: string) => {
    updateParams({ status, page: '1' })
  }

  const setPage = (page: number) => {
    updateParams({ page: String(page) })
  }

  const toggleSort = (field: string) => {
    if (currentSortBy === field) {
      updateParams({ sort_by: field, order: currentOrder === 'desc' ? 'asc' : 'desc', page: '1' })
    } else {
      updateParams({ sort_by: field, order: 'desc', page: '1' })
    }
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: '960px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>Job 히스토리</h2>
        <div style={{ display: 'flex', gap: '0.25rem', fontSize: '0.8rem' }}>
          {[
            { field: 'created_at', label: '날짜' },
            { field: 'status', label: '상태' },
          ].map(({ field, label }) => (
            <button
              key={field}
              onClick={() => toggleSort(field)}
              style={{
                padding: '0.25rem 0.5rem',
                border: '1px solid #ccc',
                borderRadius: '4px',
                background: currentSortBy === field ? '#f0f0f0' : '#fff',
                cursor: 'pointer',
                fontWeight: currentSortBy === field ? 600 : 400,
              }}
            >
              {label} {currentSortBy === field ? (currentOrder === 'desc' ? '\u2193' : '\u2191') : ''}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setFilter(opt.value)}
            style={{
              padding: '0.375rem 0.75rem',
              border: '1px solid #ccc',
              borderRadius: '4px',
              background: currentStatus === opt.value ? '#2563eb' : '#fff',
              color: currentStatus === opt.value ? '#fff' : '#333',
              cursor: 'pointer',
              fontSize: '0.875rem',
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {error && (
        <div
          style={{
            padding: '0.75rem',
            background: '#fef2f2',
            borderRadius: '4px',
            color: '#dc2626',
            marginBottom: '1rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <span style={{ flex: 1 }}>{error}</span>
          <button
            onClick={fetchJobs}
            style={{
              padding: '0.25rem 0.5rem',
              background: '#dc2626',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            재시도
          </button>
        </div>
      )}

      {loading ? (
        <div style={{ color: '#666', padding: '2rem', textAlign: 'center' }}>
          <div
            style={{
              width: '24px',
              height: '24px',
              border: '3px solid #e0e0e0',
              borderTop: '3px solid #2563eb',
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
              margin: '0 auto 0.5rem',
            }}
          />
          로딩 중...
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      ) : jobs.length === 0 ? (
        <div style={{ color: '#666', padding: '2rem', textAlign: 'center' }}>
          작업이 없습니다.
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {jobs.map((job) => (
              <div
                key={job.id}
                onClick={() => navigate(`/jobs/${job.id}`)}
                style={{
                  padding: '0.75rem 1rem',
                  border: '1px solid #e0e0e0',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '1rem',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#f9fafb'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = ''
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 500,
                      marginBottom: '0.25rem',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {job.result?.video_title || job.url}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#888' }}>{job.id}</div>
                </div>
                <span
                  style={{
                    padding: '0.25rem 0.5rem',
                    borderRadius: '4px',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: '#fff',
                    background: statusColors[job.status] || '#888',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {statusLabels[job.status] || job.status}
                </span>
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                gap: '0.5rem',
                marginTop: '1rem',
              }}
            >
              <button
                disabled={currentPage <= 1}
                onClick={() => setPage(currentPage - 1)}
                style={{
                  padding: '0.375rem 0.75rem',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  cursor: currentPage <= 1 ? 'default' : 'pointer',
                  opacity: currentPage <= 1 ? 0.5 : 1,
                }}
              >
                이전
              </button>
              <span style={{ padding: '0.375rem 0.5rem', fontSize: '0.875rem' }}>
                {currentPage} / {totalPages}
              </span>
              <button
                disabled={currentPage >= totalPages}
                onClick={() => setPage(currentPage + 1)}
                style={{
                  padding: '0.375rem 0.75rem',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  cursor: currentPage >= totalPages ? 'default' : 'pointer',
                  opacity: currentPage >= totalPages ? 0.5 : 1,
                }}
              >
                다음
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
