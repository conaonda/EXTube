# Spark v2 Gaussian Splatting 렌더러 기술 조사

> 조사 기준일: 2026-03-05
> 관련 이슈: #76 (parent: #56)

## 1. 요약

EXTube의 3D 뷰어에 Gaussian Splatting 렌더링을 추가하기 위해 `@sparkjsdev/spark`와 대안 라이브러리를 조사했다. **Spark v1 (0.1.10) 즉시 도입 + v2 안정화 시 마이그레이션** 전략을 권장한다.

---

## 2. Spark 현황

### 2.1 안정 버전: v0.1.10

| 항목 | 값 |
|------|-----|
| npm 패키지 | `@sparkjsdev/spark` |
| 최신 안정 버전 | 0.1.10 |
| 언팩 크기 | ~10.5 MB (WASM 포함) |
| 번들 크기 (gzipped) | ~150 KB |
| 라이선스 | MIT |
| Three.js 통합 | Native (`Object3D` 상속) |

**지원 포맷:** `.ply` (gsplat, SuperSplat 압축, 포인트 클라우드), `.spz`, `.splat`, `.ksplat`, `.sog`

### 2.2 v2.0.0-preview 신기능

| 기능 | 설명 |
|------|------|
| LoD Splat Tree | 뷰포인트 기반 동적 디테일 선택 (고정 splat 수 500K–2.5M) |
| `.RAD` 포맷 | HTTP Range 요청 기반 스트리밍, coarse-to-fine 로딩 |
| LRU Splat Page Table | 고정 GPU 메모리 풀 (기본 16M splats), 모바일에서 100M+ splat 가능 |
| ExtSplats (32-byte) | float32 좌표로 대규모 씬 양자화 아티팩트 제거 |
| 다중 SparkRenderer | 독립 뷰포인트/씬/이펙트 동시 렌더링 |
| SparkXr | AR/VR 통합 |
| Covariance Splats | 비등방 스케일링 (실험적) |
| Chainable Modifiers | 셰이더 커스터마이징 |

**하위 호환성:** v2는 v0.1과 대부분 호환, 특수 기능 외 변경 불필요.

### 2.3 R3F 통합 패턴

Spark는 `@react-three/fiber`와 직접 통합 가능. 공식 예제 저장소: [sparkjsdev/spark-react-r3f](https://github.com/sparkjsdev/spark-react-r3f)

```tsx
import { extend, useFrame } from '@react-three/fiber'
import { SparkRenderer, SplatMesh } from '@sparkjsdev/spark'

extend({ SparkRenderer, SplatMesh })

function GaussianSplatViewer({ url }: { url: string }) {
  return (
    <Canvas>
      <sparkRenderer />
      <splatMesh url={url} />
      <OrbitControls />
    </Canvas>
  )
}
```

v2 LoD 활성화:
```tsx
<splatMesh url={url} lod={true} />
```

---

## 3. 대안 라이브러리 비교

| 기준 | Spark (0.1.10) | gsplat.js | GaussianSplats3D | antimatter15/splat |
|------|---------------|-----------|-------------------|-------------------|
| 유지보수 | Active (World Labs) | Active (Hugging Face) | Deprecated | 중단 |
| Three.js 통합 | Native Object3D | 자체 렌더러 | Native | Raw WebGL |
| R3F 지원 | 공식 예제 | 미지원 | 비공식 | 미지원 |
| 지원 포맷 | PLY, SPZ, SPLAT, KSPLAT, SOG | PLY, SPLAT | PLY, SPLAT, KSPLAT | PLY→SPLAT |
| LoD | v2 지원 | 미지원 | 미지원 | 미지원 |
| WebXR | v2 지원 | 미지원 | 미지원 | 미지원 |
| 메모리 효율 | 16 bytes/splat (packed) | 높음 | 보통 | 보통 |
| 번들 크기 | ~150KB gz | ~50KB gz | ~100KB gz | ~30KB gz |
| 라이선스 | MIT | MIT | MIT | MIT |

**결론:** Spark가 포맷 지원, Three.js/R3F 통합, LoD, 활발한 유지보수 면에서 압도적 우위.

---

## 4. 기존 PointCloudViewer와의 공존 방안

### 현재 구조
```
ViewerCanvas.tsx
├── potreeUrl → PotreePointCloud (LoD 포인트 클라우드)
└── plyUrl → PointCloud (PLY 포인트 클라우드)
```

### 제안: 포맷별 자동 전환
```
ViewerCanvas.tsx
├── potreeUrl → PotreePointCloud (LoD 포인트 클라우드)
├── splatUrl → GaussianSplatViewer (Gaussian Splatting) [신규]
└── plyUrl → PointCloud (PLY 포인트 클라우드)
```

**전환 로직:**
- 파일 확장자 기반: `.splat`, `.spz`, `.ksplat`, `.sog` → Spark 렌더러
- `.ply` → 헤더 파싱으로 GS 여부 판별 (SH 계수 존재 시 Spark, 없으면 기존 PointCloud)
- Potree 메타데이터 존재 → PotreePointCloud

**공존 가능 이유:**
- Spark의 `SplatMesh`는 `THREE.Object3D` 상속 → 같은 씬에 포인트 클라우드와 공존 가능
- `SparkRenderer`는 Three.js WebGLRenderer 위에서 동작, 별도 렌더러 불필요

---

## 5. 번들 크기 및 성능 영향

### 번들 크기 증가
| 현재 | 추가 | 합계 |
|------|------|------|
| three.js (~150KB gz) | @sparkjsdev/spark (~150KB gz) | ~300KB gz |
| potree-core (~30KB gz) | | |

WASM 모듈은 별도 로딩되므로 초기 JS 번들에는 포함되지 않음. 동적 import로 splat 뷰어 필요 시에만 로딩 가능.

### 성능 특성
- **PackedSplats:** 16 bytes/splat → 1M splats = 16MB GPU 메모리
- **렌더링:** WebGL2 기반, 대부분 모던 브라우저 지원
- **v2 LoD:** 고정 splat budget으로 대규모 씬에서도 일정 프레임레이트 유지

### 최적화 전략
```tsx
// 동적 import로 번들 분리
const GaussianSplatViewer = React.lazy(() => import('./GaussianSplatViewer'))
```

---

## 6. 권장 사항

### 단기 (즉시)
1. `@sparkjsdev/spark@0.1.10` 도입
2. `GaussianSplatViewer` 컴포넌트 구현 (R3F + SplatMesh)
3. `ViewerCanvas`에 포맷별 자동 전환 로직 추가
4. `.splat`, `.spz` 포맷 로딩 테스트

### 중기 (v2 안정화 시)
1. v2.0 stable 릴리즈 후 마이그레이션
2. LoD 활성화 (`lod: true`)로 대규모 씬 지원
3. 백엔드에서 `.RAD` 포맷 변환 파이프라인 추가

### 장기
1. SparkXr로 WebXR/VR 뷰어 확장
2. 3DGS 학습 파이프라인 (COLMAP → 3DGS 학습 → .spz 출력) 통합

---

## 7. 참고 자료

- [Spark 공식 문서](https://sparkjs.dev/docs/)
- [Spark GitHub](https://github.com/sparkjsdev/spark)
- [Spark v2.0 New Features](https://sparkjs.dev/2.0.0-preview/docs/new-features-2.0/)
- [Spark R3F 예제](https://github.com/sparkjsdev/spark-react-r3f)
- [gsplat.js (Hugging Face)](https://github.com/huggingface/gsplat.js)
- [GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D)
