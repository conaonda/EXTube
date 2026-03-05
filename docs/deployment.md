# Docker Compose 프로덕션 배포 전략

> 조사 기준일: 2026-03-05 | 관련 이슈: #124

## 1. Override 전략: `docker-compose.prod.yml`

### 권장 접근법

Docker Compose의 [다중 파일 합성](https://docs.docker.com/compose/extends/) 기능을 활용한다.

```
docker-compose.yml          # 공통 서비스 정의 (개발/프로덕션 공유)
docker-compose.override.yml # 개발 전용 설정 (자동 로드)
docker-compose.prod.yml     # 프로덕션 전용 설정
```

**개발 실행:**
```bash
docker compose up           # compose.yml + override.yml 자동 합성
```

**프로덕션 실행:**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 주요 차이점

| 항목 | 개발(`override.yml`) | 프로덕션(`prod.yml`) |
|------|---------------------|---------------------|
| 빌드 컨텍스트 | 소스 볼륨 마운트 | 이미지 직접 참조 |
| 환경변수 | `.env` 파일 | Docker secrets / 환경 변수 주입 |
| 포트 노출 | 호스트 직접 노출 | Nginx를 통해서만 노출 |
| 재시작 정책 | `no` | `unless-stopped` |
| 리소스 제한 | 없음 | CPU/메모리 제한 설정 |

---

## 2. 헬스체크 설정

### 엔드포인트 활용

현재 구현된 엔드포인트:
- `GET /health` — 서버 생존 확인 (liveness)
- `GET /health/ready` — DB 연결 + COLMAP 바이너리 확인 (readiness)

### Docker Compose 헬스체크 설정

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

**파라미터 권장값:**
- `interval`: 30s — 주기적 확인 간격
- `timeout`: 10s — 타임아웃 (COLMAP 바이너리 확인 포함)
- `retries`: 3 — 3회 실패 시 unhealthy 상태
- `start_period`: 40s — 초기 시작 유예 시간 (모델 로딩 등 고려)

### 의존성 연계

```yaml
depends_on:
  redis:
    condition: service_healthy
  app:
    condition: service_healthy
```

---

## 3. Redis 영속성 및 보안 설정

### 영속성 전략

| 방식 | 특징 | 권장 용도 |
|------|------|----------|
| **RDB (Snapshot)** | 주기적 스냅샷, 복구 빠름 | 작업 결과 캐시 |
| **AOF (Append-Only File)** | 모든 쓰기 기록, 데이터 손실 최소 | 작업 상태 큐 |
| **RDB + AOF 혼합** | 안정성 + 성능 균형 | **프로덕션 권장** |

### 보안 설정

```yaml
redis:
  command: >
    redis-server
    --requirepass ${REDIS_PASSWORD}
    --maxmemory 512mb
    --maxmemory-policy allkeys-lru
    --save 900 1
    --save 300 10
    --appendonly yes
    --appendfsync everysec
    --bind 0.0.0.0
```

> **참고:** Docker 네트워크 환경에서는 `--bind 0.0.0.0`을 사용합니다.
> 컨테이너 간 통신이 Docker 내부 네트워크를 통해 이루어지므로,
> `127.0.0.1`로 바인딩하면 다른 컨테이너에서 접근할 수 없습니다.
> 외부 접근은 Docker 네트워크 격리와 `requirepass`로 차단됩니다.

**핵심 보안 항목:**
- `requirepass`: 비밀번호 인증 필수 (Docker secrets로 관리)
- `bind 0.0.0.0`: Docker 네트워크 내부 접근 허용 (외부는 포트 미노출로 차단)
- `maxmemory-policy allkeys-lru`: 메모리 초과 시 LRU 방식으로 만료

### Redis 설정 파일

프로덕션 환경에서는 `docker/redis/redis.conf`를 통해 Redis 설정을 관리한다.
비밀번호는 보안을 위해 설정 파일이 아닌 `docker-compose.prod.yml`에서 환경변수로 주입한다.

### 백업 및 복구

**자동 백업:**
- RDB 스냅샷: `save 900 1`, `save 300 10`, `save 60 10000` (redis.conf에서 설정)
- AOF: 모든 쓰기 연산 기록 (`appendfsync everysec`)
- 데이터는 `redis_data` Docker 볼륨의 `/data` 디렉토리에 저장

**수동 백업:**
```bash
# RDB 스냅샷 강제 생성
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis \
  redis-cli -a $REDIS_PASSWORD BGSAVE

# 백업 파일 호스트로 복사
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  cp redis:/data/dump.rdb ./backup/dump.rdb
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  cp redis:/data/appendonly.aof ./backup/appendonly.aof
```

**복구:**
```bash
# 1. 서비스 중지
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop redis

# 2. 백업 파일을 볼륨에 복사
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  cp ./backup/dump.rdb redis:/data/dump.rdb
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  cp ./backup/appendonly.aof redis:/data/appendonly.aof

# 3. 서비스 재시작
docker compose -f docker-compose.yml -f docker-compose.prod.yml start redis
```

**정기 백업 (cron 예시):**
```bash
# 매일 새벽 3시에 Redis 백업 수행
0 3 * * * cd /path/to/EXTube/docker && \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T redis \
  redis-cli -a $REDIS_PASSWORD BGSAVE && \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  cp redis:/data/dump.rdb /backup/redis/dump-$(date +\%Y\%m\%d).rdb
```

---

## 4. Nginx 리버스 프록시 + SSL 설정

### 구성 전략

```
Internet → Nginx (80/443) → app:8000
```

### SSL 인증서 옵션

| 방식 | 장점 | 단점 | 권장 상황 |
|------|------|------|----------|
| **Let's Encrypt (Certbot)** | 무료, 자동 갱신 | 도메인 필요 | 퍼블릭 서버 |
| **Self-signed** | 빠른 설정 | 브라우저 경고 | 내부 테스트 |
| **Cloudflare Tunnel** | 인프라 최소화 | Cloudflare 의존 | 홈서버/소규모 |

### 권장 Nginx 설정 (Let's Encrypt)

```nginx
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # 보안 헤더
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header Strict-Transport-Security "max-age=31536000";

    location / {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 지원 (Spark 등)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 대용량 파일 업로드 (3D 모델)
    client_max_body_size 500M;
}
```

---

## 5. 로그 수집 전략

### stdout 기반 로그 드라이버

Docker의 기본 `json-file` 드라이버는 용량 제한 없이 성장할 수 있음.

**권장 설정 (json-file + 로테이션):**
```yaml
logging:
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"
```

### 로그 집중화 옵션

| 솔루션 | 특징 | 권장 상황 |
|--------|------|----------|
| **Loki + Grafana** | 경량, Docker 친화적 | 소규모 ~ 중규모 |
| **ELK Stack** | 강력한 검색/분석 | 대규모, 로그 분석 중요 |
| **CloudWatch / Datadog** | 관리형 서비스 | 클라우드 환경 |
| **json-file + logrotate** | 단순, 추가 인프라 없음 | **초기 단계 권장** |

**EXTube 초기 단계 권장:** `json-file` + 로테이션으로 시작, 로그 분석 필요 시 Loki 도입.

---

## 6. 재시작 정책 및 리소스 제한

### 재시작 정책

| 정책 | 동작 | 권장 서비스 |
|------|------|------------|
| `no` | 재시작 안 함 | 개발 환경 |
| `on-failure` | 오류 종료 시만 재시작 | 일회성 작업 |
| `unless-stopped` | 수동 중지 전까지 재시작 | **프로덕션 API 서버** |
| `always` | 항상 재시작 | 인프라 서비스 (Redis) |

### 리소스 제한

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 4G
    reservations:
      cpus: '0.5'
      memory: 1G
```

**서비스별 권장 설정:**

| 서비스 | CPU 제한 | 메모리 제한 | 비고 |
|--------|---------|------------|------|
| `app` | 2.0 | 4G | FastAPI + COLMAP |
| `app-gpu` | 4.0 | 8G | GPU 작업 포함 |
| `redis` | 0.5 | 512M | maxmemory와 일치 |
| `nginx` | 0.5 | 256M | 정적 파일 서빙 |

---

## 7. 환경별 실행 방법

### 개발 환경

```bash
cd docker
docker compose up
```

`docker-compose.yml` + `docker-compose.override.yml`(있는 경우)이 자동 합성됩니다.

### 프로덕션 환경

1. 환경 변수 설정:
```bash
cd docker
cp .env.example .env
# .env 파일에서 REDIS_PASSWORD, DOMAIN 등을 실제 값으로 변경
```

2. SSL 인증서 초기 발급:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot -d $DOMAIN --agree-tos -m admin@$DOMAIN
```

3. 서비스 실행:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

4. GPU 프로파일 포함 실행:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile gpu up -d
```

---

## 8. 권장 사항 요약

### 단기 (즉시 적용)
1. `docker-compose.prod.yml` 생성 — 볼륨 마운트 제거, 재시작 정책 설정
2. Redis `requirepass` + `maxmemory` 설정
3. 로그 드라이버 `json-file` + 로테이션 설정

### 중기 (안정화 후)
4. Nginx 리버스 프록시 추가 (SSL 포함)
5. Docker secrets로 민감 정보 관리
6. 헬스체크 기반 의존성 연계

### 장기 (운영 성숙 후)
7. Loki + Grafana 로그 집중화
8. 모니터링 (Prometheus + Grafana)

---

## 참고 자료
- [Docker Compose 다중 파일 합성](https://docs.docker.com/compose/extends/)
- [Docker 헬스체크 공식 문서](https://docs.docker.com/engine/reference/builder/#healthcheck)
- [Redis 보안 가이드](https://redis.io/docs/manual/security/)
- [Nginx 프록시 설정 가이드](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
