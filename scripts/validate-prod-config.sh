#!/usr/bin/env bash
set -euo pipefail

# EXTube 프로덕션 배포 사전 검증 스크립트

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
warning() { echo -e "  ${YELLOW}[WARN]${NC} $*"; WARNINGS=$((WARNINGS + 1)); }

echo "========================================"
echo " EXTube 프로덕션 배포 사전 검증"
echo "========================================"
echo ""

# 1. Docker / Docker Compose 설치 확인
echo "[ 인프라 ]"
if command -v docker >/dev/null 2>&1; then
    pass "Docker 설치됨 ($(docker --version | grep -oP '\d+\.\d+\.\d+'))"
else
    fail "Docker가 설치되어 있지 않습니다"
fi

if docker compose version >/dev/null 2>&1; then
    pass "Docker Compose 설치됨"
else
    fail "Docker Compose가 설치되어 있지 않습니다"
fi

# NVIDIA Container Toolkit (GPU 프로파일 사용 시)
if [ "${EXTUBE_GPU:-}" = "1" ] || [ "${1:-}" = "--gpu" ]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
        pass "NVIDIA 드라이버 감지됨"
    else
        fail "GPU 모드이나 NVIDIA 드라이버가 감지되지 않습니다"
    fi
    if docker info 2>/dev/null | grep -q "nvidia"; then
        pass "NVIDIA Container Toolkit 감지됨"
    else
        fail "GPU 모드이나 NVIDIA Container Toolkit이 감지되지 않습니다"
    fi
fi

echo ""

# 2. .env 파일 확인
echo "[ 환경 변수 ]"

# 프로젝트 루트 .env
if [ -f "$PROJECT_DIR/.env" ]; then
    pass ".env 파일 존재 (프로젝트 루트)"

    # JWT secret key 기본값 확인
    if grep -qE "EXTUBE_JWT_SECRET_KEY\s*=\s*change-me" "$PROJECT_DIR/.env" 2>/dev/null; then
        fail "EXTUBE_JWT_SECRET_KEY가 기본값(change-me)입니다. 변경하세요"
    elif grep -q "EXTUBE_JWT_SECRET_KEY" "$PROJECT_DIR/.env" 2>/dev/null; then
        pass "EXTUBE_JWT_SECRET_KEY 설정됨"
    else
        warning "EXTUBE_JWT_SECRET_KEY가 .env에 없습니다"
    fi
else
    fail ".env 파일이 없습니다 (프로젝트 루트). cp .env.example .env로 생성하세요"
fi

# docker/.env
if [ -f "$DOCKER_DIR/.env" ]; then
    pass ".env 파일 존재 (docker/)"

    # REDIS_PASSWORD
    if grep -qE "REDIS_PASSWORD\s*=\s*$" "$DOCKER_DIR/.env" 2>/dev/null; then
        fail "REDIS_PASSWORD가 비어있습니다"
    elif grep -q "REDIS_PASSWORD" "$DOCKER_DIR/.env" 2>/dev/null; then
        pass "REDIS_PASSWORD 설정됨"
    else
        fail "REDIS_PASSWORD가 docker/.env에 없습니다"
    fi

    # DOMAIN
    if grep -qE "DOMAIN\s*=\s*$" "$DOCKER_DIR/.env" 2>/dev/null; then
        fail "DOMAIN이 비어있습니다"
    elif grep -q "DOMAIN" "$DOCKER_DIR/.env" 2>/dev/null; then
        pass "DOMAIN 설정됨"
    else
        fail "DOMAIN이 docker/.env에 없습니다"
    fi
else
    fail "docker/.env 파일이 없습니다. cp docker/.env.example docker/.env로 생성하세요"
fi

echo ""

# 3. SSL 인증서 확인
echo "[ SSL 인증서 ]"
if [ -f "$DOCKER_DIR/.env" ] && grep -q "DOMAIN" "$DOCKER_DIR/.env" 2>/dev/null; then
    DOMAIN=$(grep -oP 'DOMAIN\s*=\s*\K\S+' "$DOCKER_DIR/.env" 2>/dev/null || true)
    if [ -n "$DOMAIN" ]; then
        CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        if [ -f "$CERT_PATH" ]; then
            pass "SSL 인증서 존재 ($CERT_PATH)"
        else
            warning "SSL 인증서가 없습니다 ($CERT_PATH). 배포 후 certbot으로 발급하세요"
        fi
    else
        warning "DOMAIN 값이 비어있어 SSL 인증서를 확인할 수 없습니다"
    fi
else
    warning "DOMAIN 설정이 없어 SSL 인증서를 확인할 수 없습니다"
fi

echo ""

# 결과 요약
echo "========================================"
if [ $ERRORS -gt 0 ]; then
    echo -e " ${RED}검증 실패: $ERRORS개 오류, $WARNINGS개 경고${NC}"
    echo "========================================"
    exit 1
else
    echo -e " ${GREEN}검증 통과: $ERRORS개 오류, $WARNINGS개 경고${NC}"
    echo "========================================"
    exit 0
fi
