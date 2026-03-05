# EXTube

유튜브 영상에서 사진측량(photogrammetry) 기술을 활용해 영상 속 3차원 공간을 복원하는 서비스입니다.

## 개요

유튜브 URL을 입력하면 영상에서 프레임을 추출하고, Structure-from-Motion(SfM) 또는 3D Gaussian Splatting 기술로 3D 공간을 복원하여 웹 브라우저에서 탐색할 수 있습니다.

## 파이프라인

```
유튜브 URL → 영상 다운로드 → 프레임 추출 → 3D 복원 → 웹 3D 뷰어
             (yt-dlp)       (ffmpeg)     (COLMAP/3DGS)  (Three.js)
```

## Quick Start

### 1. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 EXTUBE_JWT_SECRET_KEY 등을 변경하세요
```

### 2. Docker로 실행 (개발)

```bash
cd docker
docker compose up --build
```

### 3. Docker로 실행 (프로덕션)

```bash
cp docker/.env.example docker/.env
# docker/.env에서 REDIS_PASSWORD, DOMAIN 설정

./scripts/deploy.sh          # CPU 모드
./scripts/deploy.sh --gpu    # GPU 모드
```

### 4. GPU 모드

NVIDIA GPU와 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)이 필요합니다.
GPU 모드에서는 COLMAP이 CUDA 가속으로 빌드되어 Dense MVS 등 GPU 의존 작업이 가능합니다.

### 로컬 개발

```bash
make dev        # 개발 의존성 포함 설치
make lint       # 린트
make test       # 테스트
```

자세한 배포 가이드는 [docs/deployment.md](docs/deployment.md)를 참고하세요.

## 업무 스킴

이 프로젝트는 [TeamWork](https://github.com/conaonda/TeamWork) 업무 스킴을 따릅니다.
스프린트 자동화 실행:
```bash
/path/to/TeamWork/scripts/sprint.sh --repo conaonda/EXTube --workdir ~/git --sprints 3
```
