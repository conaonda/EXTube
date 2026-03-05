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

| 알림 | 조건 | 심각도 |
|------|------|--------|
| QueueBacklog | 큐 길이 > 20 (10분간) | warning |
| HighErrorRate | 5xx 에러율 > 10% (5분간) | critical |
| WorkerDown | 활성 Job 있으나 Worker 없음 (2분간) | critical |
| DiskSpaceLow | 디스크 여유 < 10% (5분간) | warning |

## 파일 구조

```
docker/
├── prometheus/
│   ├── prometheus.yml          # 스크레이프 설정
│   └── rules/
│       └── extube.yml          # 알림 규칙
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
