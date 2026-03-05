"""JWT 인증 및 사용자 관리."""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator

from src.api.config import get_settings
from src.api.db import JobStore

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])

# 모듈 수준 참조 — main.py에서 set_job_store()로 주입
_job_store: JobStore | None = None

# 로그인 실패 추적: username -> (실패 횟수, 마지막 실패 시각)
_login_attempts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))


def _check_login_lockout(username: str) -> None:
    """로그인 잠금 상태를 확인한다."""
    settings = get_settings()
    count, last_fail = _login_attempts[username]
    if count >= settings.max_login_attempts:
        elapsed = time.time() - last_fail
        if elapsed < settings.login_lockout_seconds:
            remaining = int(settings.login_lockout_seconds - elapsed)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"로그인 시도 횟수 초과. {remaining}초 후 다시 시도하세요.",
            )
        # 잠금 시간 경과 시 초기화
        _login_attempts[username] = (0, 0.0)


def _record_login_failure(username: str) -> None:
    """로그인 실패를 기록한다."""
    count, _ = _login_attempts[username]
    _login_attempts[username] = (count + 1, time.time())


def _clear_login_attempts(username: str) -> None:
    """로그인 성공 시 실패 기록을 초기화한다."""
    _login_attempts.pop(username, None)


def set_job_store(store: JobStore) -> None:
    global _job_store  # noqa: PLW0603
    _job_store = store


def _get_store() -> JobStore:
    assert _job_store is not None
    return _job_store


# --- Pydantic 스키마 ---


_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]).{8,}$"
)


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not _PASSWORD_PATTERN.match(v):
            raise ValueError(
                "비밀번호는 최소 8자이며, "
                "대문자·소문자·숫자·특수문자를 "
                "각각 1개 이상 포함해야 합니다"
            )
        return v


class UserResponse(BaseModel):
    id: str
    username: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# --- 토큰 생성 ---


def _create_access_token(user_id: str, username: str) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _create_refresh_token(user_id: str) -> tuple[str, str]:
    """refresh token을 생성하고 (jwt_string, token_id)를 반환한다."""
    settings = get_settings()
    token_id = uuid.uuid4().hex
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": user_id,
        "jti": token_id,
        "exp": expire,
        "type": "refresh",
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return token, token_id


# --- 인증 의존성 ---


def _validate_access_token(token: str) -> dict:
    """access token을 검증하고 사용자 정보를 반환한다."""
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효하지 않은 인증 토큰입니다",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")
        if user_id is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    store = _get_store()
    user = store.users.get_by_id(user_id)
    if user is None:
        raise credentials_exception
    return {"id": user["id"], "username": user["username"]}


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """access token에서 현재 사용자를 추출한다."""
    return _validate_access_token(token)


def get_current_user_or_query_token(
    token: str | None = Depends(oauth2_scheme_optional),
    query_token: str | None = Query(None, alias="token"),
) -> dict:
    """Authorization 헤더 또는 query parameter의 토큰으로 사용자를 인증한다.

    서드파티 3D 뷰어 라이브러리(PLYLoader, SparkJS 등)는
    Authorization 헤더를 설정할 수 없으므로 query parameter를 지원한다.
    """
    effective_token = token or query_token
    if not effective_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _validate_access_token(effective_token)


# --- 엔드포인트 ---


@router.post("/register", response_model=UserResponse, status_code=201, summary="사용자 등록")
def register(body: UserRegister) -> UserResponse:
    """새 사용자 계정을 등록한다."""
    store = _get_store()
    existing = store.users.get_by_username(body.username)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 사용자명입니다",
        )
    user_id = uuid.uuid4().hex[:12]
    hashed = pwd_context.hash(body.password)
    result = store.users.create(user_id, body.username, hashed)
    return UserResponse(**result)


@router.post("/login", response_model=TokenResponse, summary="로그인")
def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """사용자명과 비밀번호로 로그인하고 JWT access/refresh 토큰을 발급한다."""
    _check_login_lockout(form.username)

    store = _get_store()
    user = store.users.get_by_username(form.username)
    if user is None or not pwd_context.verify(form.password, user["hashed_password"]):
        _record_login_failure(form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="잘못된 사용자명 또는 비밀번호입니다",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _clear_login_attempts(form.username)

    settings = get_settings()
    access_token = _create_access_token(user["id"], user["username"])
    refresh_token, token_id = _create_refresh_token(user["id"])
    expires_at = time.time() + settings.refresh_token_expire_days * 86400
    store.refresh_tokens.create(token_id, user["id"], expires_at)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse, summary="토큰 갱신")
def refresh(body: RefreshRequest) -> TokenResponse:
    """refresh token으로 새 access/refresh 토큰 쌍을 발급한다 (token rotation)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            body.refresh_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")
        token_id = payload.get("jti")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")

    store = _get_store()
    stored = store.refresh_tokens.get(token_id)
    if stored is None or stored["expires_at"] < time.time():
        raise HTTPException(
            status_code=401,
            detail="토큰이 만료되었거나 무효화되었습니다",
        )

    # 기존 refresh token 무효화 (rotation)
    store.refresh_tokens.revoke(token_id)

    user = store.users.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다")

    new_access = _create_access_token(user["id"], user["username"])
    new_refresh, new_token_id = _create_refresh_token(user["id"])
    new_expires = time.time() + settings.refresh_token_expire_days * 86400
    store.refresh_tokens.create(new_token_id, user["id"], new_expires)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)
