import { test, expect } from '@playwright/test'
import { loginViaLocalStorage } from './helpers'

test.describe('에러 핸들링', () => {
  test('잘못된 URL 제출 시 에러 메시지가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: '유효하지 않은 유튜브 URL입니다',
          }),
        })
      }
    })

    await loginViaLocalStorage(page)

    const urlInput = page
      .locator('input[type="url"], input[type="text"]')
      .first()
    await urlInput.fill('not-a-url')
    await page.getByTestId('job-submit').click()

    await expect(page.getByRole('alert')).toBeVisible({ timeout: 5000 })
  })

  test('네트워크 오류 시 에러 메시지가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs', async (route) => {
      if (route.request().method() === 'POST') {
        await route.abort('connectionrefused')
      }
    })

    await loginViaLocalStorage(page)

    const urlInput = page
      .locator('input[type="url"], input[type="text"]')
      .first()
    await urlInput.fill('https://www.youtube.com/watch?v=test123')
    await page.getByTestId('job-submit').click()

    await expect(page.getByRole('alert')).toBeVisible({ timeout: 5000 })
  })

  test('복원 실패 시 실패 상태와 에러가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs/failed-job-1', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'failed-job-1',
          status: 'failed',
          url: 'https://www.youtube.com/watch?v=test',
          error: 'COLMAP 복원 실패: 특징점이 부족합니다',
          result: null,
          gs_splat_url: null,
          retry_count: 2,
        }),
      })
    })

    await loginViaLocalStorage(page)
    await page.goto('/jobs/failed-job-1')

    await expect(page.getByText('실패', { exact: true })).toBeVisible({ timeout: 5000 })
    await expect(
      page.getByText('COLMAP 복원 실패: 특징점이 부족합니다'),
    ).toBeVisible()
  })

  test('존재하지 않는 작업 접근 시 에러가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs/nonexistent-job', async (route) => {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: '작업을 찾을 수 없습니다',
        }),
      })
    })

    await loginViaLocalStorage(page)
    await page.goto('/jobs/nonexistent-job')

    await expect(page.getByRole('alert')).toBeVisible({ timeout: 5000 })
  })

  test('서버 500 에러 시 에러 메시지가 표시된다', async ({ page }) => {
    await page.route('**/api/jobs', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: '내부 서버 오류',
          }),
        })
      }
    })

    await loginViaLocalStorage(page)

    const urlInput = page
      .locator('input[type="url"], input[type="text"]')
      .first()
    await urlInput.fill('https://www.youtube.com/watch?v=valid123')
    await page.getByTestId('job-submit').click()

    await expect(page.getByRole('alert')).toBeVisible({ timeout: 5000 })
  })
})

test.describe('작업 취소', () => {
  test('처리 중인 작업을 취소할 수 있다', async ({ page }) => {
    await page.route('**/api/jobs', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'cancel-test-1',
            status: 'pending',
            url: 'https://www.youtube.com/watch?v=test',
            error: null,
            result: null,
            gs_splat_url: null,
            retry_count: 0,
          }),
        })
      }
    })

    await page.route('**/api/jobs/cancel-test-1/cancel', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'cancel-test-1',
          status: 'cancelled',
          url: 'https://www.youtube.com/watch?v=test',
          error: '사용자에 의해 취소됨',
          result: null,
          gs_splat_url: null,
          retry_count: 0,
        }),
      })
    })

    // WebSocket 연결 시도를 무시
    await page.route('**/ws/**', async (route) => {
      await route.abort()
    })

    await loginViaLocalStorage(page)

    const urlInput = page
      .locator('input[type="url"], input[type="text"]')
      .first()
    await urlInput.fill('https://www.youtube.com/watch?v=test')
    await page.getByTestId('job-submit').click()

    // 대기 상태 확인
    await expect(page.getByText(/pending|대기/i)).toBeVisible({
      timeout: 5000,
    })

    // 취소 버튼 클릭
    await page.getByTestId('job-cancel').click()

    // 취소 상태 확인
    await expect(page.getByText('취소됨', { exact: true })).toBeVisible({ timeout: 5000 })
  })
})
