# 웹 기반 3D 뷰어 기술 비교

> 조사 기준일: 2026-03-05
> 관련 이슈: #3

## 비교 표

| 항목 | Three.js | Spark (sparkjsdev) | GaussianSplats3D | antimatter15/splat | Potree | model-viewer |
|------|----------|---------------------|------------------|-------------------|--------|-------------|
| **Gaussian Splat 지원** | 플러그인 필요 | 네이티브 (핵심 기능) | 네이티브 | 네이티브 | 미지원 | 미지원 |
| **지원 포맷** | PLY, glTF, OBJ 등 다수 | PLY, SPZ, SPLAT, KSPLAT, SOG, RAD | PLY, SPLAT, KSPLAT | PLY → SPLAT 변환 | LAS, LAZ | glTF, GLB |
| **렌더링 성능** | 중간 | 높음 (GPU 소팅, LoD) | 중간-높음 | 낮음 (CPU 소팅) | 매우 높음 (octree) | 낮음-중간 |
| **모바일 호환성** | 중간 | 중간 (동적 해상도) | 중간 | 낮음 | 낮음-중간 | 높음 (AR 포함) |
| **커스터마이징** | 매우 높음 | 높음 (Dynos 시스템) | 중간 | 낮음 | 낮음 | 낮음 |
| **Three.js 통합** | N/A | 완전 통합 | 완전 통합 | 독립적 | 별도 필요 | 독립적 |
| **2D Gaussian Splatting** | 미지원 | 미확인 | 지원 | 미지원 | 미지원 | 미지원 |
| **라이선스** | MIT | MIT | MIT | MIT | BSD | Apache 2.0 |

## 각 기술 상세

### Three.js

범용 WebGL/WebGPU 3D 렌더링 프레임워크. 포맷 지원과 커뮤니티 규모 최대. Gaussian Splatting은 코어에 포함되지 않으며 서드파티 라이브러리로 지원한다. 다른 뷰어 라이브러리의 기반 프레임워크 역할.

### Spark (sparkjsdev)

World Labs 개발. Three.js 위에 구축된 전용 Gaussian Splatting 렌더러.

- **v2.0**: LoD 스트리밍, GPU 소팅, Stochastic rendering, `.RAD` 포맷 지원
- Dynos 시스템으로 GLSL 셰이더 수준 커스터마이징 가능
- 현존 주요 Gaussian Splatting 포맷 모두 지원
- MIT 라이선스

### GaussianSplats3D (mkkellogg)

Three.js 완전 통합, 안정적 유지보수. 학술 연구 baseline으로 채택.

- 2D Gaussian Splatting 씬 지원 추가 (`SplatRenderMode.TwoD`)
- PLY 인메모리 압축 수준 설정 가능
- Spark 대비 기능 범위 제한적이나 안정성 우수

### antimatter15/splat

순수 WebGL 1.0 구현. CPU 기반 소팅으로 성능 한계. 유지보수 사실상 중단. 학습/참고용으로만 적합.

### Potree

수십억 포인트 처리 가능한 대규모 포인트 클라우드 뷰어. Gaussian Splatting 미지원. 영상 기반 SfM/3DGS 출력물에 부적합.

### model-viewer (Google)

HTML 태그 하나로 3D 모델 임베드. AR 지원. Gaussian Splatting 및 포인트 클라우드 미지원.

## glTF Gaussian Splatting 표준화 동향

2026년 2월, Khronos Group이 `KHR_gaussian_splatting` glTF 확장 릴리스 후보를 발표했다.

- glTF 2.0에 Gaussian Splat을 포인트 프리미티브로 저장 (위치, 회전, 스케일, 투명도, SH 계수)
- `KHR_gaussian_splatting_compression_spz`: SPZ 포맷으로 PLY 대비 최대 90% 압축
- Khronos, OGC, Niantic Spatial, Cesium, Esri 등 공동 참여
- Spark가 SPZ 포맷을 이미 지원하여 표준 수혜 예상

## 권장: Three.js + Spark 조합

```
React 앱 (@react-three/fiber)
  └─ Three.js (씬 관리, 카메라, UI)
       └─ Spark (Gaussian Splatting 렌더링)
       └─ PLYLoader (포인트 클라우드 폴백)
```

### 선택 근거

| 고려사항 | 이유 |
|---------|------|
| **파이프라인 호환성** | COLMAP/Nerfstudio 출력(PLY)을 Spark가 직접 로드 |
| **성능** | GPU 기반 소팅과 LoD 스트리밍으로 대규모 씬 안정 렌더링 |
| **표준 호환** | KHR_gaussian_splatting glTF 확장 + SPZ 압축 지원 |
| **React 통합** | React Three Fiber로 선언형 씬 구성 가능 |
| **커스터마이징** | Dynos 시스템으로 셰이더 수준 커스터마이징 |

### 대안 (2순위): GaussianSplats3D

Spark가 불안정하거나 요구사항이 단순한 경우의 폴백. 안정성 우수, 2D Gaussian Splatting 지원.

### 제외 대상

| 기술 | 제외 이유 |
|------|-----------|
| antimatter15/splat | 프로덕션 부적합, CPU 소팅 성능 한계, 유지보수 중단 |
| Potree | Gaussian Splatting 미지원, 변환 복잡 |
| model-viewer | Gaussian Splatting·포인트 클라우드 미지원 |

## COLMAP 출력 포맷과 뷰어 호환성

### COLMAP 출력 파일

| 단계 | 출력 파일 | 설명 |
|------|----------|------|
| Sparse | `cameras.bin` | 카메라 내부 파라미터 (초점거리, 주점, 왜곡) |
| Sparse | `images.bin` | 카메라 외부 파라미터 (자세/위치) |
| Sparse | `points3D.bin` | Sparse 3D 포인트 클라우드 |
| Export | `points.ply` | `model_converter`로 변환한 PLY 포인트 클라우드 |

현재 파이프라인(`src/reconstruction/reconstruction.py`)은 Sparse 복원 후 `model_converter`로 PLY 내보내기까지 수행한다.

### 뷰어별 COLMAP 호환성

| 뷰어 | PLY 직접 로드 | 추가 변환 필요 | 비고 |
|------|-------------|--------------|------|
| **Spark** | ✅ | SPZ 변환 시 90% 압축 가능 | PLY, SPZ, SPLAT, KSPLAT, SOG, RAD 모두 지원 |
| **GaussianSplats3D** | ✅ | 없음 | PLY 인메모리 압축 수준 설정 가능 |
| **Three.js PLYLoader** | ✅ | 없음 | 포인트 클라우드로 렌더링 |

**결론**: 현재 파이프라인의 `points.ply` 출력을 Spark/GaussianSplats3D가 추가 변환 없이 직접 로드할 수 있다.

## 모바일/저사양 환경 성능 벤치마크

### 데스크톱 기준선

- RTX 3080Ti: 6.1M splats → 147 FPS
- RTX 3070급: 30~100 FPS (씬 크기에 따라)

### 모바일 최적화 전략

| 항목 | Spark 2.0 | GaussianSplats3D |
|------|-----------|------------------|
| **LoD 시스템** | ✅ LoD Splat Tree (디바이스별 500K~2.5M splat 캡) | ❌ |
| **GPU 소팅** | 기본 활성화 | 데스크톱만 기본 활성화, 모바일은 비활성 |
| **동적 해상도** | 디바이스 성능에 맞춰 자동 조절 | 수동 설정 |
| **스트리밍** | HTTP Range request 기반 청크 로딩 (.RAD 포맷) | 전체 파일 로드 |
| **WASM 최적화** | 해당 없음 | SIMD WebAssembly 소팅, 정수 기반 거리 계산 |

**모바일 요약**: 공개된 정량적 FPS 수치는 제한적이나, Spark는 LoD 캡으로 프레임 수 보장, GaussianSplats3D는 WASM 소팅으로 모바일 대응. 대규모 씬에서는 Spark의 LoD 스트리밍이 유리하다.

### 2D Gaussian Splatting 성능 특성

GaussianSplats3D의 `SplatRenderMode.TwoD` 모드:
- 3D 볼륨을 2D 평면 디스크로 압축 → 깊이 계산 불필요
- 더 적은 Gaussian으로 동일 품질 달성 가능 (저장 효율적)
- GPU 래스터라이제이션 + 알파 블렌딩 네이티브 최적화
- 3DGS 대비 렌더링 속도 향상, 기하학적 일관성 우수

## 참고 자료

- [Spark 공식 문서](https://sparkjs.dev/docs/overview/)
- [Spark GitHub](https://github.com/sparkjsdev/spark)
- [GaussianSplats3D GitHub](https://github.com/mkkellogg/GaussianSplats3D)
- [Three.js 공식](https://threejs.org/)
- [Khronos glTF Gaussian Splatting 발표](https://www.khronos.org/news/press/gltf-gaussian-splatting-press-release)
- [KHR_gaussian_splatting 블로그](https://www.khronos.org/blog/khronos-ogc-and-geospatial-leaders-add-3d-gaussian-splats-to-the-gltf-asset-standard)
