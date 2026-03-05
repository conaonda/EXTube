import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import ViewerCanvas from './components/ViewerCanvas'
import JobForm from './components/JobForm'
import JobStatusBar from './components/JobStatus'
import { createJob, getJob, getPotreeUrl, getResultUrl, getSplatUrl } from './api'
import type { Job } from './api'

export default function App() {
  const { jobId } = useParams<{ jobId?: string }>()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [plyUrl, setPlyUrl] = useState<string | null>(null)
  const [potreeUrl, setPotreeUrl] = useState<string | null>(null)
  const [splatUrl, setSplatUrl] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const startPolling = useCallback(
    (id: string) => {
      pollingRef.current = setInterval(async () => {
        try {
          const updated = await getJob(id)
          setJob(updated)
          if (updated.status === 'completed') {
            stopPolling()
            if (updated.result?.has_gaussian_splatting) {
              setSplatUrl(getSplatUrl(updated.id, updated.result.gaussian_splatting_format ?? 'splat'))
            } else if (updated.result?.has_potree) {
              setPotreeUrl(getPotreeUrl(updated.id))
            } else {
              setPlyUrl(getResultUrl(updated.id))
            }
          } else if (updated.status === 'failed') {
            stopPolling()
          }
        } catch {
          stopPolling()
          setError('작업 상태 조회 실패')
        }
      }, 2000)
    },
    [stopPolling],
  )

  const loadJob = useCallback(
    async (id: string) => {
      setError(null)
      setPlyUrl(null)
      setPotreeUrl(null)
      setSplatUrl(null)
      stopPolling()

      try {
        const loaded = await getJob(id)
        setJob(loaded)
        if (loaded.status === 'completed') {
          if (loaded.result?.has_gaussian_splatting) {
            setSplatUrl(getSplatUrl(loaded.id, loaded.result.gaussian_splatting_format ?? 'splat'))
          } else if (loaded.result?.has_potree) {
            setPotreeUrl(getPotreeUrl(loaded.id))
          } else {
            setPlyUrl(getResultUrl(loaded.id))
          }
        } else if (loaded.status === 'pending' || loaded.status === 'processing') {
          startPolling(loaded.id)
        }
      } catch {
        setError('작업을 찾을 수 없습니다')
      }
    },
    [stopPolling, startPolling],
  )

  // Load job from URL param
  useEffect(() => {
    if (!jobId) return
    loadJob(jobId) // eslint-disable-line react-hooks/set-state-in-effect -- loading from URL param is valid
  }, [jobId, loadJob])

  const handleSubmit = useCallback(
    async (url: string) => {
      setError(null)
      setPlyUrl(null)
      setPotreeUrl(null)
      setSplatUrl(null)
      stopPolling()

      try {
        const created = await createJob(url)
        setJob(created)
        startPolling(created.id)
      } catch (err) {
        setError(err instanceof Error ? err.message : '작업 생성 실패')
      }
    },
    [stopPolling, startPolling],
  )

  useEffect(() => {
    return stopPolling
  }, [stopPolling])

  const isProcessing =
    job !== null && (job.status === 'pending' || job.status === 'processing')

  return (
    <>
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
      <ViewerCanvas plyUrl={plyUrl} potreeUrl={potreeUrl} splatUrl={splatUrl} />
    </>
  )
}
