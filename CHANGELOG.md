# Changelog

모든 주요 변경사항은 이 파일에 기록됩니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/)를 따르며,
버전 관리는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

---

## [Unreleased]

### Fixed
- **fix(reconstruction):** COLMAP 재시도 시 원본 예외 traceback 체인 보존 (#300, PR #304)
  - `raise last_error` → `raise last_error from exc`로 변경하여 원본 `__cause__` 보존
  - 디버깅 시 실제 원인 예외를 traceback에서 확인 가능
- **fix(reconstruction):** Dense reconstruction 실패 시 워크스페이스 정리 범위 확장 (#301, PR #304)
  - Dense 단계 `RuntimeError` 발생 시 `_cleanup_workspace` 호출 추가
  - Sparse 단계와 동일한 수준의 tmp 파일 정리 보장

### Added
- **feat(api):** WebSocket 재연결 및 작업 상태 복구 메커니즘 구현 (#292, PR #293)
  - `JobProgressManager`에 이벤트 히스토리(시퀀스 번호, 타임스탬프) 추가
  - 재연결 시 `last_seq` 기반 누락 이벤트 재전송
  - 클라이언트 Exponential backoff 재연결 (1s → 2s → 4s ... 최대 30s)
  - `useSyncExternalStore` 기반 연결 상태 관리, 연결 상태 UI 표시
- **feat(api):** `/health/live` 경량 liveness probe 엔드포인트 추가 (#272, PR #281)
  - 기존 `/health`는 하위 호환 유지
  - Docker Compose healthcheck를 `/health/live` 사용으로 업데이트
  - Prometheus instrumentation에서 `/health/live` 제외
- **chore(ci):** CD 파이프라인 — GHCR Docker 이미지 자동 빌드/푸시 (#271, PR #280)
  - `main` 브랜치 push 시 Docker 이미지를 GHCR에 자동 배포
  - 태그 릴리스 시 semver 기반 이미지 태그 자동 생성 (`v1.2.3`, `1.2`)
  - GitHub Actions build cache(`type=gha`)로 빌드 시간 최적화
- **chore(docker):** 프로덕션 배포 사전 검증 스크립트 구현 (#283, PR #285)
  - `scripts/validate-prod-config.sh`: .env, JWT secret, Redis 비밀번호, 도메인, Docker, GPU 툴킷, SSL 인증서 7개 항목 자동 검증
  - `scripts/deploy.sh` 연동 — 검증 실패 시 배포 중단

### Fixed
- **fix(docker):** Prometheus `HighErrorRate` 알림 규칙 expr 버그 수정 (#284, PR #288)
  - `sum()` 누락으로 `status` 레이블별 분리 계산되던 문제 해결
  - `sum(rate(...))` / `sum(rate(...))` 형태로 수정하여 전체 요청 대비 올바른 에러율 계산

### Tests
- **test(viewer):** 3D 뷰어 E2E 테스트 커버리지 강화 (#291, PR #294)
  - 카메라 인터랙션(회전/줌/패닝), 에러 핸들링(404/500/네트워크 오류), 작업 플로우(취소/완료) 테스트 추가
  - E2E 테스트 17개 → 25개 (+8개)
- **test(docker):** Prometheus 알림 규칙 promtool 단위 테스트 8개 추가 (#284, PR #288)
  - 4개 알림 규칙 × 발생/미발생 시나리오 검증
  - CI에 `prometheus-rules` job 추가 (lint + unit test)

### Documentation
- **docs(docker):** `docs/monitoring.md` 운영 가이드 보강 (#284, PR #288)
  - 알림 대응 절차, Alertmanager 설정 예시 추가

### Known Issues
- **fix(api):** ZIP 번들 다운로드(`GET /api/jobs/{job_id}/download-zip`)가 전체 ZIP을 메모리에 적재하는 구조로 대용량 결과물에서 OOM 위험 (#286)

---

## [0.46.0] - 2026-03-07

### Sprint 27

### Added
- **feat(api):** Job 결과물 ZIP 번들 다운로드 엔드포인트 추가 (#273, PR #277)
  - `GET /api/jobs/{job_id}/download-zip` — 복원 결과 전체를 ZIP으로 다운로드
  - 파일 크기 2GB 제한, 인증 및 소유권 검증 포함
- **test(api):** 인증 플로우 및 Job 생명주기 통합 테스트 강화 (#274, PR #278)
  - 회원가입 → 로그인 → Job 생성 → 완료 전체 플로우 검증
  - 실패 Job 재시도, 토큰 만료/갱신, max_jobs_per_user 한도 검증
  - 동적 rate limit 읽기(`_get_rate_limit()`)로 하드코딩 제거

### Fixed
- **fix(viewer):** App.tsx의 사용하지 않는 eslint-disable 디렉티브 제거 (#267, PR #269)

### Changed
- **chore(docker):** 프로덕션 Dockerfile 멀티스테이지 빌드 적용 (#268, PR #270)
  - 프론트엔드 빌드 스테이지 분리 (node:20-alpine)
  - 개발 의존성 제외한 최소 런타임 이미지 생성
  - `.dockerignore`에 `.claude/`, `node_modules/`, `dist/` 추가

---

## [0.45.0] - 2026-03-07

### Sprint 26

### Added
- **feat(api):** 파이프라인 단계별 진행률 WebSocket 알림 개선 (#248, PR #253)
  - `progress_callback` 파라미터로 5단계 세분화 진행률 실시간 WebSocket 전송
  - 프론트엔드 프로그레스 바 + 5단계 인디케이터 UI
- **feat(viewer):** GitHub Pages 온라인 데모 자동 배포 설정 (#227, PR #245)
  - `deploy-pages.yml` 워크플로우 추가
- **test(viewer):** 갤러리 페이지 Playwright E2E 테스트 추가 (#247, PR #255)
  - 갤러리 렌더링 / 뷰어 전환 / 에러 UI 12케이스

### Fixed
- **fix(ci):** backend job에 `pull-requests: write` 권한 추가 (#257, PR #261)
  - `orgoro/coverage` 액션의 PR 코멘트 권한 오류 해결

### Documentation
- **chore(docs):** CHANGELOG.md에 v0.42.0~v0.44.0 릴리스 내역 추가 (#259, PR #262)

---

## [0.44.0] - 2026-03-06

### Sprint 25

### Added
- **feat(api):** 파이프라인 단계별 진행률 WebSocket 알림 개선 (#248)
  - `progress_callback` 파라미터, 5단계 세분화, 실시간 WebSocket 전송
  - 프론트엔드 프로그레스 바 + 5단계 인디케이터 UI
- **test(viewer):** 갤러리 Playwright E2E 테스트 4건 (#247)

### Known Issues
- CI `orgoro/coverage` 액션 권한 오류 (#257)

---

## [0.43.0] - 2026-03-06

### Sprint 24 (추가)

### Added
- **docs(viewer):** `Viewer3DErrorBoundary` / `GalleryPage` JSDoc 추가 (#243)
- **docs(viewer):** README 온라인 데모 URL 추가 (#227)

### Fixed
- **fix(api):** `src/api/db.py`, `tests/test_api.py` git 충돌 마커 제거 — CI lint 수정 (#251)

---

## [0.42.0] - 2026-03-06

### Sprint 24

### Added
- **feat(viewer):** 갤러리 페이지 — 사전 복원 샘플 3D 뷰어 갤러리 (#239, #240)
- **feat(viewer):** 온라인 데모 — GitHub Pages 자동 배포 설정 (#227, #245)

### Fixed
- **fix(viewer):** 갤러리 에러 UI — 3D 데이터 로드 실패 시 에러 바운더리 + 샘플 PLY 추가 (#243, #244)

---

## [0.41.0] - 2026-03-07

### Sprint 20-22

### Fixed
- **fix(api):** Job 생성 파라미터 입력 검증 강화 (#225, PR #235)
  - `frame_interval`: 0.1~300초 범위 제한 (Pydantic `ge`/`le`)
  - `blur_threshold`: 0~500 범위 제한
  - `camera_model`: COLMAP 지원 10개 모델 화이트리스트 검증 (`field_validator`)
  - `gs_max_iterations`: 1~100,000 범위 제한
  - 잘못된 파라미터에 즉각 422 응답으로 파이프라인 실패 사전 차단
- **fix(reconstruction):** 파이프라인 견고성 개선 (#226, PR #234)
  - 블러 필터링 후 프레임 2장 미만 시 조기 실패 및 사용자 안내 메시지
  - Sparse reconstruction 후 `num_points3d == 0`이면 즉시 실패 처리
  - `subprocess.TimeoutExpired`를 사용자 친화적 `RuntimeError`로 변환
- **fix(ci):** test_rate_limit.py E501 및 Toast.tsx TS2554 수정 (#232, PR #233)

---

## [0.40.0] - 2026-03-06

### Sprint 19

### Added
- **feat(viewer):** Job 취소 API 연결 및 프론트엔드 완성 (#218, PR #220)
  - `cancelJob()` API 함수 추가
  - JobStatus에 취소 버튼 (pending/processing/retrying 상태)
  - WebSocket `cancelled` 상태 처리
  - JobHistory에 `cancelled`/`retrying` 필터·색상·라벨

### Fixed
- **fix(ci):** backend lint 에러 및 vitest e2e 수집 문제 해결 (#221, #222, PR #229)

### Sprint 18

### Added
- **feat(api):** 로그인 실패 추적을 Redis 기반으로 전환 (#212, PR #217)
  - 기존 메모리 기반 → Redis 기반으로 전환
  - 분산 환경에서도 로그인 잠금 기능 정상 동작

### Fixed
- **fix(api):** 파이프라인 재시도 시 원래 파라미터 복원 (#214, PR #215)
  - 재시도 시 잘못된 파라미터가 사용되던 버그 수정

---

## [0.39.0] - 2026-03-06

### Sprint 17

### Added
- **test:** Docker Compose 기반 통합 테스트 환경 구축 (#208, PR #210)
  - 10개 통합 테스트, `make test-integration` 타겟

### Changed
- **chore(api):** 리뷰 피드백 후속 개선 (#206, PR #209)
  - `assert` → `RuntimeError` 전환
  - `get_output_base_dir()` 함수화
  - `data-testid` 셀렉터 추가

---

## [0.38.0] - 2026-03-06

### Sprint 16

### Added
- **feat(api):** Job 목록 페이지네이션 및 정렬 기능 추가 (#196, PR #198)
  - `GET /api/jobs`에 `page`, `per_page`, `sort_by`, `order` 파라미터 추가
  - Viewer에 정렬 UI 추가

### Fixed
- **fix(api):** 프로덕션 보안 하드닝 (#202)
  - JWT 시크릿 강화, 비밀번호 정책, CORS 설정, 로그인 잠금

### Test
- **test:** 백엔드 테스트 커버리지 리포트 생성 및 CI 연동 (#194, PR #197)
  - pytest-cov 기반, 70% 임계값 (현재 83.87%)
  - CI에서 PR 코멘트로 자동 보고
- **test(viewer):** Playwright E2E 테스트 환경 구축 (#195, PR #203)

---

## [0.37.0] - 2026-03-05

### Sprint 15

### Added
- **feat(api):** Job 목록 페이지네이션 및 정렬 (#196)
- **test:** 백엔드 테스트 커버리지 CI 연동 (#194)

---

## [0.36.0] - 2026-03-05

### Sprint 14

### Fixed
- **fix(viewer):** Toast.tsx ESLint 오류 수정 (#190) — 렌더 중 ref 접근을 useEffect로 이동

### Added
- **chore(ci):** 프론트엔드 테스트를 CI 파이프라인에 추가 (#191)

### Documentation
- **docs:** README에 로컬 개발 환경 설정 가이드 추가 (#192)

---

## [0.35.0] - 2026-03-05

### Sprint 13

### Added
- **feat(api):** Rate Limiting, GPU Semaphore, Path Traversal 리팩토링 (#93)
- **feat(api):** main.py 라우터 분리 리팩토링 (#205)

---

## [0.34.0] - 2026-03-05

### Sprint 12

### Security
- **fix(api):** WebSocket 보안 강화 (#171, PR #174)
  - 첫 메시지 토큰 인증 방식 도입
  - Job 소유권 검증 추가

### Added
- **feat(docker):** Grafana 모니터링 대시보드 및 알림 규칙 구성 (#172, PR #175)
  - node-exporter 추가, Alertmanager Slack webhook 지원
- **feat(viewer):** 모바일 반응형 UI 및 접근성 개선 (#176)

---

## [0.23.0] - 2026-03-05

### Sprint 11

### Test
- **test(e2e):** 인증 플로우 포함 E2E 테스트 보강 (#103)
  - 회원가입 → 로그인 → Job 생성 → 조회 → 삭제 전체 플로우 검증

---

## [0.21.0] - 2026-03-05

### Sprint 10

### Added
- **feat(viewer):** 로그인/회원가입 UI 및 인증 토큰 관리 (#105)

---

## [0.20.0] - 2026-03-05

### Sprint 9

### Added
- **feat(api):** JWT 기반 사용자 등록/로그인/토큰 갱신 API (#98, PR #102)
  - access token + refresh token rotation
  - 기존 API 엔드포인트에 인증 의존성 적용

---

## [0.18.0] - 2026-03-05

### Sprint 8

### Added
- **feat(api):** Rate Limiting, GPU Semaphore, Path Traversal 리팩토링 (#93)

---

## [0.17.0] - 2026-03-05

### Sprint 7

### Added
- **feat(api):** Job 삭제 API 및 Splat 파일 서빙 (#89)

---

## [0.16.0] - 2026-03-05

### Sprint 6

### Added
- **feat(viewer):** Gaussian Splatting 렌더러 Spark v2 통합 (#56, PR #80)
  - `.splat`, `.spz` 포맷 지원
  - 포맷별 자동 전환 (PLY 폴백)

---

## [0.15.0] - 2026-03-05

### Sprint 5

### Added
- **feat(viewer):** Job 히스토리 목록 페이지 (#73, PR #78)
  - `/history` 라우트에서 전체 Job 목록 조회
  - React Router 도입, Layout/Outlet 패턴 적용

---

## [0.14.0] - 2026-03-05

### Added
- **feat(api):** Job 결과 파일 목록 조회 및 다운로드 엔드포인트 (#72, PR #75)
  - `GET /api/jobs/{job_id}/files`
  - `GET /api/jobs/{job_id}/download/{file_path}`

---

## [0.13.0] - 2026-03-05

### Added
- **feat(viewer):** Potree LoD 포인트 클라우드 렌더링 (#50, PR #70)
  - potree-core 기반 옥트리 Level-of-Detail 렌더링
  - PotreeConverter 연동 및 자동 PLY 폴백
- **feat(api):** `/health` 엔드포인트 및 pydantic-settings 설정 분리 (#64, #65)

---

## [0.12.1] - 2026-03-05

### Test
- **test(e2e):** E2E 파이프라인 통합 테스트 12개 추가 (#67, PR #69)
  - sparse/dense/3DGS 모드, 에러 전파, 옵션 전달 검증

---

## [0.11.0] - 2026-03-04

### Added
- **feat(reconstruction):** 3D Gaussian Splatting 학습 파이프라인 (#55, PR #59)
  - nerfstudio + gsplat 기반
  - VRAM 자동 감지 및 프리셋 자동 선택 (low/medium/high)
  - `engine="gaussian_splatting"` 옵션으로 3DGS 학습 지원

---

## [0.10.0] - 2026-03-04

### Added
- **feat(docker):** GPU Docker 지원

### Fixed
- **fix(api):** SSE 버그 수정

---

## [0.9.0] - 2026-03-04

### Added
- **feat(reconstruction):** Dense MVS 파이프라인
- **feat(viewer):** 뷰어 UI 개선

---

## [0.5.0] - 2026-03-04

### Added
- **feat(api):** FastAPI 백엔드 API 구현 (#18, PR #25)
  - 파이프라인 작업 생성/조회/결과 다운로드 엔드포인트
  - Thread-safety, path traversal 방지, XSS 방지, graceful shutdown

---

## [0.4.0] - 2026-03-04

### Added
- **feat:** 엔드투엔드 파이프라인 오케스트레이터 및 CLI 진입점 (#19, PR #23)
  - `python -m src`로 실행 가능

---

## [0.3.0] - 2026-03-04

### Added
- **feat(downloader):** yt-dlp 기반 유튜브 영상 다운로드
- **feat(extractor):** ffmpeg 기반 프레임 추출
- **feat(reconstruction):** COLMAP SfM 3D 복원 파이프라인

---

## [0.2.0] - 2026-03-04

### Documentation
- 사진측량 파이프라인 기술 스택 리서치 문서 (#1)
- 유튜브 영상 다운로드 및 프레임 추출 방법 리서치 문서 (#2)

---

## [0.1.0] - 2026-03-04

### Added
- 프로젝트 초기 구조 설정 (#4, PR #7)
  - Python 프로젝트 구조 (pyproject.toml, hatchling, ruff, pytest)
  - 디렉토리 구조 (src/downloader, extractor, reconstruction, api, viewer)
  - Makefile (lint, test, format, install)
  - Docker 개발 환경 (Dockerfile + docker-compose.yml)
  - GitHub Actions CI 워크플로우

[Unreleased]: https://github.com/conaonda/EXTube/compare/v0.46.0...HEAD
[0.46.0]: https://github.com/conaonda/EXTube/compare/v0.45.0...v0.46.0
[0.45.0]: https://github.com/conaonda/EXTube/compare/v0.44.0...v0.45.0
[0.44.0]: https://github.com/conaonda/EXTube/compare/v0.43.0...v0.44.0
[0.43.0]: https://github.com/conaonda/EXTube/compare/v0.42.0...v0.43.0
[0.42.0]: https://github.com/conaonda/EXTube/compare/v0.41.0...v0.42.0
[0.41.0]: https://github.com/conaonda/EXTube/compare/v0.40.0...v0.41.0
[0.40.0]: https://github.com/conaonda/EXTube/compare/v0.39.0...v0.40.0
[0.39.0]: https://github.com/conaonda/EXTube/compare/v0.38.0...v0.39.0
[0.38.0]: https://github.com/conaonda/EXTube/compare/v0.37.0...v0.38.0
[0.37.0]: https://github.com/conaonda/EXTube/compare/v0.36.0...v0.37.0
[0.36.0]: https://github.com/conaonda/EXTube/compare/v0.35.0...v0.36.0
[0.35.0]: https://github.com/conaonda/EXTube/compare/v0.34.0...v0.35.0
[0.34.0]: https://github.com/conaonda/EXTube/compare/v0.23.0...v0.34.0
[0.23.0]: https://github.com/conaonda/EXTube/compare/v0.21.0...v0.23.0
[0.21.0]: https://github.com/conaonda/EXTube/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/conaonda/EXTube/compare/v0.18.0...v0.20.0
[0.18.0]: https://github.com/conaonda/EXTube/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/conaonda/EXTube/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/conaonda/EXTube/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/conaonda/EXTube/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/conaonda/EXTube/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/conaonda/EXTube/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/conaonda/EXTube/compare/v0.11.0...v0.12.1
[0.11.0]: https://github.com/conaonda/EXTube/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/conaonda/EXTube/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/conaonda/EXTube/compare/v0.5.0...v0.9.0
[0.5.0]: https://github.com/conaonda/EXTube/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/conaonda/EXTube/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/conaonda/EXTube/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/conaonda/EXTube/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/conaonda/EXTube/releases/tag/v0.1.0
