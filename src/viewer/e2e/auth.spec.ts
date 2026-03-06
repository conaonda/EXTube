import { test, expect } from '@playwright/test'
import { mockLoginApi } from './helpers'

test.describe('로그인 플로우', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
  })

  test('로그인 페이지가 올바르게 렌더링된다', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '로그인' })).toBeVisible()
    await expect(page.getByPlaceholder('사용자명')).toBeVisible()
    await expect(page.getByPlaceholder('비밀번호')).toBeVisible()
    await expect(page.getByRole('button', { name: '로그인' })).toBeVisible()
  })

  test('회원가입 모드로 전환할 수 있다', async ({ page }) => {
    await page.getByRole('button', { name: /회원가입/ }).click()
    await expect(
      page.getByRole('heading', { name: '회원가입' }),
    ).toBeVisible()
  })

  test('미인증 사용자가 메인 페이지 접근 시 로그인으로 리다이렉트된다', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })

  test('미인증 사용자가 작업 목록 접근 시 로그인으로 리다이렉트된다', async ({
    page,
  }) => {
    await page.goto('/jobs')
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('로그인 API 모킹 플로우', () => {
  test('로그인 폼 제출 시 API가 호출된다', async ({ page }) => {
    await mockLoginApi(page)
    await page.goto('/login')
    await page.getByPlaceholder('사용자명').fill('testuser')
    await page.getByPlaceholder('비밀번호').fill('Test1234!')

    const responsePromise = page.waitForResponse('**/auth/login')
    await page.getByRole('button', { name: '로그인' }).click()

    const response = await responsePromise
    expect(response.status()).toBe(200)
  })

  test('로그인 실패 시 에러 메시지를 표시한다', async ({ page }) => {
    await page.route('**/auth/login', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: '잘못된 사용자명 또는 비밀번호입니다',
        }),
      })
    })

    await page.goto('/login')
    await page.getByPlaceholder('사용자명').fill('wronguser')
    await page.getByPlaceholder('비밀번호').fill('WrongPass1!')
    await page.getByRole('button', { name: '로그인' }).click()

    await expect(
      page.getByText('잘못된 사용자명 또는 비밀번호입니다'),
    ).toBeVisible()
  })
})
