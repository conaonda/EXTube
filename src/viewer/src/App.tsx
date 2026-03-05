import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import ViewerCanvas from './components/ViewerCanvas'
import JobForm from './components/JobForm'
import JobStatusBar from './components/JobStatus'
import { createJob, getJob, getPotreeUrl, getResultUrl, getSplatUrl } from './api'
import type { Job } from './api'
import { useJobWebSocket } from './hooks/useJobWebSocket'
import type { JobProgress, WsJobMessage } from './hooks/useJobWebSocket'

export default function App() {
  const { jobId } = useParams<{ jobId?: string }>()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
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
        // Fetch full job data on completion
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

  useJobWebSocket({ jobId: wsJobId, onMessage: onWsMessage })

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
      } catch {
        setError('작업을 찾을 수 없습니다')
      }
    },
    [stopPolling, handleJobCompleted],
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
      setProgress(null)
      stopPolling()

      try {
        const created = await createJob(url)
        setJob(created)
        setWsJobId(created.id)
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
        {job && <JobStatusBar job={job} progress={progress} />}
      </div>
      <ViewerCanvas plyUrl={plyUrl} potreeUrl={potreeUrl} splatUrl={splatUrl} />
    </>
  )
}
