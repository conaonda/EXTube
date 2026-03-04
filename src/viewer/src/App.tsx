import { useCallback, useEffect, useRef, useState } from 'react'
import Layout from './components/Layout'
import ViewerCanvas from './components/ViewerCanvas'
import JobForm from './components/JobForm'
import JobStatusBar from './components/JobStatus'
import { createJob, getJob, getResultUrl, getStreamUrl } from './api'
import type { Job, ProgressEvent, StreamEvent } from './api'

export default function App() {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [plyUrl, setPlyUrl] = useState<string | null>(null)
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const stopStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const startPollingFallback = useCallback(
    (jobId: string) => {
      pollingRef.current = setInterval(async () => {
        try {
          const updated = await getJob(jobId)
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
    },
    [stopPolling],
  )

  const startStream = useCallback(
    (jobId: string) => {
      const es = new EventSource(getStreamUrl(jobId))
      eventSourceRef.current = es

      es.onmessage = (event) => {
        try {
          const data: StreamEvent = JSON.parse(event.data)
          setProgress(data.progress)
          setJob((prev) =>
            prev
              ? {
                  ...prev,
                  status: data.status,
                  result: data.result ?? prev.result,
                  error: data.error ?? prev.error,
                }
              : prev,
          )
          if (data.status === 'completed') {
            stopStream()
            setPlyUrl(getResultUrl(jobId))
          } else if (data.status === 'failed') {
            stopStream()
          }
        } catch {
          // ignore parse errors
        }
      }

      es.onerror = () => {
        stopStream()
        // Fallback to polling
        startPollingFallback(jobId)
      }
    },
    [stopStream, startPollingFallback],
  )

  const handleSubmit = useCallback(
    async (url: string) => {
      setError(null)
      setPlyUrl(null)
      setProgress(null)
      stopPolling()
      stopStream()

      try {
        const created = await createJob(url)
        setJob(created)
        startStream(created.id)
      } catch (err) {
        setError(err instanceof Error ? err.message : '작업 생성 실패')
      }
    },
    [stopPolling, stopStream, startStream],
  )

  useEffect(() => {
    return () => {
      stopPolling()
      stopStream()
    }
  }, [stopPolling, stopStream])

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
        {job && <JobStatusBar job={job} progress={progress} />}
      </div>
      <ViewerCanvas plyUrl={plyUrl} />
    </Layout>
  )
}
