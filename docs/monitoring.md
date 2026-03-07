# EXTube 모니터링 가이드

## 아키텍처

```
app:8000/metrics → Prometheus → Grafana → Alertmanager → Slack/Email
                        ↑
              redis-exporter:9121
```

## 서비스 구성

| 서비스 | 이미지 | 포트 (내부) | 역할 |
|--------|--------|------------|------|
| Prometheus | prom/prometheus:v2.51.0 | 9090 | 메트릭 수집/저장 |
| Grafana | grafana/grafana:10.4.0 | 3000 | 대시보드 시각화 |
| Alertmanager | prom/alertmanager:v0.27.0 | 9093 | 알림 라우팅/발송 |
| redis-exporter | oliver006/redis_exporter:v1.61.0 | 9121 | Redis 메트릭 수집 |

## 접근 방법

- **Grafana**: `https://<도메인>/grafana/` (nginx 서브패스)
- 초기 로그인: `admin` / `${GRAFANA_PASSWORD}`

## 환경 변수

`.env` 파일에 다음을 설정:

```bash
GRAFANA_PASSWORD=<강력한 비밀번호>
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

## 대시보드

EXTube Overview 대시보드가 자동 프로비저닝됩니다:

| 패널 | 메트릭 | 시각화 |
|------|--------|--------|
| 활성 Job 수 | `extube_active_jobs` | Stat |
| 큐 길이 | `extube_queue_length` | Stat + Time series |
| 요청 처리율 | `rate(http_requests_total[5m])` | Time series |
| 에러율 (5xx) | `rate(http_requests_total{status=~"5.."}[5m])` | Time series |
| P95 응답시간 | `histogram_quantile(0.95, ...)` | Gauge |
| Redis 메모리 | `redis_memory_used_bytes` | Stat + Time series |

## 알림 규칙

| 알림 | 조건 | 심각도 | 대기시간 |
|------|------|--------|---------|
| QueueBacklog | 큐 길이 > 20 | warning | 10분 |
| HighErrorRate | 5xx 에러율 > 10% | critical | 5분 |
| WorkerDown | 활성 Job 있으나 Worker 없음 | critical | 2분 |
| DiskSpaceLow | 디스크 여유 < 10% | warning | 5분 |

### 알림 대응 가이드

#### QueueBacklog (warning)
- **원인**: 처리 속도 대비 Job 유입량 초과, Worker 성능 저하
- **대응**:
  1. Worker 프로세스 상태 확인: `docker compose logs worker`
  2. Worker 수 증설 검토
  3. 큐 내 장시간 대기 Job 확인 및 필요 시 제거

#### HighErrorRate (critical)
- **원인**: 애플리케이션 버그, 외부 의존성 장애, 리소스 부족
- **대응**:
  1. 애플리케이션 로그 확인: `docker compose logs app`
  2. Redis 연결 상태 확인
  3. 최근 배포 변경사항 확인 및 필요 시 롤백

#### WorkerDown (critical)
- **원인**: Worker 컨테이너 크래시, OOM, Redis 연결 끊김
- **대응**:
  1. Worker 컨테이너 상태 확인: `docker compose ps worker`
  2. Worker 로그 확인: `docker compose logs worker --tail=100`
  3. Worker 재시작: `docker compose restart worker`

#### DiskSpaceLow (warning)
- **원인**: Job 결과물 누적, 로그 파일 증가, Docker 이미지 누적
- **대응**:
  1. 디스크 사용량 확인: `df -h /`
  2. 오래된 Job 결과물 정리
  3. Docker 미사용 리소스 정리: `docker system prune`

### 알림 규칙 테스트

`promtool`을 사용하여 알림 규칙의 정확성을 검증한다.

```bash
# 규칙 문법 검사
promtool check rules docker/prometheus/rules/extube.yml

# 단위 테스트 실행
promtool test rules docker/prometheus/rules/extube_test.yml
```

테스트 파일(`docker/prometheus/rules/extube_test.yml`)에는 각 알림의 발생/미발생 시나리오가 포함되어 있다.
CI에서 `prometheus-rules` Job이 자동으로 실행된다.

### Alertmanager 알림 채널 설정

알림은 Slack `#extube-alerts` 채널로 전송된다. 설정 파일: `docker/alertmanager/alertmanager.yml`

**Slack Webhook 설정:**
1. [Slack Incoming Webhooks](https://api.slack.com/messaging/webhooks) 페이지에서 Webhook URL 생성
2. `docker/.env`에 URL 설정:
   ```
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   ```

**알림 라우팅:**

| 심각도 | 채널 | 반복 간격 |
|--------|------|----------|
| warning (default) | `#extube-alerts` | 4시간 |
| critical | `#extube-alerts` | 1시간 |

**다른 알림 채널 추가 (이메일 예시):**

`docker/alertmanager/alertmanager.yml`의 `receivers` 섹션에 추가:

```yaml
receivers:
  - name: email
    email_configs:
      - to: "ops@example.com"
        from: "alertmanager@example.com"
        smarthost: "smtp.example.com:587"
```

## 파일 구조

```
docker/
├── prometheus/
│   ├── prometheus.yml          # 스크레이프 설정
│   └── rules/
│       ├── extube.yml          # 알림 규칙
│       └── extube_test.yml     # promtool 단위 테스트
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   └── prometheus.yml  # 데이터소스 설정
│       └── dashboards/
│           ├── dashboard.yml   # 프로비저닝 설정
│           └── extube.json     # 대시보드 JSON
└── alertmanager/
    └── alertmanager.yml        # 알림 라우팅 설정
```

## 데이터 보존

- Prometheus: 15일 (`--storage.tsdb.retention.time=15d`)
- Grafana: `grafana_data` Docker 볼륨에 저장
