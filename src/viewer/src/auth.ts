const API_BASE = '/api'

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface User {
  id: string
  username: string
}

const ACCESS_TOKEN_KEY = 'extube_access_token'
const REFRESH_TOKEN_KEY = 'extube_refresh_token'

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function saveTokens(tokens: TokenPair): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export async function register(
  username: string,
  password: string,
): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `회원가입 실패: ${res.status}`)
  }
  return res.json()
}

export async function login(
  username: string,
  password: string,
): Promise<TokenPair> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `로그인 실패: ${res.status}`)
  }
  const tokens: TokenPair = await res.json()
  saveTokens(tokens)
  return tokens
}

let refreshPromise: Promise<TokenPair> | null = null

export async function refreshAccessToken(): Promise<TokenPair> {
  if (refreshPromise) return refreshPromise

  refreshPromise = (async () => {
    const rt = getRefreshToken()
    if (!rt) throw new Error('No refresh token')

    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!res.ok) {
      clearTokens()
      throw new Error('토큰 갱신 실패')
    }
    const tokens: TokenPair = await res.json()
    saveTokens(tokens)
    return tokens
  })().finally(() => {
    refreshPromise = null
  })

  return refreshPromise
}

export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(init?.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let res = await fetch(input, { ...init, headers })

  if (res.status === 401 && getRefreshToken()) {
    try {
      const tokens = await refreshAccessToken()
      headers.set('Authorization', `Bearer ${tokens.access_token}`)
      res = await fetch(input, { ...init, headers })
    } catch {
      // refresh failed, return original 401
    }
  }

  return res
}

export function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split('.')[1]
    return JSON.parse(atob(payload))
  } catch {
    return null
  }
}

export function getCurrentUser(): User | null {
  const token = getAccessToken()
  if (!token) return null
  const payload = parseJwtPayload(token)
  if (!payload || !payload.sub || !payload.username) return null
  return { id: payload.sub as string, username: payload.username as string }
}
