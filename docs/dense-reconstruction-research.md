# Dense Reconstruction 및 3D Gaussian Splatting 기술 조사

> 이슈: #35
> 작성일: 2026-03-05
> 역할: agent/researcher

---

## 1. COLMAP Dense Reconstruction (MVS)

### 1.1 파이프라인 단계

| 단계 | 명령어 | 실행 환경 | 설명 |
|---|---|---|---|
| 1 | `image_undistorter` | CPU | 렌즈 왜곡 제거, MVS 워크스페이스 생성 |
| 2 | `patch_match_stereo` | **GPU (CUDA)** | PatchMatch MVS로 이미지별 depth/normal map 생성 |
| 3 | `stereo_fusion` | CPU/RAM | depth map 융합 → dense point cloud (`fused.ply`) |
| 4 | `poisson_mesher` (선택) | CPU | 포인트 클라우드 → 메시 변환 |

### 1.2 리소스 요구사항

| 항목 | 100 프레임 @ 1080p | 500 프레임 @ 1080p |
|---|---|---|
| GPU VRAM | 8 GB 최소 | 12–16 GB 권장 |
| RAM | 16 GB | 32–64 GB |
| 디스크 (중간 산출물) | 2–5 GB | 10–20 GB |
| `fused.ply` 크기 | 0.2–2 GB | 1–10 GB |
| 처리 시간 (RTX 3080급) | 30–90분 | 3–10시간 |

- `geom_consistency=true` 시 VRAM 약 2배 증가
- `stereo_fusion`의 `cache_size` 파라미터로 RAM 사용량 조절

### 1.3 Sparse vs Dense 비교

- Sparse: 5,000–200,000 포인트 (특징점 기반)
- Dense: 10M–500M 포인트 (픽셀 단위 밀도)
- Dense 품질은 Sparse(SfM) 품질에 종속됨

### 1.4 YouTube 영상 제한사항

| 문제 | 영향 | 완화 방법 |
|---|---|---|
| H.264/VP9 압축 아티팩트 | SIFT/NCC 정확도 저하 | 최고 비트레이트로 다운로드, 4K 선호 |
| 롤링 셔터 | 기하학적 왜곡 (COLMAP 미보정) | 느린 카메라 이동 구간만 사용 |
| 모션 블러 | 등록/depth 품질 저하 | Laplacian variance로 블러 프레임 필터링 |
| 자동 노출 | 광도 일관성 위반 | splatfacto-w 사용 또는 히스토그램 정규화 |
| 과다 프레임 | 좁은 기선, 중복 뷰 | 1–3 fps 추출, 각도 변화 10–15° 이상 확보 |

### 1.5 CUDA 요구사항

- 최소 Compute Capability: 3.5 (실질적 5.0+)
- CUDA Toolkit: 11.7+ (CUDA 12.x 완전 지원)
- RTX 50xx(sm_120): 빌드 필요 (프리빌트 미지원)

### 1.6 Docker 호환성

- `nvidia-container-toolkit` + Docker ≥ 19.03 필요
- `patch_match_stereo`는 headless GPU 실행 가능 (디스플레이 불필요)
- 주의: Docker 메모리 제한 상향 필수 (`--memory=64g`)
- CUDA 버전 호환성: 컨테이너 CUDA ≤ 호스트 드라이버 지원 버전

---

## 2. 3D Gaussian Splatting 구현체 비교

### 2.1 핵심 비교표

| 기준 | graphdeco-inria (원본) | nerfstudio (splatfacto) | gsplat | SuGaR |
|---|---|---|---|---|
| **라이선스** | ⚠️ Inria/MPII (비상업) | ✅ Apache 2.0 | ✅ Apache 2.0 | ⚠️ Inria/MPII (비상업) |
| **최소 VRAM** | 8 GB (권장 24 GB) | 8 GB | 6–8 GB (4x 효율적) | 24 GB |
| **COLMAP 필요** | 필수 | 내장 (ns-process-data) | 외부 SfM 필요 | 필수 |
| **학습 시간** (100–500장, RTX 3090) | 7–45분 | 20–40분 | 18–38분 | 1–3시간 |
| **출력 형식** | `.ply` | `.ply`, `.splat`, `.ply_compressed` | `.ply`, `.splat`, `.ply_compressed` | `.obj` 메시 |
| **Python 통합** | 낮음 (스크립트) | **높음** (pip, CLI, API) | **최고** (pip, 라이브러리) | 낮음 |
| **유지보수** | 학술 참조용 | ✅ 활발 | ✅ 활발 | 저조 |
| **YouTube 적합성** | 전처리 필요 | **최적** (splatfacto-w) | SfM 별도 | 부적합 |

### 2.2 라이선스 제약 (중요)

- **graphdeco-inria** 및 **SuGaR**: 비상업적 연구 전용. 상업적 사용 시 별도 라이선스 필요 → EXTube 서비스 적용 불가
- **nerfstudio** 및 **gsplat**: Apache 2.0 → 제약 없음

### 2.3 YouTube 전처리 권장사항

```
yt-dlp (1080p) → ffmpeg (2–5 fps) → 블러 필터링 → COLMAP/hloc → 3DGS 학습 → .ply 내보내기
```

- **해상도**: 1080p 최적 (4K는 비용 대비 효과 미미)
- **프레임 수**: 100–300장 목표
- **프레임 겹침**: 인접 프레임 70–80% 오버랩
- **동적 객체**: 마스킹 처리 필요

---

## 3. 웹 Gaussian Splatting 뷰어 비교

### 3.1 비교표

| 라이브러리 | 기술 | Three.js/R3F | 입력 형식 | 모바일 | 라이선스 | 유지보수 |
|---|---|---|---|---|---|---|
| antimatter15/splat | WebGL 1.0 | ❌ | `.ply`, `.splat` | 양호 | MIT | 최소 |
| playcanvas/supersplat | WebGL2+WebGPU | ❌ (PlayCanvas 전용) | `.ply`, `.splat`, `.sogs` | 우수 | MIT | 매우 활발 |
| mkkellogg/GaussianSplats3D | WebGL2/Three.js | 부분적 (문제 있음) | `.ply`, `.splat`, `.ksplat` | 보통 | MIT | **지원 종료** |
| **sparkjsdev/spark** | **WebGL2/Three.js** | **✅ 공식 R3F 지원** | **`.ply`, `.spz`, `.splat`, `.ksplat`, `.sog`** | **우수** | **MIT** | **매우 활발** |
| huggingface/gsplat.js | WebGL (자체 렌더러) | ❌ | `.ply`, `.splat` | 기본 | MIT | 저조 |
| lumaai/luma-web | WebGL/Three.js | ✅ | Luma 전용 | 양호 | 독점 | **아카이브됨** |

### 3.2 R3F 통합 예시 (Spark)

```tsx
import { Canvas } from '@react-three/fiber'
import { Splat } from '@sparkjsdev/spark/r3f'

export function SplatViewer({ url }: { url: string }) {
  return (
    <Canvas>
      <Splat src={url} />
    </Canvas>
  )
}
```

---

## 4. GPU 요구사항 종합

| 구성요소 | GPU 필요 | 최소 VRAM | 권장 VRAM | CUDA |
|---|---|---|---|---|
| COLMAP Sparse (SfM) | 선택 (CPU 가능) | - | 4 GB | - |
| COLMAP Dense (MVS) | **필수** | 8 GB | 16 GB | 11.7+ |
| 3DGS 학습 (gsplat) | **필수** | 6 GB | 12 GB | CC 7.0+ |
| 3DGS 학습 (nerfstudio) | **필수** | 8 GB | 16 GB | CC 7.0+ |
| 웹 뷰어 (Spark) | WebGL2 | - | - | - |

### Docker GPU 환경

```bash
# nvidia-container-toolkit 설치 후
docker run --gpus all \
    --memory=64g \
    --shm-size=16g \
    -v /local/data:/data \
    colmap/colmap:latest \
    colmap patch_match_stereo \
        --workspace_path /data/dense \
        --PatchMatchStereo.geom_consistency true
```

---

## 5. 권장 사항

### 5.1 추천 기술 스택

| 단계 | 추천 기술 | 근거 |
|---|---|---|
| Dense Reconstruction | COLMAP MVS | 검증된 파이프라인, Docker GPU 지원 |
| 3D Gaussian Splatting | **nerfstudio (splatfacto-w)** + gsplat 백엔드 | Apache 2.0, YouTube 적합, pip 설치, 비디오→3DGS 통합 파이프라인 |
| 웹 뷰어 | **sparkjsdev/spark** | Three.js/R3F 공식 지원, MIT, 활발한 유지보수, 최다 형식 지원 |

### 5.2 구현 로드맵 제안

1. **Phase 1**: COLMAP Dense 파이프라인 추가 (`src/reconstruction/`)
   - `image_undistorter` → `patch_match_stereo` → `stereo_fusion` 통합
   - GPU 메모리에 따른 `max_image_size` 자동 조절

2. **Phase 2**: 3D Gaussian Splatting 도입
   - nerfstudio + gsplat 설치 (Docker 이미지)
   - `splatfacto-w` 학습 파이프라인 통합
   - `.ply` / `.splat` 출력

3. **Phase 3**: 웹 뷰어 업그레이드
   - 기존 Three.js 뷰어에 `@sparkjsdev/spark` 통합
   - `.ply` → `.spz` 압축 파이프라인 추가 (전송 최적화)

4. **Phase 4**: 품질 최적화
   - 프레임 품질 필터링 (블러 감지, 중복 제거)
   - 동적 객체 마스킹
   - YouTube 해상도별 품질 벤치마크

### 5.3 최소 하드웨어 요구사항

- **개발/테스트**: RTX 3060 12GB, RAM 32GB, SSD 100GB
- **프로덕션 권장**: RTX 4080 16GB+, RAM 64GB, SSD 500GB

---

## 6. Sprint 12 업데이트 (2026-03-05)

### 6.1 최신 버전 및 변경사항

| 도구 | 최신 버전 | 주요 변경 |
|---|---|---|
| gsplat | **v1.5.3** (2026-01) | 배치 렌더링, Fused bilagrid (14.7% 빠른 학습, 26% VRAM 절감), F-Theta 카메라 지원 |
| nerfstudio (splatfacto-w) | 최신 dev | Transparency carving, opacity compensation 래스터화, NaN/Inf 처리 개선 |
| sparkjsdev/spark | **v2.0.0-preview** | Dynos 시스템(프로시저럴 스플랫), 메시+스플랫 퓨전 렌더링, WebXR 지원 |
| COLMAP | **3.14.0.dev0** (2026-02) | 여전히 SfM/MVS 표준 |

### 6.2 glTF 표준화 (2026-02, 신규)

**3D Gaussian Splat이 glTF 표준에 공식 추가됨** (Khronos Group):
- `KHR_gaussian_splatting`: 기본 확장
- `KHR_gaussian_splatting_compression_spz`: SPZ 압축 확장 (Release Candidate)
- Khronos, OGC, Niantic, Cesium, Esri 공동 작업

**EXTube 영향**: 향후 `.glb` 단일 파일로 3DGS + 메시 + 텍스처 통합 배포 가능

### 6.3 포맷 표준화 현황

| 포맷 | 상태 | 압축률 | 용도 |
|---|---|---|---|
| **SPZ** | 사실상 표준 | PLY 대비 90% 압축 (250MB→25MB) | 웹 전송, 압축 배포 |
| PLY | 레거시 표준 | 없음 | 아카이브, 최대 품질 |
| .splat | 확립됨 | 포맷별 | 웹 뷰어 호환 |
| **glTF + KHR** | 공식 표준 (신규) | SPZ 옵션 | 미래 호환, 산업 표준 |

### 6.4 COLMAP MVS vs OpenMVS 비교 (Sprint 12 추가 조사)

| 기준 | COLMAP MVS | OpenMVS |
|---|---|---|
| 정확도 | 양호 | **우수** (0.15mm 벤치마크) |
| 텍스처 품질 | 적절 | **우수** |
| 자동화 | **높음** | 중간 (설정 필요) |
| EXTube 통합 | **쉬움** (기존 COLMAP 파이프라인 확장) | 별도 설치/빌드 필요 |
| 대용량 데이터셋 | 메모리 제한 | **효율적** |

**결론**: Phase 1은 COLMAP MVS로 시작 (기존 파이프라인 확장 용이), 품질 요구 증가 시 OpenMVS 도입 검토

### 6.5 현재 코드에서 Dense 확장 구체적 단계

현재 `src/reconstruction/reconstruction.py`는 sparse 파이프라인만 구현:
`feature_extractor` → `exhaustive_matcher` → `sparse_reconstructor` → `export_to_ply`

**Dense 확장에 필요한 코드 변경**:

1. `_run_colmap()` 함수에 `image_undistorter`, `patch_match_stereo`, `stereo_fusion` 호출 추가
2. `ReconstructionResult`에 `dense_dir`, `dense_ply_path` 필드 추가
3. `reconstruct()` 함수에 `dense=False` 파라미터 추가
4. GPU VRAM 감지 로직 추가 (`max_image_size` 자동 조절)
5. API 엔드포인트에 dense 옵션 노출

### 6.6 업데이트된 권장사항

Sprint 11 권장사항을 유지하되, 다음을 추가:
- **출력 포맷**: SPZ를 기본 웹 배포 포맷으로 채택 (PLY 대비 90% 압축)
- **glTF 준비**: Spark v2.0이 glTF KHR 확장 지원 시 마이그레이션 계획
- **gsplat 1.5.3**: Fused bilagrid 옵션 활성화로 VRAM 절감 (6GB GPU에서도 학습 가능)

---

## 7. Sprint 13 최종 권고안 (2026-03-05)

### 7.1 최신 동향 업데이트

#### glTF KHR_gaussian_splatting 표준화 진행
- **2026 Q2 정식 비준 예정** (현재 Release Candidate)
- Nvidia, Google, Adobe, Cesium 등 주요 기업 지원
- glTF 2.0 mesh primitive를 확장하여 3DGS 데이터셋 표현
- 기존 glTF 툴링 파이프라인과 호환

#### gsplat 최신 기능
- **3DGUT** (3D Gaussian Unscented Transform) 네이티브 통합 — 더 정확한 렌더링
- **PPIPS** 통합 — bilateral grid 대안으로 학습 뷰 보정
- 배치 렌더링으로 다중 씬 동시 처리 가능

#### Spark 2.0
- **Streaming LoD** (Level of Detail) — 대규모 씬 스트리밍 렌더링
- 메시+스플랫 퓨전 렌더링 안정화
- 98%+ 디바이스 WebGL2 호환성

### 7.2 최종 기술 스택 결정

| 구성요소 | 선택 | 대안 (향후 검토) |
|---|---|---|
| Dense Reconstruction | **COLMAP MVS** | OpenMVS (품질 요구 증가 시) |
| 3D Gaussian Splatting | **nerfstudio (splatfacto-w) + gsplat** | — |
| 웹 뷰어 | **sparkjsdev/spark v2** (R3F) | — |
| 배포 포맷 | **SPZ** (웹), PLY (아카이브) | glTF + KHR (Q2 비준 후) |
| Docker GPU | **nvidia-container-toolkit** | — |

### 7.3 최종 결정 근거

1. **COLMAP MVS**: 기존 sparse 파이프라인에서 3개 명령어 추가로 확장 가능. 별도 설치 불필요.
2. **nerfstudio + gsplat**: Apache 2.0 라이선스, `splatfacto-w`가 YouTube 자동노출/조명 변화에 특화, pip 설치로 Python 통합 용이.
3. **Spark v2**: 유일한 Three.js/R3F 공식 지원 3DGS 렌더러. MIT 라이선스. SPZ/PLY/splat 등 모든 주요 포맷 지원.
4. **SPZ 포맷**: Niantic 오픈소스(MIT), glTF KHR 확장에 채택, PLY 대비 90% 압축. 웹 전송 최적.

### 7.4 구현 우선순위 (확정)

| 순서 | 작업 | 의존성 | 예상 이슈 |
|---|---|---|---|
| 1 | COLMAP Dense (MVS) 파이프라인 추가 | 없음 (기존 sparse 확장) | `feat(reconstruction): COLMAP Dense 파이프라인` |
| 2 | GPU Docker 이미지 구성 | Phase 1 | `chore(docker): GPU 지원 Docker 이미지` |
| 3 | nerfstudio + gsplat 3DGS 학습 통합 | Phase 1, 2 | `feat(reconstruction): 3DGS 학습 파이프라인` |
| 4 | Spark v2 기반 GS 뷰어 | Phase 3 | `feat(viewer): Gaussian Splatting 뷰어` |
| 5 | 품질 최적화 (블러 필터, 마스킹) | Phase 1–4 | `feat(extractor): 프레임 품질 필터링` |

### 7.5 리스크 및 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| GPU VRAM 부족 (< 8GB) | Dense/3DGS 불가 | `max_image_size` 자동 조절, gsplat fused bilagrid (6GB 가능) |
| YouTube 영상 품질 저하 | 복원 실패 | 블러 필터링, 최소 해상도 720p 강제, 프레임 수 100–300장 제한 |
| glTF 표준 변경 | 포맷 마이그레이션 | SPZ 기본 채택 (이미 KHR 확장에 포함), 전환 비용 최소 |
| nerfstudio API 변경 | 통합 깨짐 | 특정 버전 고정 (pip freeze), CI 테스트 |
