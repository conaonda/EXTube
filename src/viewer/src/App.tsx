import { useCallback, useEffect, useRef, useState } from 'react'
import Layout from './components/Layout'
import ViewerCanvas from './components/ViewerCanvas'
import JobForm from './components/JobForm'
import JobStatusBar from './components/JobStatus'
import { createJob, getJob, getResultUrl } from './api'
import type { Job } from './api'

export default function App() {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [plyUrl, setPlyUrl] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const handleSubmit = useCallback(
    async (url: string) => {
      setError(null)
      setPlyUrl(null)
      stopPolling()

      try {
        const created = await createJob(url)
        setJob(created)

        pollingRef.current = setInterval(async () => {
          try {
            const updated = await getJob(created.id)
            setJob(updated)
            if (updated.status === 'completed') {
              stopPolling()
              setPlyUrl(getResultUrl(updated.id))
            } else if (updated.status === 'failed') {
              stopPolling()
            }
          } catch {
            stopPolling()
            setError('작업 상태 조회 실패')
          }
        }, 2000)
      } catch (err) {
        setError(err instanceof Error ? err.message : '작업 생성 실패')
      }
    },
    [stopPolling],
  )

  useEffect(() => {
    return stopPolling
  }, [stopPolling])

  const isProcessing =
    job !== null && (job.status === 'pending' || job.status === 'processing')

  return (
    <Layout>
      <div
        style={{
          position: 'absolute',
          top: '1rem',
          left: '1rem',
          right: '1rem',
          zIndex: 10,
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }}
      >
        <JobForm onSubmit={handleSubmit} disabled={isProcessing} />
        {error && (
          <div
            style={{
              padding: '0.5rem 0.75rem',
              background: '#fef2f2',
              borderRadius: '4px',
              color: '#dc2626',
              fontSize: '0.875rem',
            }}
          >
            {error}
          </div>
        )}
        {job && <JobStatusBar job={job} />}
      </div>
      <ViewerCanvas plyUrl={plyUrl} />
    </Layout>
  )
}
