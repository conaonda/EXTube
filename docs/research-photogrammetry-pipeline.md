# 사진측량 파이프라인 기술 스택 비교

> 조사 기준일: 2026-03-05
> 관련 이슈: #1

## 비교 표

| 항목 | COLMAP (SfM+MVS) | 3D Gaussian Splatting (3DGS) | CF-3DGS (COLMAP-Free 3DGS) | Nerfstudio |
|------|-----------------|------------------------------|----------------------------|------------|
| **입력 요구사항** | 카메라 포즈 불필요 (자동 추정) | 카메라 포즈 필요 (COLMAP 전처리 필수) | 카메라 포즈 불필요 (자동 추정) | COLMAP 전처리 필요 (일부 메서드) |
| **복원 품질** | 고품질 포인트 클라우드/메시 | 최고 수준 포토리얼리스틱 렌더링 | 3DGS 대비 소폭 낮음 | 메서드에 따라 다름 (Splatfacto ≈ 3DGS) |
| **처리 속도** | 느림 (SfM: 수 분~수 시간) | 빠름 (학습 ~30분~1.5시간) | 빠름 (학습 ~1.5시간) | 메서드에 따라 다름 |
| **GPU 요구사항** | CUDA GPU (CPU도 가능) | NVIDIA 24GB VRAM 권장 (RTX 3090+) | NVIDIA 24GB VRAM 권장 | RTX 2060 이상, 24GB 권장 |
| **웹 뷰어 호환성** | 별도 변환 필요 (PLY → Three.js) | WebGL/WebGPU 뷰어 다수 존재 | 3DGS 포맷 → 동일 뷰어 활용 | 내장 웹 뷰어, PLY/메시 내보내기 |
| **라이선스** | BSD (상업적 이용 가능) | INRIA 비상업적 라이선스 | NVIDIA 비상업적 라이선스 | Apache 2.0 (상업적 이용 가능) |

## 권장 스택: COLMAP + Nerfstudio (Splatfacto)

```
유튜브 URL → yt-dlp → ffmpeg 프레임 추출 → COLMAP (SfM 포즈 추정) → Nerfstudio Splatfacto (3DGS 학습) → PLY 내보내기 → WebGL 뷰어
```

### 선택 근거

| 고려사항 | 이유 |
|---------|------|
| **라이선스** | COLMAP(BSD) + Nerfstudio(Apache 2.0) = 상업적 이용 가능 |
| **카메라 포즈** | 유튜브 영상은 카메라 파라미터 불명 → COLMAP SfM 자동 추정 |
| **복원 품질** | Splatfacto는 INRIA 3DGS 수준의 포토리얼리스틱 품질 |
| **웹 뷰어** | 3DGS 출력(PLY)은 WebGL 뷰어와 직접 연동 가능 |
| **생태계** | COLMAP은 검증된 도구, Nerfstudio는 활발한 커뮤니티 |

### CF-3DGS 보류 이유

카메라 포즈 없이 동작하지만 NVIDIA 비상업적 라이선스 제약. 오픈 라이선스 대안 성숙 시 재검토.

### 추가 검토 사항

- GPU 최소 사양: NVIDIA RTX 3090 (24GB VRAM) — 클라우드 GPU 활용 권장
- 유튜브 영상 품질: 최소 1080p, 30fps 이상 권장
- WebGPU: 크로스 플랫폼 호환성 향상 중

## 참고 자료

- [COLMAP 공식 문서](https://colmap.github.io/)
- [3DGS 논문 (SIGGRAPH 2023)](https://arxiv.org/abs/2308.04079)
- [CF-3DGS (CVPR 2024)](https://oasisyang.github.io/colmap-free-3dgs/)
- [Nerfstudio 공식 문서](https://docs.nerf.studio/)
- [GaussianSplats3D 웹 뷰어](https://github.com/mkkellogg/GaussianSplats3D)
