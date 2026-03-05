import { useCallback, useEffect, useRef } from 'react'

export interface JobProgress {
  stage: string
  percent: number
  message: string
}

export interface WsJobMessage {
  status: string
  progress?: JobProgress | null
  result?: Record<string, unknown> | null
  error?: string | null
}

interface UseJobWebSocketOptions {
  jobId: string | null
  onMessage: (msg: WsJobMessage) => void
  reconnectInterval?: number
}

export function useJobWebSocket({
  jobId,
  onMessage,
  reconnectInterval = 3000,
}: UseJobWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!jobId) return

    let stopped = false

    function connect() {
      if (stopped) return

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/jobs/${jobId}`)
      wsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const data: WsJobMessage = JSON.parse(event.data)
          onMessageRef.current(data)
          if (data.status === 'completed' || data.status === 'failed') {
            ws.close()
          }
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        if (!stopped) {
          reconnectTimer.current = setTimeout(connect, reconnectInterval)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      stopped = true
      cleanup()
    }
  }, [jobId, reconnectInterval, cleanup])

  return { close: cleanup }
}
