import { test, expect } from '@playwright/test'
import { loginViaLocalStorage } from './helpers'

test.describe('Job 제출 플로우', () => {
  test('인증된 사용자가 메인 페이지에 접근할 수 있다', async ({ page }) => {
    await loginViaLocalStorage(page)

    await expect(
      page.getByRole('region', { name: '작업 제어 패널' }),
    ).toBeVisible()
  })

  test('유효하지 않은 URL 제출 시 에러가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: '유효하지 않은 유튜브 URL',
        }),
      })
    })

    await loginViaLocalStorage(page)

    const urlInput = page
      .locator('input[type="url"], input[type="text"]')
      .first()
    await urlInput.fill('https://invalid-url.com')
    await page.getByTestId('job-submit').click()

    await expect(page.getByRole('alert')).toBeVisible()
  })

  test('Job 제출 성공 시 상태바가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'abc123def456',
            status: 'pending',
            url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            error: null,
            result: null,
            gs_splat_url: null,
            retry_count: 0,
          }),
        })
      }
    })

    // WebSocket 연결 시도를 무시
    await page.route('**/ws/**', async (route) => {
      await route.abort()
    })

    await loginViaLocalStorage(page)

    const urlInput = page
      .locator('input[type="url"], input[type="text"]')
      .first()
    await urlInput.fill('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
    await page.getByTestId('job-submit').click()

    // Job 상태 표시 확인
    await expect(page.getByText(/pending|대기/i)).toBeVisible({
      timeout: 5000,
    })
  })
})

test.describe('3D 뷰어', () => {
  test('뷰어 캔버스가 렌더링된다', async ({ page }) => {
    await loginViaLocalStorage(page)

    const canvas = page.locator('canvas')
    await expect(canvas).toBeVisible({ timeout: 10000 })
  })
})
