# Rate Limiting 및 동시 작업 제한 전략 조사

> 관련 이슈: #83
> 작성일: 2026-03-05

## 1. 현재 상태 분석

- **Rate Limiting**: 없음. 모든 엔드포인트가 무제한 요청 수락.
- **동시 작업 제한**: `ThreadPoolExecutor(max_workers=N)`으로 GPU 작업 동시 실행 수만 제한.
- **큐잉**: 없음. `ThreadPoolExecutor` 내부 큐에 의존하며, 서버 재시작 시 대기 작업 유실.
- **인증**: 없음. IP 기반 식별만 가능.

## 2. FastAPI Rate Limiting 라이브러리 비교

| 항목 | **slowapi** | **fastapi-limiter** | **직접 구현 (미들웨어)** |
|------|------------|--------------------|-----------------------|
| GitHub Stars | ~1.2k | ~400 | N/A |
| 백엔드 | 인메모리 / Redis | Redis (필수) | 선택 가능 |
| 설정 방식 | 데코레이터 (`@limiter.limit`) | 데코레이터 (`@RateLimiter`) | 미들웨어 |
| 키 추출 | IP, 헤더, 커스텀 함수 | IP, 커스텀 함수 | 자유 |
| 유지보수 | 활발 | 보통 | 직접 관리 |
| Redis 필수 | 아니오 (인메모리 가능) | 예 | 아니오 |
| 분산 환경 지원 | Redis 사용 시 가능 | 가능 | Redis 사용 시 가능 |
| 적용 난이도 | 낮음 | 낮음 | 중간 |

**권장: slowapi**
- Redis 없이 인메모리로 시작 가능 (단일 인스턴스 배포에 적합)
- 추후 Redis 백엔드로 전환 용이
- 가장 널리 사용되며 문서 풍부

## 3. IP 기반 vs 토큰 기반 제한 전략

| 기준 | IP 기반 | 토큰 기반 |
|------|---------|----------|
| 구현 난이도 | 낮음 | 중간 (인증 시스템 필요) |
| 정확도 | NAT/프록시 뒤 사용자 구분 불가 | 정확한 사용자 식별 |
| 현재 적합성 | **높음** (인증 미구현) | 낮음 (인증 시스템 없음) |
| 우회 난이도 | IP 변경으로 우회 가능 | 토큰 발급 제한으로 방어 |

**권장: 1단계 IP 기반 → 2단계 토큰 기반 (인증 도입 후)**

### 권장 제한 값 (초안)
- `POST /api/jobs`: 분당 5회 (IP당) — GPU 작업은 비용이 크므로 엄격 제한
- `GET /api/jobs/*`: 분당 60회 (IP당) — 조회는 느슨하게
- `GET /api/jobs/{id}/stream`: 분당 10회 (IP당) — SSE 연결

## 4. GPU 작업 큐잉: ThreadPoolExecutor vs Celery vs RQ vs arq

| 항목 | **ThreadPoolExecutor** (현재) | **Celery** | **RQ (Redis Queue)** | **arq** |
|------|------------------------------|-----------|---------------------|---------|
| 의존성 | 표준 라이브러리 | Redis/RabbitMQ + celery | Redis + rq | Redis + arq |
| 설정 복잡도 | 없음 | 높음 | 낮음 | 낮음 |
| 작업 영속성 | 없음 (메모리) | 있음 (브로커) | 있음 (Redis) | 있음 (Redis) |
| 재시도 | 수동 구현 | 내장 | 내장 | 내장 |
| 작업 모니터링 | 없음 | Flower UI | rq-dashboard | arq 대시보드 |
| 동시성 제어 | max_workers | worker concurrency + 큐 | worker count | max_jobs |
| 스케줄링 | 없음 | Beat (크론) | rq-scheduler | 내장 cron |
| 프로세스 분리 | 동일 프로세스 | 별도 worker 프로세스 | 별도 worker 프로세스 | 별도 worker 프로세스 |
| GPU 적합성 | 낮음 | 높음 | 중간 | 중간 |
| 운영 복잡도 | 없음 | 높음 | 낮음 | 낮음 |

### 분석

**ThreadPoolExecutor의 한계** (현재):
- 서버 재시작 시 진행 중/대기 중 작업 유실
- 큐 크기 제한 없음 → 메모리 고갈 가능
- 작업 취소/재시도 불가
- 모니터링 불가

**Celery**:
- 프로덕션 검증된 솔루션이나 이 프로젝트 규모에 과도함
- RabbitMQ 또는 Redis 브로커 + 별도 Beat 프로세스 필요
- 학습 곡선 높음

**RQ**:
- Redis만 필요, 설정 간단
- 동시 작업 수 = worker 수로 자연스럽게 제한
- GPU 작업처럼 긴 실행 시간에 적합 (`job_timeout` 설정)
- rq-dashboard로 간단한 모니터링

**arq**:
- asyncio 네이티브, FastAPI와 궁합 좋음
- RQ보다 가볍고 빠름
- 상대적으로 커뮤니티 작음

**권장: RQ (Redis Queue)**
- 현재 프로젝트 규모에 적합한 복잡도
- Redis 하나로 rate limiting + 작업 큐 모두 해결
- 프로세스 분리로 API 서버 안정성 확보
- 충분한 모니터링 도구

## 5. 동시 작업 수 제한 및 큐 대기열 관리

### 권장 구성
```
[API 서버] → [Redis] → [RQ Worker × 1~2 (GPU)]
                ↑
          [slowapi rate limit]
```

| 설정 | 값 | 근거 |
|------|---|------|
| RQ worker 수 | 1~2 | GPU 메모리 제한 (COLMAP + GS) |
| 최대 대기열 크기 | 10 | 메모리/디스크 고갈 방지 |
| 작업 타임아웃 | 30분 | 영상 길이에 따른 최대 처리 시간 |
| IP당 동시 작업 | 2 | 리소스 독점 방지 |

### 큐 대기열 관리 방안
1. **대기열 크기 제한**: Job 생성 시 큐 길이 확인, 초과 시 HTTP 429 반환
2. **IP당 활성 작업 제한**: 동일 IP의 pending/processing 상태 작업 수 확인
3. **우선순위 큐**: 향후 유료 사용자 우선 처리 (RQ `Queue` 다중 생성)

## 6. Redis 의존성 추가 여부

### 판단 기준

| 시나리오 | Redis 필요 여부 | 이유 |
|---------|----------------|------|
| 단일 서버 + 간단한 rate limit | 불필요 | slowapi 인메모리로 충분 |
| 작업 영속성 + 모니터링 필요 | **필요** | ThreadPoolExecutor로는 불가 |
| 다중 서버/컨테이너 배포 | **필요** | 분산 상태 공유 |

**권장: Redis 도입**
- Docker Compose에 Redis 서비스 추가 (운영 부담 최소)
- rate limiting (slowapi) + 작업 큐 (RQ) 두 가지를 한 번에 해결
- 향후 세션/캐시 용도로도 활용 가능

## 7. 구현 로드맵

### Phase 1: Rate Limiting (난이도: 낮음, 1~2일)
- slowapi 도입 (인메모리 백엔드)
- `/api/jobs` POST에 IP 기반 제한 적용
- 429 응답 포맷 정의

### Phase 2: Redis + RQ 전환 (난이도: 중간, 3~5일)
- Docker Compose에 Redis 추가
- `_run_pipeline`을 RQ task로 전환
- RQ worker Dockerfile 작성
- slowapi 백엔드를 Redis로 전환
- 대기열 크기 제한 로직 추가

### Phase 3: 고급 제어 (난이도: 중간, 2~3일)
- IP당 동시 작업 수 제한
- 작업 취소 API (`DELETE /api/jobs/{id}`)
- rq-dashboard 연동
- 큐 상태 API (`GET /api/queue/status`)

## 8. 최종 권장 사항

| 항목 | 권장 | 대안 |
|------|------|------|
| Rate Limiting | slowapi (인메모리 → Redis) | fastapi-limiter |
| 제한 기준 | IP 기반 (1단계) | 토큰 기반 (인증 도입 후) |
| 작업 큐 | RQ | arq (asyncio 선호 시) |
| 브로커 | Redis | - |
| 동시 작업 | RQ worker 1~2개 | - |
| 대기열 제한 | 최대 10개 | 설정 가능하게 구현 |
