import type { Page } from '@playwright/test'

function base64(obj: Record<string, unknown>): string {
  return Buffer.from(JSON.stringify(obj)).toString('base64')
}

export function createMockJwt(payload: Record<string, unknown>): string {
  const header = base64({ alg: 'HS256', typ: 'JWT' })
  const body = base64({
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...payload,
  })
  return `${header}.${body}.fake-signature`
}

export async function loginViaLocalStorage(page: Page) {
  const mockToken = createMockJwt({
    sub: 'user123',
    username: 'testuser',
    type: 'access',
  })

  // 먼저 페이지를 로드하여 localStorage 접근 가능하게 함
  await page.goto('/login')
  await page.evaluate(
    ({ token }) => {
      localStorage.setItem('extube_access_token', token)
      localStorage.setItem('extube_refresh_token', 'mock.refresh.token')
    },
    { token: mockToken },
  )
  // 토큰 설정 후 메인 페이지로 이동
  await page.goto('/')
}

export async function mockLoginApi(page: Page) {
  const mockToken = createMockJwt({
    sub: 'user123',
    username: 'testuser',
    type: 'access',
  })

  await page.route('**/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: mockToken,
        refresh_token: 'mock.refresh.token',
        token_type: 'bearer',
      }),
    })
  })
}
