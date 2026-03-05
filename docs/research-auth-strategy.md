# API 인증 및 사용자 관리 전략 조사

> Issue: #96 | Date: 2026-03-05

## 1. 인증 방식 비교

### JWT vs API Key vs OAuth2

| 항목 | JWT | API Key | OAuth2 |
|------|-----|---------|--------|
| **구현 복잡도** | 중간 | 낮음 | 높음 |
| **상태 관리** | Stateless (서명 검증) | Stateful (DB 조회) | Stateful (토큰 저장소) |
| **만료/갱신** | access+refresh 토큰 | 수동 갱신 | 자동 갱신 (refresh) |
| **사용자 식별** | claim 내장 | DB 매핑 필요 | 풍부한 스코프/클레임 |
| **취소(revocation)** | 어려움 (블랙리스트 필요) | 즉시 가능 | 즉시 가능 |
| **프론트 연동** | Authorization header | X-API-Key header | Authorization header |
| **적합한 사용처** | SPA/모바일 앱 | 서버-서버, CLI | 소셜 로그인, 멀티앱 |

### EXTube 맥락 평가

EXTube는 현재 단일 프론트엔드 + FastAPI 구조이며 소셜 로그인 요구사항이 없다.

- **OAuth2 (Google/GitHub 등)**: 불필요한 외부 의존성. 현 단계에선 과도함.
- **API Key**: 사용자 관리 없이 단순 접근 제어만 필요할 때 적합. 다중 사용자 quota 관리가 어렵다.
- **JWT (권장)**: username/password 로그인 → access token + refresh token 발급. FastAPI `python-jose` + `passlib`으로 표준 구현 가능. 사용자별 claim으로 Job 격리 가능.

---

## 2. FastAPI 보안 미들웨어 옵션

### 2-1. FastAPI 내장 Security (`fastapi.security`)

```python
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    ...
```

- **장점**: 추가 패키지 불필요, OpenAPI /docs에 자동 통합, Depends로 라우터별 적용 가능
- **단점**: JWT 파싱은 `python-jose` 별도 필요

### 2-2. authlib

- RFC 준수 OAuth2/OIDC 완전 구현체
- FastAPI용 `authlib.integrations.starlette_client` 제공
- **단점**: 소셜 로그인이나 OIDC 서버 구축 목적이 아니면 과도함

### 2-3. fastapi-users

- User 모델, 이메일 인증, OAuth2 소셜 로그인까지 통합 라이브러리
- SQLAlchemy / Beanie ORM 지원
- **단점**: 현재 EXTube는 SQLite + 자체 DB 구조를 사용하고 있어 마이그레이션 비용 발생

### 권장: FastAPI 내장 Security + python-jose + passlib

가장 가볍고 현 아키텍처와 호환성이 좋다.

---

## 3. 사용자별 Job 격리 및 Quota 관리

### Job 격리 방안

현재 `data/jobs/{job_id}/` 구조를 `data/jobs/{user_id}/{job_id}/`로 변경하면 파일시스템 수준 격리 가능.

DB(`jobs.db`)에 `user_id` 컬럼 추가:

```sql
ALTER TABLE jobs ADD COLUMN user_id TEXT NOT NULL DEFAULT 'anonymous';
CREATE INDEX idx_jobs_user_id ON jobs(user_id);
```

Job 조회/삭제 엔드포인트에서 `WHERE job_id = ? AND user_id = ?` 조건 추가로 타 사용자 접근 차단.

### Quota 관리 방안

| 방식 | 설명 | 복잡도 |
|------|------|--------|
| DB COUNT | `SELECT COUNT(*) FROM jobs WHERE user_id=? AND created_at > now()-interval` | 낮음 |
| Rate Limit 통합 | 기존 `RateLimitMiddleware`에 user_id 키 추가 | 낮음 |
| 전용 quota 테이블 | `user_quotas` 테이블로 세밀한 제어 | 중간 |

**권장**: 초기에는 DB COUNT 방식으로 동시 활성 Job 수 제한 (예: 사용자당 최대 3개). 추후 quota 테이블로 확장.

---

## 4. Rate Limiting 통합

기존 `RateLimitMiddleware`는 IP 기반이다. 인증 도입 후 **user_id 기반**으로 전환 가능:

```python
# 현재: IP 기반 키
key = f"{client_ip}:default"

# 변경 후: 인증된 사용자면 user_id, 미인증이면 IP
key = f"user:{user_id}" if user_id else f"ip:{client_ip}"
```

미들웨어에서 JWT 토큰을 파싱해 `user_id`를 추출하고 `request.state.user_id`에 저장하면 rate limiter와 라우터 모두에서 활용 가능.

---

## 5. 권장 구현 방향

### 채택: JWT + FastAPI 내장 Security

**구현 스택**:
- `python-jose[cryptography]` — JWT 생성/검증
- `passlib[bcrypt]` — 비밀번호 해싱
- `fastapi.security.OAuth2PasswordBearer` — 토큰 추출

**엔드포인트**:
- `POST /auth/register` — 사용자 등록
- `POST /auth/token` — 로그인 → access token 발급
- `POST /auth/refresh` — refresh token으로 갱신

**DB 변경**:
- `users` 테이블 추가 (`id`, `username`, `hashed_password`, `created_at`)
- `jobs` 테이블에 `user_id` 컬럼 추가

**설정 추가** (`config.py`):
```python
jwt_secret_key: str = "change-me-in-production"
jwt_algorithm: str = "HS256"
access_token_expire_minutes: int = 30
refresh_token_expire_days: int = 7
```

### 단계별 구현 계획

1. **Phase 1**: `users` 테이블 + `/auth` 엔드포인트 구현
2. **Phase 2**: 기존 Job 엔드포인트에 `Depends(get_current_user)` 추가
3. **Phase 3**: `jobs.user_id` 컬럼 추가 + Job 격리 적용
4. **Phase 4**: Rate Limiter를 user_id 기반으로 전환 + quota 제한 추가

---

## 6. 보안 고려사항

- JWT secret은 반드시 환경변수로 주입 (`EXTUBE_JWT_SECRET_KEY`)
- refresh token은 DB에 저장하고 로그아웃 시 즉시 무효화
- HTTPS 미적용 환경에서는 토큰 노출 위험 → 프로덕션 배포 시 TLS 필수
- Job 파일 다운로드 엔드포인트도 인증 적용 필요 (현재 공개)

---

## 참고

- [FastAPI Security 공식 문서](https://fastapi.tiangolo.com/tutorial/security/)
- [python-jose](https://github.com/mpdavis/python-jose)
- [passlib](https://passlib.readthedocs.io/)
