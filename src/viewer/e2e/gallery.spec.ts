import { test, expect } from '@playwright/test'

test.describe('갤러리 페이지', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/gallery')
  })

  test('갤러리 페이지가 올바르게 렌더링된다', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: 'Sample Gallery' }),
    ).toBeVisible()
    await expect(page.getByText('사전 복원된 3D 결과물을')).toBeVisible()

    // 샘플 카드 3개가 표시되는지 확인
    const cards = page.locator('.gallery-card')
    await expect(cards).toHaveCount(3)

    // 각 샘플 카드의 제목 확인
    await expect(page.getByText('Temple of Heaven')).toBeVisible()
    await expect(page.getByText('Seoul Street View')).toBeVisible()
    await expect(page.getByText('Japanese Garden')).toBeVisible()
  })

  test('샘플 카드 클릭 시 3D 뷰어로 전환된다', async ({ page }) => {
    await page
      .getByRole('button', { name: 'Temple of Heaven 샘플 보기' })
      .click()

    // 뷰어 헤더가 표시되는지 확인
    await expect(page.locator('.gallery-viewer-title')).toHaveText(
      'Temple of Heaven',
    )
    await expect(page.locator('.gallery-viewer-badge')).toHaveText('SPLAT')

    // 뒤로가기 버튼 확인
    const backBtn = page.locator('.gallery-back-btn')
    await expect(backBtn).toBeVisible()

    // 뒤로가기 클릭 시 갤러리로 복귀
    await backBtn.click()
    await expect(
      page.getByRole('heading', { name: 'Sample Gallery' }),
    ).toBeVisible()
  })

  test('미인증 사용자도 갤러리에 접근할 수 있다', async ({ page }) => {
    // /gallery는 인증 불필요 — 리다이렉트되지 않아야 함
    await expect(page).toHaveURL(/\/gallery/)
    await expect(
      page.getByRole('heading', { name: 'Sample Gallery' }),
    ).toBeVisible()
  })

  test('반응형 레이아웃 — 모바일 뷰포트', async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 375, height: 667 },
    })
    const page = await context.newPage()
    await page.goto('/gallery')

    await expect(
      page.getByRole('heading', { name: 'Sample Gallery' }),
    ).toBeVisible()

    // 카드가 모두 표시되는지 확인
    const cards = page.locator('.gallery-card')
    await expect(cards).toHaveCount(3)

    // 모바일에서도 카드 클릭이 동작하는지 확인
    await cards.first().click()
    await expect(page.locator('.gallery-viewer-header')).toBeVisible()

    await context.close()
  })
})
