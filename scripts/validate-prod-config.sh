#!/usr/bin/env bash
set -euo pipefail

# EXTube 프로덕션 배포 사전 검증 스크립트
# docs/deployment.md 체크리스트와 동기화

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

pass()    { echo -e "  ${GREEN}[PASS]${NC} $*"; }
fail()    { echo -e "  ${RED}[FAIL]${NC} $*"; ERRORS=$((ERRORS + 1)); }
warn_msg() { echo -e "  ${YELLOW}[WARN]${NC} $*"; WARNINGS=$((WARNINGS + 1)); }

section() { echo -e "\n${GREEN}===${NC} $* ${GREEN}===${NC}"; }

# === 필수 항목 ===

check_env_files() {
    section "환경 변수 파일 확인"

    if [ -f "$PROJECT_DIR/.env" ]; then
        pass ".env 파일 존재"
    else
        fail ".env 파일이 없습니다. 'cp .env.example .env'로 생성하세요"
    fi

    if [ -f "$DOCKER_DIR/.env" ]; then
        pass "docker/.env 파일 존재"
    else
        fail "docker/.env 파일이 없습니다. 'cp docker/.env.example docker/.env'로 생성하세요"
    fi
}

check_jwt_secret() {
    section "JWT Secret Key 확인"

    if [ ! -f "$PROJECT_DIR/.env" ]; then
        fail ".env 파일이 없어 JWT secret 확인 불가"
        return
    fi

    local jwt_key
    jwt_key=$(grep -E "^EXTUBE_JWT_SECRET_KEY=" "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)

    if [ -z "$jwt_key" ]; then
        fail "EXTUBE_JWT_SECRET_KEY가 설정되지 않았습니다"
    elif echo "$jwt_key" | grep -qiE "change-me|changeme|secret|default"; then
        fail "EXTUBE_JWT_SECRET_KEY가 기본값입니다. 강력한 랜덤 값으로 변경하세요"
    else
        pass "EXTUBE_JWT_SECRET_KEY 설정됨"
    fi
}

check_redis_password() {
    section "Redis 비밀번호 확인"

    if [ ! -f "$DOCKER_DIR/.env" ]; then
        fail "docker/.env 파일이 없어 Redis 비밀번호 확인 불가"
        return
    fi

    local redis_pw
    redis_pw=$(grep -E "^REDIS_PASSWORD=" "$DOCKER_DIR/.env" 2>/dev/null | cut -d= -f2- || true)

    if [ -z "$redis_pw" ]; then
        fail "REDIS_PASSWORD가 설정되지 않았습니다"
    elif echo "$redis_pw" | grep -qiE "changeme|change-me|password|default"; then
        fail "REDIS_PASSWORD가 기본값입니다. 강력한 비밀번호로 변경하세요"
    else
        pass "REDIS_PASSWORD 설정됨"
    fi
}

check_domain() {
    section "도메인 설정 확인"

    if [ ! -f "$DOCKER_DIR/.env" ]; then
        fail "docker/.env 파일이 없어 도메인 확인 불가"
        return
    fi

    local domain
    domain=$(grep -E "^DOMAIN=" "$DOCKER_DIR/.env" 2>/dev/null | cut -d= -f2- || true)

    if [ -z "$domain" ]; then
        fail "DOMAIN이 설정되지 않았습니다"
    elif [ "$domain" = "example.com" ]; then
        fail "DOMAIN이 기본값(example.com)입니다. 실제 도메인으로 변경하세요"
    else
        pass "DOMAIN 설정됨: $domain"
    fi
}

# === 인프라 항목 ===

check_docker() {
    section "Docker 설치 확인"

    if command -v docker >/dev/null 2>&1; then
        pass "Docker 설치됨: $(docker --version 2>/dev/null | head -1)"
    else
        fail "Docker가 설치되어 있지 않습니다"
    fi

    if docker compose version >/dev/null 2>&1; then
        pass "Docker Compose 설치됨: $(docker compose version 2>/dev/null | head -1)"
    else
        fail "Docker Compose가 설치되어 있지 않습니다"
    fi
}

check_nvidia_toolkit() {
    section "NVIDIA Container Toolkit 확인 (GPU 프로파일)"

    if command -v nvidia-smi >/dev/null 2>&1; then
        pass "nvidia-smi 사용 가능"
        if docker info 2>/dev/null | grep -q "nvidia"; then
            pass "NVIDIA Container Runtime 감지됨"
        else
            warn_msg "NVIDIA Container Runtime이 Docker에 등록되지 않았습니다 (GPU 미사용 시 무시)"
        fi
    else
        warn_msg "nvidia-smi를 찾을 수 없습니다 (GPU 미사용 시 무시)"
    fi
}

check_ssl_certificates() {
    section "SSL 인증서 확인"

    if [ ! -f "$DOCKER_DIR/.env" ]; then
        warn_msg "docker/.env 파일이 없어 도메인 기반 SSL 확인 생략"
        return
    fi

    local domain
    domain=$(grep -E "^DOMAIN=" "$DOCKER_DIR/.env" 2>/dev/null | cut -d= -f2- || true)

    local cert_path="$DOCKER_DIR/certbot/conf/live/$domain/fullchain.pem"
    if [ -n "$domain" ] && [ "$domain" != "example.com" ] && [ -f "$cert_path" ]; then
        pass "SSL 인증서 존재: $cert_path"
    else
        warn_msg "SSL 인증서를 찾을 수 없습니다. Let's Encrypt 발급 또는 Cloudflare Tunnel 사용을 확인하세요"
    fi
}

# === 결과 요약 ===

summary() {
    echo ""
    echo "========================================="
    if [ $ERRORS -gt 0 ]; then
        echo -e "  ${RED}검증 실패${NC}: 에러 ${ERRORS}개, 경고 ${WARNINGS}개"
        echo "========================================="
        echo -e "  ${RED}배포를 진행할 수 없습니다. 위 에러를 수정하세요.${NC}"
        return 1
    elif [ $WARNINGS -gt 0 ]; then
        echo -e "  ${YELLOW}검증 통과 (경고 있음)${NC}: 경고 ${WARNINGS}개"
        echo "========================================="
        echo -e "  ${YELLOW}배포는 가능하지만 경고 항목을 확인하세요.${NC}"
        return 0
    else
        echo -e "  ${GREEN}검증 통과${NC}: 모든 항목 정상"
        echo "========================================="
        return 0
    fi
}

# === 메인 ===

echo "EXTube 프로덕션 배포 사전 검증"
echo "========================================="

check_env_files
check_jwt_secret
check_redis_password
check_domain
check_docker
check_nvidia_toolkit
check_ssl_certificates

summary
