import { createContext, useCallback, useContext, useState } from 'react'
import type { ReactNode } from 'react'
import {
  login as apiLogin,
  register as apiRegister,
  clearTokens,
  getCurrentUser,
} from '../auth'
import type { User } from '../auth'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => getCurrentUser())
  const [loading] = useState(false)

  const login = useCallback(async (username: string, password: string) => {
    await apiLogin(username, password)
    setUser(getCurrentUser())
  }, [])

  const register = useCallback(async (username: string, password: string) => {
    await apiRegister(username, password)
    await apiLogin(username, password)
    setUser(getCurrentUser())
  }, [])

  const logout = useCallback(() => {
    clearTokens()
    setUser(null)
  }, [])

  return (
    <AuthContext value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
