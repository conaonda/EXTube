# EXTube

유튜브 영상에서 사진측량(photogrammetry) 기술을 활용해 영상 속 3차원 공간을 복원하는 서비스입니다.

## 개요

유튜브 URL을 입력하면 영상에서 프레임을 추출하고, Structure-from-Motion(SfM) 또는 3D Gaussian Splatting 기술로 3D 공간을 복원하여 웹 브라우저에서 탐색할 수 있습니다.

## 파이프라인

```
유튜브 URL → 영상 다운로드 → 프레임 추출 → 3D 복원 → 웹 3D 뷰어
             (yt-dlp)       (ffmpeg)     (COLMAP/3DGS)  (Three.js)
```

### 실시간 진행률 알림

작업 처리 중 WebSocket을 통해 5단계 진행률을 실시간으로 전달합니다.

| 단계 | 설명 |
|------|------|
| `download` | 유튜브 영상 다운로드 |
| `extraction` | 프레임 추출 |
| `feature_matching` | COLMAP 특징점 추출 및 매칭 |
| `reconstruction` | Sparse 3D 복원 |
| `export` | PLY/Splat 결과 내보내기 |

프론트엔드 `JobStatus` 컴포넌트는 프로그레스 바와 단계 인디케이터로 진행 상황을 표시합니다.

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

## 로컬 개발 환경 설정

### 시스템 의존성

| 도구 | 버전 | 용도 |
|------|------|------|
| Python | >= 3.11 | 백엔드 |
| Node.js | >= 20 | 프론트엔드 |
| ffmpeg | - | 프레임 추출 |
| COLMAP | - | 3D 복원 (SfM) |
| Redis | >= 7 | 작업 큐 |

```bash
# Ubuntu/Debian
sudo apt-get install -y ffmpeg colmap redis-server

# macOS (Homebrew)
brew install ffmpeg colmap redis
```

### 백엔드 설정

```bash
# 환경변수
cp .env.example .env
# .env에서 EXTUBE_JWT_SECRET_KEY를 변경하세요

# Python 의존성 (개발 모드)
make dev

# Redis 실행
redis-server &

# API 서버 실행
uvicorn src.api.main:app --reload --port 8000
```

### 프론트엔드 설정

```bash
cd src/viewer
npm install
npm run dev      # Vite 개발 서버 (localhost:5173)
```

### 주요 Make 명령어

| 명령어 | 설명 |
|--------|------|
| `make dev` | 개발 의존성 포함 설치 |
| `make lint` | Python (ruff) + TypeScript (eslint) 린트 |
| `make format` | 자동 포맷팅 |
| `make test` | 백엔드 테스트 (pytest) |

프론트엔드 테스트는 별도로 실행합니다:
```bash
cd src/viewer && npm test
```

### Docker 개발 환경

Docker Compose로 Redis와 앱을 한 번에 실행할 수 있습니다:

```bash
cd docker
docker compose up --build    # app + redis + rq-worker
```

GPU 모드가 필요한 경우:
```bash
docker compose --profile gpu up --build
```

## 샘플 갤러리

**온라인 데모:** https://conaonda.github.io/EXTube/gallery

`/gallery` 페이지에서 로그인 없이 사전 복원된 3D 결과물을 탐색할 수 있습니다.

- 카드 클릭 시 기존 3D 뷰어(ViewerCanvas)로 전환
- PLY(포인트 클라우드), Splat(Gaussian Splatting) 포맷 지원
- 모바일 반응형 그리드 레이아웃 (640px 이하 단일 컬럼)

샘플 데이터는 `src/viewer/src/sampleGallery.ts`에서 설정합니다. `SampleItem` 인터페이스:

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `string` | 고유 식별자 |
| `title` | `string` | 표시 제목 |
| `description` | `string` | 설명 |
| `thumbnail` | `string` | 썸네일 이미지 경로 |
| `type` | `'ply' \| 'potree' \| 'splat'` | 3D 데이터 포맷 |
| `dataUrl` | `string` | 3D 데이터 파일 경로 |

샘플 파일은 `public/samples/<name>/` 디렉토리에 배치합니다.

## 업무 스킴

이 프로젝트는 [TeamWork](https://github.com/conaonda/TeamWork) 업무 스킴을 따릅니다.
스프린트 자동화 실행:
```bash
/path/to/TeamWork/scripts/sprint.sh --repo conaonda/EXTube --workdir ~/git --sprints 3
```
