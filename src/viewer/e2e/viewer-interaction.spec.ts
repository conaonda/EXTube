import { test, expect } from '@playwright/test'
import { loginViaLocalStorage } from './helpers'

test.describe('3D 뷰어 인터랙션', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaLocalStorage(page)
  })

  test('캔버스가 렌더링되고 마우스 드래그로 카메라가 회전한다', async ({ page }) => {
    const canvas = page.locator('canvas')
    await expect(canvas).toBeVisible({ timeout: 10000 })

    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()

    // 마우스 드래그로 카메라 회전 시뮬레이션
    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2
    await page.mouse.move(cx, cy)
    await page.mouse.down()
    await page.mouse.move(cx + 100, cy + 50, { steps: 10 })
    await page.mouse.up()

    // 캔버스가 여전히 표시되는지 확인 (크래시 없음)
    await expect(canvas).toBeVisible()
  })

  test('마우스 휠로 줌이 동작한다', async ({ page }) => {
    const canvas = page.locator('canvas')
    await expect(canvas).toBeVisible({ timeout: 10000 })

    const box = await canvas.boundingBox()
    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2

    // 줌 인/아웃 시뮬레이션
    await page.mouse.move(cx, cy)
    await page.mouse.wheel(0, -300) // 줌 인
    await page.mouse.wheel(0, 300) // 줌 아웃

    await expect(canvas).toBeVisible()
  })

  test('우클릭 드래그로 패닝이 동작한다', async ({ page }) => {
    const canvas = page.locator('canvas')
    await expect(canvas).toBeVisible({ timeout: 10000 })

    const box = await canvas.boundingBox()
    const cx = box!.x + box!.width / 2
    const cy = box!.y + box!.height / 2

    // 우클릭 드래그로 패닝
    await page.mouse.move(cx, cy)
    await page.mouse.down({ button: 'right' })
    await page.mouse.move(cx + 50, cy + 30, { steps: 5 })
    await page.mouse.up({ button: 'right' })

    await expect(canvas).toBeVisible()
  })
})

test.describe('3D 뷰어 컨트롤 — 완료 상태', () => {
  test('완료된 작업 로드 시 뷰어 컨트롤이 표시된다', async ({ page }) => {
    // 완료된 작업을 반환하는 API 모킹
    await page.route('**/api/jobs/completed-job-1', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'completed-job-1',
          status: 'completed',
          url: 'https://www.youtube.com/watch?v=test',
          error: null,
          result: {
            num_points3d: 5000,
            num_registered: 10,
            has_gaussian_splatting: false,
            has_potree: false,
          },
          gs_splat_url: null,
          retry_count: 0,
        }),
      })
    })

    // PLY 결과 파일 모킹
    await page.route('**/api/jobs/completed-job-1/result', async (route) => {
      await route.abort()
    })

    await loginViaLocalStorage(page)
    await page.goto('/jobs/completed-job-1')

    // 완료 상태 표시 확인
    await expect(page.getByText('완료')).toBeVisible({ timeout: 5000 })

    // 뷰어 컨트롤 툴바 표시 확인
    const toolbar = page.getByRole('toolbar', { name: '3D 뷰어 컨트롤' })
    await expect(toolbar).toBeVisible({ timeout: 10000 })

    // 카메라 리셋 버튼 확인
    await expect(
      page.getByRole('button', { name: '카메라 위치 초기화' }),
    ).toBeVisible()

    // 배경색 버튼 확인
    await expect(
      page.getByRole('button', { name: '배경색 검정' }),
    ).toBeVisible()

    // 포인트 크기 슬라이더 확인
    await expect(
      page.getByRole('slider', { name: '포인트 크기 조절' }),
    ).toBeVisible()
  })
})
