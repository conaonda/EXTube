# Rate Limiting 및 동시 작업 제한 전략 조사

> Issue: #83
> 작성일: 2026-03-05

## 현재 상태

- API에 rate limiting 미적용 — 무제한 요청 가능
- `ThreadPoolExecutor(max_workers=4)`로 동시 작업 제한 (기본값 4)
- SQLite WAL 모드로 작업 상태 관리
- 작업 실패 시 재시도 없음, 프로세스 크래시 시 작업 유실

---

## 1. FastAPI Rate Limiting 라이브러리 비교

| 항목 | SlowAPI | fastapi-limiter | Custom Redis Middleware |
|---|---|---|---|
| 방식 | 데코레이터 (flask-limiter 포팅) | FastAPI 의존성 주입 | 직접 구현 미들웨어 |
| 알고리즘 | Token bucket, leaky bucket, fixed/sliding window | Fixed window (pyrate-limiter) | 자유 선택 |
| 백엔드 | 인메모리, Redis, Memcached | Redis (필수) | Redis |
| 비동기 지원 | O | O | O |
| PyPI 다운로드 | ~79,000/주 | 상대적 적음 | N/A |
| 유지보수 (2026) | **비활성** — 12개월+ 릴리스 없음 | **비활성** — 12개월+ 릴리스 없음 | N/A |

**권장:** 두 주요 라이브러리 모두 사실상 유지보수 중단 상태. **Custom Redis 미들웨어** 구현이 가장 안전한 선택. Sliding window (Redis sorted set) 또는 Fixed window (`INCR`+`EXPIRE`) 구현이 간단하며 외부 의존성 최소화.

---

## 2. IP 기반 vs 토큰 기반 제한 전략

| 항목 | IP 기반 | 토큰/사용자 기반 | 하이브리드 |
|---|---|---|---|
| 설정 복잡도 | 단순 | 인증 필요 | 중간 |
| 정확도 | 낮음 (NAT/공유 IP 문제) | 높음 | 높음 |
| 비인증 엔드포인트 | 유일한 옵션 | 불가 | IP로 커버 |
| 우회 가능성 | 중간 (X-Forwarded-For 조작) | 낮음 | 낮음 |

**권장:** **하이브리드** 방식. 전체 엔드포인트에 넉넉한 IP 기반 제한 적용 (DDoS 방어), GPU 작업 생성(`POST /api/jobs`)에는 더 엄격한 제한 적용.

---

## 3. GPU 작업 큐 비교: ThreadPoolExecutor vs Celery vs RQ vs Dramatiq

| 항목 | ThreadPoolExecutor | Celery | RQ | Dramatiq |
|---|---|---|---|---|
| 복잡도 | 최소 (stdlib) | 높음 | 낮음 | 중간 |
| 브로커 | 없음 (인프로세스) | RabbitMQ, Redis, SQS | Redis만 | RabbitMQ, Redis |
| 작업 영속성 | 없음 — 크래시 시 유실 | 있음 | 있음 | 있음 |
| 분산 워커 | 불가 | 가능 | 가능 | 가능 |
| 워크플로우 | 수동 | Chain, Group, Chord | 기본 | Pipeline, Group |
| 재시도/DLQ | 수동 | 내장 | 기본 | 내장 (우수한 기본값) |
| 모니터링 | 없음 | Flower | rq-dashboard | Prometheus 내장 |
| 성능 | 빠름 (직렬화 없음) | 양호 | 느림 (~10x Dramatiq 대비) | 빠름 |
| GPU 적합성 | 단일서버 소규모 | 멀티노드 대규모 | 단순 설정 | 균형 잡힘 |

**핵심:** GPU 작업(COLMAP, 3DGS)은 외부 C/CUDA 프로세스로 실행되므로 GIL 영향 없음. Python 워커는 서브프로세스 I/O 대기만 수행.

| 규모 | 권장 |
|---|---|
| MVP / 단일 GPU 서버 | **ThreadPoolExecutor + asyncio.Semaphore** |
| 프로덕션 / 단일 서버 | **Dramatiq + Redis** |
| 프로덕션 / 멀티 GPU 클러스터 | **Celery + Redis/RabbitMQ** |

---

## 4. Redis 의존성 판단

| 용도 | Redis 적합도 | 핵심 패턴 |
|---|---|---|
| Rate limiting | 우수 | `INCR`+`EXPIRE`, sorted set, Lua 스크립트 |
| 작업 브로커 | 양호 | Celery/Dramatiq/RQ 모두 지원 |
| 작업 상태 추적 | 우수 | Hash + TTL 자동 만료 |
| 분산 락 | 양호 | `SET NX EX` (GPU 리소스 잠금) |

**판단:** Redis 단일 의존성으로 rate limiting + 작업 큐 + 상태 관리를 모두 해결 가능. 프로덕션 전환 시 추가 권장. MVP 단계에서는 인메모리로 충분.

---

## 5. 동시 GPU 작업 제한 모범 사례

| 방안 | 구현 |
|---|---|
| Semaphore 기반 동시성 | `asyncio.Semaphore(N)`, N = GPU 수 |
| 고정 워커 큐 | 작업 큐 워커 동시성 = GPU 수 |
| 전용 GPU 큐 | GPU 작업(COLMAP, 3DGS)과 경량 작업(다운로드, 추출) 큐 분리 |
| 메모리 인식 스케줄링 | `nvidia-smi` 여유 메모리 확인 후 작업 수락/대기 |
| 타임아웃/킬 | GPU 작업 하드 타임 리밋 설정, COLMAP 행 프로세스 강제 종료 |

**권장 아키텍처:**
```
[FastAPI] --rate limit (Redis)--> [Job Queue (Dramatiq/Celery + Redis)]
                                         |
                                   [GPU Worker Pool]
                                   concurrency = num_GPUs
                                   dedicated "gpu" queue
                                         |
                              [COLMAP / 3DGS subprocess]
```

---

## 종합 권장안

| 컴포넌트 | MVP (현재) | 프로덕션 |
|---|---|---|
| Rate limiting | Custom 인메모리 미들웨어 (sliding window) | Custom Redis 미들웨어 + 사용자별 티어 |
| 작업 큐 | ThreadPoolExecutor + Semaphore | Dramatiq + Redis |
| GPU 동시성 | Semaphore(1) — GPU 작업 1개씩 | 전용 GPU 큐, workers = GPU 수 |
| 백킹 스토어 | 인메모리 (현행 유지) | Redis (AOF 영속성 활성화) |

### 구현 난이도

| 작업 | 난이도 | 예상 이슈 |
|---|---|---|
| MVP rate limiting (인메모리) | **낮음** | 1개 이슈 |
| GPU Semaphore 적용 | **낮음** | 1개 이슈 |
| Redis 인프라 추가 (Docker) | **중간** | 1개 이슈 |
| Dramatiq 마이그레이션 | **높음** | 2-3개 이슈 |
| 프로덕션 rate limiting (Redis) | **중간** | 1개 이슈 |
