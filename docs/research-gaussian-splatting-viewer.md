# Gaussian Splatting 웹 렌더러 조사 보고서

> 조사 기준일: 2026-03-05
> 관련 이슈: #56

## 요약

3DGS 파이프라인에서 생성되는 `.splat`/`.spz` 파일을 웹에서 렌더링하기 위한 라이브러리를 비교하고, **`@sparkjsdev/spark`** 도입을 권장한다.

## 웹 기반 3DGS 렌더러 비교표

| 기준 | **Spark** (sparkjsdev) | **gsplat.js** (HF) | **antimatter15/splat** | **GaussianSplats3D** | **@lumaai/luma-web** |
|---|---|---|---|---|---|
| **상태** | Active (World Labs) | Active | 유지보수 중단 | **Deprecated** (Spark 권장) | Active (Luma AI) |
| **최신 버전** | 0.1.10 (v2 preview) | ~0.0.x | N/A | ~0.4.x | 0.2.2 |
| **Three.js 통합** | Native (Object3D) | 자체 렌더러 | 없음 (raw WebGL) | Native | Native |
| **R3F 지원** | 공식 예제 | 없음 | 없음 | 커뮤니티 래퍼 | 문서화 |
| **.PLY** | O | O | O | O | X |
| **.SPLAT** | O | O | O | O | X |
| **.SPZ** | O | X | X | X | X |
| **.KSPLAT** | O | X | X | O | X |
| **LoD 스트리밍** | O (v2) | X | X | X | O (Luma 클라우드) |
| **모바일** | O (WebGL2) | 제한적 | 기본 | O | O |
| **WebXR/VR** | O (v2 SparkXr) | X | X | X | O |
| **벤더 락인** | 없음 (MIT) | 없음 (MIT) | 없음 (MIT) | 없음 (MIT) | **있음** (Luma 캡처) |

## Spark v2 주요 신기능

- **LoD Splat Tree**: 뷰포인트/거리 기반 동적 스플랫 선택
- **`.RAD` 포맷**: 사전 계산된 LoD 트리, HTTP Range 요청으로 점진적 로딩
- **LRU 기반 스플랫 페이저**: 고정 GPU 메모리 풀로 수십억 스플랫 가능
- **XR 통합**: SparkXr 래퍼

## R3F 통합 패턴

```tsx
import { extend } from "@react-three/fiber";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";

extend({ SparkRenderer, SplatMesh });

<Canvas>
  <sparkRenderer />
  <splatMesh url="scene.spz" />
</Canvas>
```

> Vite 환경 필수 (WASM 로딩 이슈로 Webpack 비호환 또는 추가 설정 필요)

## 기존 PLY 뷰어와의 공존 방안

포맷 확장자에 따라 뷰어를 자동 전환:
- `.ply` (포인트 클라우드) -> 기존 Three.js Points 뷰어
- `.splat`, `.spz`, `.ksplat` -> Spark GaussianSplatViewer
- `.rad` (향후) -> Spark v2 LoD 스트리밍

## 번들 크기 영향

- `@sparkjsdev/spark`: ~150KB gzipped (WASM 포함)
- 기존 Three.js/R3F 번들에 추가되는 크기는 제한적
- WASM은 lazy load 가능

## 권장사항

**`@sparkjsdev/spark` v0.1.10 도입 권장**

| 이유 | 설명 |
|---|---|
| 포맷 호환성 | `.ply`, `.splat`, `.spz` 모두 지원 (EXTube 파이프라인 출력 호환) |
| R3F 네이티브 | 기존 React + Three.js 스택에 직접 통합 |
| GaussianSplats3D 후속 | 원 저자가 Spark 이전 권장 |
| 벤더 락인 없음 | MIT 오픈소스 |
| v2 마이그레이션 용이 | 파라미터 이름 변경 수준 |

### 구현 전략

| 단계 | 시기 | 접근법 |
|---|---|---|
| **단기** | 지금 | v0.1.10 (stable) 기반 GaussianSplatViewer 컴포넌트 생성 |
| **중기** | v2 안정화 시 | LoD 스트리밍 전환 (.RAD 포맷) |

`.spz` 포맷으로 압축 전달하여 크기/품질 균형을 맞춘다.
