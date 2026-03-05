import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import ViewerCanvas from './components/ViewerCanvas'
import JobForm from './components/JobForm'
import JobStatusBar from './components/JobStatus'
import { ApiError, createJob, getJob, getPotreeUrl, getResultUrl, getSplatUrl } from './api'
import type { Job } from './api'
import { useJobWebSocket } from './hooks/useJobWebSocket'
import type { JobProgress, WsJobMessage } from './hooks/useJobWebSocket'
import { useToast } from './hooks/useToast'
import { getAccessToken } from './auth'
import './App.css'

export default function App() {
  const { jobId } = useParams<{ jobId?: string }>()
  const { addToast } = useToast()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastFailedUrl, setLastFailedUrl] = useState<string | null>(null)
  const [plyUrl, setPlyUrl] = useState<string | null>(null)
  const [potreeUrl, setPotreeUrl] = useState<string | null>(null)
  const [splatUrl, setSplatUrl] = useState<string | null>(null)
  const [progress, setProgress] = useState<JobProgress | null>(null)
  const [wsJobId, setWsJobId] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const handleJobCompleted = useCallback(
    (updated: Job) => {
      setJob(updated)
      setProgress(null)
      setWsJobId(null)
      if (updated.result?.has_gaussian_splatting) {
        setSplatUrl(getSplatUrl(updated.id))
      } else if (updated.result?.has_potree) {
        setPotreeUrl(getPotreeUrl(updated.id))
      } else {
        setPlyUrl(getResultUrl(updated.id))
      }
    },
    [],
  )

  const onWsMessage = useCallback(
    (msg: WsJobMessage) => {
      if (msg.status === 'completed') {
        if (wsJobId) {
          getJob(wsJobId).then(handleJobCompleted).catch(() => {})
        }
      } else if (msg.status === 'failed') {
        setJob((prev) =>
          prev ? { ...prev, status: 'failed', error: msg.error ?? null } : prev,
        )
        setProgress(null)
        setWsJobId(null)
      } else if (msg.progress) {
        setProgress(msg.progress)
        setJob((prev) =>
          prev && prev.status !== 'completed' && prev.status !== 'failed'
            ? { ...prev, status: 'processing' }
            : prev,
        )
      }
    },
    [wsJobId, handleJobCompleted],
  )

  useJobWebSocket({ jobId: wsJobId, token: getAccessToken(), onMessage: onWsMessage })

  const loadJob = useCallback(
    async (id: string) => {
      setError(null)
      setPlyUrl(null)
      setPotreeUrl(null)
      setSplatUrl(null)
      setProgress(null)
      stopPolling()

      try {
        const loaded = await getJob(id)
        setJob(loaded)
        if (loaded.status === 'completed') {
          handleJobCompleted(loaded)
        } else if (loaded.status === 'pending' || loaded.status === 'processing') {
          setWsJobId(loaded.id)
        }
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : '작업을 찾을 수 없습니다'
        setError(msg)
        const toastType = err instanceof ApiError && err.retryable ? 'warning' : 'error'
        addToast(msg, toastType)
      }
    },
    [stopPolling, handleJobCompleted, addToast],
  )

  // Load job from URL param
  useEffect(() => {
    if (!jobId) return
    loadJob(jobId) // eslint-disable-line react-hooks/set-state-in-effect -- loading from URL param
  }, [jobId, loadJob])

  const handleSubmit = useCallback(
    async (url: string) => {
      setError(null)
      setPlyUrl(null)
      setPotreeUrl(null)
      setSplatUrl(null)
      setProgress(null)
      stopPolling()

      try {
        const created = await createJob(url)
        setJob(created)
        setWsJobId(created.id)
        setLastFailedUrl(null)
      } catch (err) {
        const msg = err instanceof Error ? err.message : '작업 생성 실패'
        setError(msg)
        if (err instanceof ApiError && err.retryable) {
          setLastFailedUrl(url)
          addToast(msg, 'warning')
        } else {
          setLastFailedUrl(null)
          addToast(msg, 'error')
        }
      }
    },
    [stopPolling, addToast],
  )

  useEffect(() => {
    return stopPolling
  }, [stopPolling])

  const isProcessing =
    job !== null && (job.status === 'pending' || job.status === 'processing')

  return (
    <>
      <div className="app-overlay" role="region" aria-label="작업 제어 패널">
        <JobForm onSubmit={handleSubmit} disabled={isProcessing} />
        {error && (
          <div className="error-bar" role="alert">
            <span className="error-bar-message">{error}</span>
            {lastFailedUrl && (
              <button
                className="error-bar-retry"
                onClick={() => handleSubmit(lastFailedUrl)}
                aria-label="작업 재시도"
              >
                재시도
              </button>
            )}
          </div>
        )}
        {job && <JobStatusBar job={job} progress={progress} />}
      </div>
      <ViewerCanvas plyUrl={plyUrl} potreeUrl={potreeUrl} splatUrl={splatUrl} />
    </>
  )
}
