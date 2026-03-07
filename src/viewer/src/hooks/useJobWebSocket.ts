import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'

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
  seq?: number
}

export type WsConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting'

interface UseJobWebSocketOptions {
  jobId: string | null
  token: string | null
  onMessage: (msg: WsJobMessage) => void
  maxReconnectDelay?: number
}

const INITIAL_RECONNECT_DELAY = 1000
const BACKOFF_MULTIPLIER = 2

export function useJobWebSocket({
  jobId,
  token,
  onMessage,
  maxReconnectDelay = 30000,
}: UseJobWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  const lastSeqRef = useRef(0)
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY)
  const connectionStatusRef = useRef<WsConnectionStatus>('disconnected')
  const listenersRef = useRef(new Set<() => void>())

  const subscribe = useCallback((listener: () => void) => {
    listenersRef.current.add(listener)
    return () => listenersRef.current.delete(listener)
  }, [])

  const getSnapshot = useCallback(() => connectionStatusRef.current, [])

  const connectionStatus = useSyncExternalStore(subscribe, getSnapshot)

  function setStatus(status: WsConnectionStatus) {
    if (connectionStatusRef.current !== status) {
      connectionStatusRef.current = status
      listenersRef.current.forEach((l) => l())
    }
  }

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
    if (!jobId || !token) {
      return
    }

    let stopped = false

    function connect() {
      if (stopped) return

      setStatus(lastSeqRef.current > 0 ? 'reconnecting' : 'connecting')

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/jobs/${jobId}`)
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify({ token, last_seq: lastSeqRef.current }))
        setStatus('connected')
        reconnectDelayRef.current = INITIAL_RECONNECT_DELAY
      }

      ws.onmessage = (event) => {
        try {
          const data: WsJobMessage = JSON.parse(event.data)
          if (data.seq !== undefined) {
            lastSeqRef.current = data.seq
          }
          onMessageRef.current(data)
          if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
            stopped = true
            setStatus('disconnected')
            ws.close()
          }
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        if (!stopped) {
          setStatus('reconnecting')
          const delay = reconnectDelayRef.current
          reconnectDelayRef.current = Math.min(delay * BACKOFF_MULTIPLIER, maxReconnectDelay)
          reconnectTimer.current = setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      stopped = true
      setStatus('disconnected')
      cleanup()
    }
  }, [jobId, token, maxReconnectDelay, cleanup])

  return { close: cleanup, connectionStatus }
}
