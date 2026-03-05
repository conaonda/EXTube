import { createContext, useContext } from 'react'

export type ToastType = 'error' | 'success' | 'warning' | 'info'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastContextValue {
  addToast: (
    message: string,
    type?: ToastType,
    action?: ToastAction,
  ) => void
}

export const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
