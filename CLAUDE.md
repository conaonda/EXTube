# EXTube — 프로젝트 지침

## 프로젝트 개요
유튜브 영상에서 사진측량(photogrammetry) 기술을 활용해 영상 속 3차원 공간을 복원하는 서비스.

### 핵심 파이프라인
```
유튜브 URL → 영상 다운로드 → 프레임 추출 → SfM/3D 복원 → 웹 3D 뷰어
```

## 기술 스택 (초기 — 리서치 후 확정)
- 영상 다운로드: yt-dlp
- 프레임 추출: ffmpeg
- 3D 복원: COLMAP / 3D Gaussian Splatting (조사 후 결정)
- 백엔드: Python (FastAPI)
- 프론트엔드: React + Three.js (또는 Gaussian Splatting Viewer)
- 인프라: Docker

## 디렉토리 구조
```
├── src/
│   ├── downloader/     # 유튜브 영상 다운로드
│   ├── extractor/      # 프레임 추출
│   ├── reconstruction/ # 3D 복원 파이프라인
│   ├── api/            # FastAPI 백엔드
│   └── viewer/         # 웹 3D 뷰어
├── tests/
├── docs/
├── docker/
├── CLAUDE.md
└── README.md
```

## 컨벤션

### 커밋
Conventional Commits: `<type>(<scope>): <subject>`
- type: feat, fix, docs, style, refactor, test, chore
- scope: downloader, extractor, reconstruction, api, viewer
- subject: 50자 이내, 명령형, 소문자 시작, 마침표 없음

### 브랜치
- `main` — 프로덕션
- `develop` — 개발 통합
- `feature/이슈번호-설명`, `fix/이슈번호-설명`, `hotfix/이슈번호-설명`
- develop에서 분기, PR로만 머지

### 코드 스타일
- Python: ruff (린트/포맷)
- TypeScript: eslint + prettier
- 린트: `make lint`
- 테스트: `make test`

## 에이전트 행동 규칙

### 필수
- 모든 작업은 GitHub 이슈에서 시작한다
- 이슈 번호를 브랜치명과 커밋에 포함한다
- PR 생성 시 `closes #이슈번호`로 연결한다
- 변경 전 기존 코드를 먼저 읽고 이해한다
- 테스트가 통과하는 코드만 PR로 제출한다

### 금지
- main/develop에 직접 push 금지
- 기존 테스트를 삭제하거나 무력화 금지
- 보안 취약점이 있는 코드 커밋 금지
- `--no-verify`, `--force` 플래그 사용 금지
- API 키, 시크릿 등 민감 정보 커밋 금지

### 업무 스킴
이 프로젝트는 [TeamWork](https://github.com/conaonda/TeamWork) 업무 스킴을 따른다.
에이전트 역할(Orchestrator, Developer, Reviewer, Tester, Researcher)과 워크플로우는 TeamWork 저장소를 참조한다.
