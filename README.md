# EXTube

유튜브 영상에서 사진측량(photogrammetry) 기술을 활용해 영상 속 3차원 공간을 복원하는 서비스입니다.

## 개요

유튜브 URL을 입력하면 영상에서 프레임을 추출하고, Structure-from-Motion(SfM) 또는 3D Gaussian Splatting 기술로 3D 공간을 복원하여 웹 브라우저에서 탐색할 수 있습니다.

## 파이프라인

```
유튜브 URL → 영상 다운로드 → 프레임 추출 → 3D 복원 → 웹 3D 뷰어
             (yt-dlp)       (ffmpeg)     (COLMAP/3DGS)  (Three.js)
```

## 설치 및 실행

### Docker (CPU)

```bash
cd docker
docker compose up --build
```

### Docker (GPU)

NVIDIA GPU와 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)이 필요합니다.

```bash
cd docker
docker compose --profile gpu up --build app-gpu
```

GPU 모드에서는 COLMAP이 CUDA 가속으로 빌드되어 Dense MVS 등 GPU 의존 작업이 가능합니다.

### 로컬 개발

```bash
make dev        # 개발 의존성 포함 설치
make lint       # 린트
make test       # 테스트
```

## 업무 스킴

이 프로젝트는 [TeamWork](https://github.com/conaonda/TeamWork) 업무 스킴을 따릅니다.
스프린트 자동화 실행:
```bash
/path/to/TeamWork/scripts/sprint.sh --repo conaonda/EXTube --workdir ~/git --sprints 3
```
