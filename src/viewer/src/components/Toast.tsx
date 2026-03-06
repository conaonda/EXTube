import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ToastContext } from '../hooks/useToast'
import type { ToastAction, ToastType } from '../hooks/useToast'

interface ToastItem {
  id: number
  message: string
  type: ToastType
  action?: ToastAction
}

const TOAST_DURATION = 5000

const typeStyles: Record<ToastType, { bg: string; border: string; color: string }> = {
  error: { bg: '#fef2f2', border: '#fca5a5', color: '#dc2626' },
  success: { bg: '#f0fdf4', border: '#86efac', color: '#16a34a' },
  warning: { bg: '#fffbeb', border: '#fcd34d', color: '#d97706' },
  info: { bg: '#eff6ff', border: '#93c5fd', color: '#2563eb' },
}

function ToastItemView({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const style = typeStyles[toast.type]
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const onDismissRef = useRef(onDismiss)

  useEffect(() => {
    onDismissRef.current = onDismiss
  }, [onDismiss])

  useEffect(() => {
    timerRef.current = setTimeout(() => onDismissRef.current(), TOAST_DURATION)
    return () => clearTimeout(timerRef.current)
  }, [])

  return (
    <div
      style={{
        padding: '0.625rem 0.875rem',
        background: style.bg,
        border: `1px solid ${style.border}`,
        borderRadius: '6px',
        color: style.color,
        fontSize: '0.875rem',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        animation: 'toast-in 0.2s ease-out',
      }}
    >
      <span style={{ flex: 1 }}>{toast.message}</span>
      {toast.action && (
        <button
          onClick={() => {
            toast.action!.onClick()
            onDismiss()
          }}
          style={{
            padding: '0.25rem 0.5rem',
            background: style.color,
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '0.75rem',
            fontWeight: 600,
            whiteSpace: 'nowrap',
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button
        onClick={onDismiss}
        style={{
          background: 'none',
          border: 'none',
          color: style.color,
          cursor: 'pointer',
          fontSize: '1rem',
          lineHeight: 1,
          padding: '0 0.25rem',
          opacity: 0.6,
        }}
        aria-label="닫기"
      >
        ×
      </button>
    </div>
  )
}

let toastId = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const addToast = useCallback(
    (message: string, type: ToastType = 'error', action?: ToastAction) => {
      const id = ++toastId
      setToasts((prev) => [...prev, { id, message, type, action }])
    },
    [],
  )

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <style>{`
        @keyframes toast-in {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div
        style={{
          position: 'fixed',
          top: '1rem',
          right: '1rem',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          maxWidth: '400px',
          width: '100%',
          pointerEvents: toasts.length ? 'auto' : 'none',
        }}
      >
        {toasts.map((t) => (
          <ToastItemView key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}
