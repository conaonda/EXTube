# 대용량 포인트 클라우드 렌더링 최적화 조사 보고서

> 조사 기준일: 2026-03-05
> 관련 이슈: #50

## 요약

수백만~수천만 점의 포인트 클라우드를 웹에서 60fps로 렌더링하기 위해 **Potree 기반 LoD + `@pnext/three-loader`** 도입을 권장한다.

## 접근법 비교

| 접근법 | 장점 | 단점 | 적합 시나리오 |
|--------|------|------|---------------|
| **Raw THREE.Points** | 구현 간단 | 10M+ 점에서 성능 저하 | <5M 점 |
| **Potree LoD (octree)** | Point budget으로 일정 FPS 보장 | 사전 변환 필요 | 10M-100M+ 점 |
| **WebGPU compute** | 최고 성능 (2-10x) | 브라우저 지원 ~70% | 향후 |

## 성능 목표 달성 가능성 (10M+ 점 @ 60fps)

| 시나리오 | 기법 | 달성 가능? | 비고 |
|----------|------|-----------|------|
| 10M점, 정적 뷰 | Raw THREE.Points | O (데스크탑) | 240MB VRAM, 단일 draw call |
| 10M점, 인터랙티브 | THREE.Points | 30-45fps | 중급 GPU overdraw |
| 10M점, 인터랙티브 | **Potree LoD (2M budget)** | **60fps** | 항상 2M점만 렌더링 |
| 50M+점 | Potree LoD + WebGPU | 60fps | 3-5M budget 가능 |

> **핵심**: 10M+ 점을 동시에 렌더링하지 않는다. **Point budget 1.5-3M**으로 Potree octree LoD 적용 시 60fps 달성.

## Potree 관련 라이브러리 비교

| 라이브러리 | 언어 | Three.js 통합 | 유지보수 | npm 주간 DL |
|-----------|------|--------------|---------|-------------|
| **@pnext/three-loader** | TypeScript | 임베딩 전용 설계 | 활발 | ~568 |
| potree-core | JS | 래퍼 필요 | 저조 | 낮음 |
| PotreeDesktop | C++ | N/A (네이티브) | 활발 | N/A |

## R3F 통합 패턴 (@pnext/three-loader)

```tsx
function PointCloudScene({ url }: { url: string }) {
  const potree = useMemo(() => new Potree(), []);
  const groupRef = useRef<THREE.Group>(null);

  useEffect(() => {
    potree.loadPointCloud(url, (data) => {
      groupRef.current?.add(data.pointCloud);
    });
  }, [url]);

  useFrame(() => potree.updatePointClouds([...], camera, renderer));

  return <group ref={groupRef} />;
}
```

**PotreeConverter 2.x**로 사전 변환 필요 -> Docker 파이프라인에 변환 단계 추가.

## WebGPU 현황 (2026.03)

- Chrome 113+, Firefox 147+, Safari (iOS 26/macOS Tahoe) 지원 — ~70% 글로벌 커버리지
- Three.js `WebGPURenderer` (r160+) WebGL2 폴백 포함
- Potree 기반 로더는 아직 WebGPU 미지원 (CPU 측 LOD/culling이므로 영향 제한적)

## 권장 전략

**`@pnext/three-loader` + PotreeConverter 2.x 도입 권장**

| 이유 | 설명 |
|---|---|
| TypeScript 네이티브 | 프로젝트 스택과 일치 |
| Three.js 임베딩 전용 | UI 오버헤드 없음 |
| Point budget 2M | 중급 하드웨어에서 30-60 FPS |
| 규모 커버 | 유튜브 기반 복원 (1M-20M점) 충분 |

### 로드맵

| 단계 | 시기 | 접근법 |
|---|---|---|
| **단기** | 지금 | `@pnext/three-loader` + PotreeConverter 2.x |
| **중기** | 6-12개월 | Three.js WebGPU 렌더러 전환 (WebGL2 폴백) |
| **장기** | 12-24개월 | Potree-Next v3.0 모니터링 |

### 파이프라인 통합

서버 측 `PotreeConverter` Docker 통합으로 COLMAP dense 출력 -> Potree 포맷 자동 변환 파이프라인 구축.
