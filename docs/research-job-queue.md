# Job 큐잉 시스템 도입 전략 조사

> 관련 이슈: #100
> 작성일: 2026-03-05

---

## 1. 현재 아키텍처 분석

### 현재 구조

```
POST /api/jobs
  -> SQLite에 job 레코드 생성 (pending)
  -> ThreadPoolExecutor.submit(_run_pipeline)  <- 메모리 큐
  -> GPU Semaphore로 동시 GPU 작업 수 제한
```

### 현재 구조의 문제점

| 문제 | 설명 | 영향도 |
|------|------|-------|
| 작업 영속성 없음 | 서버 재시작 시 ThreadPoolExecutor 큐에 있던 pending/processing 작업 유실 | 높음 |
| 큐 크기 무제한 | max_workers 초과 작업은 내부 큐에 쌓이며 메모리 고갈 가능 | 중간 |
| 재시작 복구 불가 | 서버 재시작 후 DB에 pending/processing 상태로 남는 좀비 레코드 발생 | 높음 |
| 사용자별 제한 불가 | 현재는 IP 기반 rate limiting만 가능, 사용자별 동시 실행 제한 없음 | 중간 |
| 모니터링 없음 | 대기 중 작업 수, 예상 대기시간 등 관찰 불가 | 낮음 |
| 작업 취소 어려움 | Future.cancel()은 실행 시작 전에만 가능, 실행 중 취소 불가 | 낮음 |

---

## 2. Job 큐 솔루션 비교

### 2-1. 종합 비교표

| 항목 | ThreadPoolExecutor (현재) | Celery + Redis | RQ | Dramatiq | arq | SQLite 자체 큐 |
|------|--------------------------|---------------|-----|----------|-----|--------------|
| 추가 의존성 | 없음 | Redis + celery + flower | Redis + rq | Redis + dramatiq | Redis + arq | APScheduler |
| 설정 복잡도 | 없음 | 높음 | 낮음 | 중간 | 낮음 | 낮음 |
| 작업 영속성 | 없음 | 있음 | 있음 | 있음 | 있음 | 있음 |
| 서버 재시작 복구 | 없음 | 있음 | 있음 | 있음 | 있음 | 있음 (폴링) |
| asyncio 네이티브 | 없음 | 없음 | 없음 | 없음 | 있음 | 부분 |
| FastAPI 통합 | 간단 | 복잡 | 중간 | 중간 | 자연스러움 | 간단 |
| GPU 장시간 작업 | 중간 | 있음 (ack_late) | 있음 (job_timeout) | 있음 | 있음 | 있음 |
| 사용자별 제한 | 없음 | 있음 (큐 라우팅) | 수동 | 수동 | 수동 | 수동 |
| 모니터링 | 없음 | Flower UI | rq-dashboard | 별도 | 없음 | 직접 구현 |
| 분산 확장성 | 없음 | 있음 | 있음 | 있음 | 있음 | 없음 |
| 프로세스 분리 | 없음 (동일 프로세스) | 있음 | 있음 | 있음 | 있음 | 없음 |
| 학습 곡선 | 없음 | 높음 | 낮음 | 중간 | 낮음 | 없음 |
| GitHub Stars | N/A | ~24k | ~10k | ~4k | ~2k | N/A |
| 프로젝트 적합성 | 낮음 | 과도함 | 높음 | 중간 | 중간 | 보통 |

---

## 3. GPU 작업 특수성 고려

### GPU 작업의 특징
- 장시간 실행: COLMAP/Gaussian Splatting은 수십 분~수 시간 소요
- 메모리 점유: 작업 중 GPU 메모리 전량 사용
- 동시 실행 불가: GPU 1개 환경에서는 직렬 처리 필수
- 중단 시 재개 어려움: 체크포인트 없으면 처음부터 재실행 필요

### GPU 큐 처리 요구사항

```
GPU 작업 큐 설계 원칙:
  1. 동시 GPU 작업 = 1 (또는 GPU 수만큼)
  2. 큐 대기 중에도 영속성 보장
  3. 타임아웃: 최소 3시간 (장시간 작업)
  4. 재시작 시 재개 불가 -> 실패 처리 후 사용자 알림
  5. 큐 크기 제한: 최대 10~20개 (무제한 허용 금지)
```

### RQ의 GPU 작업 설정 예시

```python
from rq import Queue
from redis import Redis

conn = Redis()
# gpu 전용 큐, 타임아웃 3시간
q = Queue('gpu', connection=conn, default_timeout=10800)

# job 제출
job = q.enqueue(_run_pipeline, job_id, params)
```

- `job_timeout`으로 최대 실행 시간 제한
- worker 수 = GPU 수로 자연스러운 동시성 제어
- 기존 `Semaphore` 로직 제거 가능

---

## 4. 마이그레이션 복잡도 평가

### 현재 -> RQ 변경 범위

| 변경 영역 | 현재 코드 | 변경 후 | 난이도 |
|-----------|----------|---------|-------|
| Job 제출 | `_executor.submit(_run_pipeline, job_id, body)` | `q.enqueue(_run_pipeline, job_id, body)` | 낮음 |
| 동시성 제어 | `Semaphore + ThreadPoolExecutor` | RQ worker 수로 대체 | 낮음 |
| 실행 환경 | 동일 프로세스 | 별도 `rq worker` 프로세스 | 중간 |
| Docker Compose | API 서비스만 | API + Redis + RQ Worker 서비스 추가 | 중간 |
| 테스트 | mock executor | fakeredis 사용 | 중간 |

예상 구현 범위: 3~5일 (API 변경 + Docker 설정 + 테스트)

---

## 5. 서버 재시작 시 미완료 Job 복구 전략

### 복구 전략 비교

| 전략 | 설명 | 적합성 |
|------|------|-------|
| 실패 처리 (권장) | 재시작 시 pending/processing -> failed 전환, 사용자 재제출 유도 | 단순, 안전 |
| 자동 재큐잉 | pending -> 다시 큐에 추가 | processing 재시작은 위험 (GPU 메모리 이중 사용 가능) |
| 체크포인트 재개 | 파이프라인 단계별 결과 저장 후 이어서 실행 | 구현 복잡, COLMAP은 재개 미지원 |

권장: 서버 시작 시 `pending`/`processing` 상태 job을 `failed`로 전환하고 error 메시지 기록

```python
# lifespan 이벤트에서 실행
def recover_stale_jobs(job_store):
    count = job_store.fail_stale_jobs(
        statuses=["pending", "processing"],
        error="서버 재시작으로 인해 작업이 중단되었습니다. 재제출해 주세요."
    )
    logger.info("재시작 복구: %d개 job을 failed로 전환", count)
```

---

## 6. Docker Compose 인프라 영향

### RQ 도입 시 추가 서비스

```yaml
services:
  api:
    build: .
    depends_on: [redis]
    environment:
      - REDIS_URL=redis://redis:6379

  redis:                          # 신규
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes  # AOF 영속성 활성화

  rq-worker:                      # 신규
    build: .
    command: rq worker --with-scheduler gpu
    depends_on: [redis]
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]  # GPU 패스스루
    environment:
      - REDIS_URL=redis://redis:6379

volumes:
  redis_data:
```

추가 서비스: Redis 1개, RQ Worker 1개
Redis 메모리 사용: ~50MB (경량)

---

## 7. 권장 방안

### 최종 권장: RQ (Redis Queue)

근거:
1. 적절한 복잡도: Celery 대비 설정 단순, 이 프로젝트 규모에 적합
2. 영속성 확보: Redis AOF로 재시작 후 pending 작업 보존
3. GPU 친화적: worker 1개 = GPU 동시 실행 1개로 자연스러운 제어
4. 향후 확장: GPU 추가 시 worker 수만 늘리면 됨
5. 인프라 통합: 향후 rate limiting에 Redis 재사용 가능 (slowapi 권장안과 일치)

### 단계별 구현 스코프

**Phase 1: 기반 구축**
- Docker Compose에 Redis 서비스 추가 (AOF 영속성)
- `rq` 의존성 추가 (`pyproject.toml`)
- `REDIS_URL` 설정 추가 (`config.py`)

**Phase 2: 큐 마이그레이션**
- `_executor.submit()` -> `q.enqueue()` 교체
- `Semaphore` + `ThreadPoolExecutor` 제거
- Docker Compose에 `rq-worker` 서비스 추가 (GPU 패스스루 포함)

**Phase 3: 재시작 복구**
- `lifespan` 이벤트에서 stale job 실패 처리 로직 추가
- `JobStore.fail_stale_jobs()` 메서드 구현

**Phase 4: 큐 크기 제한**
- `POST /api/jobs` 시 큐 대기 수 확인, 임계값 초과 시 429 반환

### 대안 (SQLite 폴링)을 권장하지 않는 이유
- 재시작 복구, 큐 크기 제한, 타임아웃 등 직접 구현 필요
- 프로세스 분리 없어 API 서버 안정성 저하
- RQ와 기능 차이 대비 구현 비용 유사

---

## 8. 참고

- [RQ 공식 문서](https://python-rq.org/)
- [rq-dashboard](https://github.com/Parallels/rq-dashboard)
- [Redis AOF 영속성](https://redis.io/docs/manual/persistence/)
- 관련 리서치: docs/research-rate-limiting.md
