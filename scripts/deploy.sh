#!/usr/bin/env bash
set -euo pipefail

# EXTube 프로덕션 배포 스크립트

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 사전 조건 확인 (validate-prod-config.sh로 위임)
check_prerequisites() {
    info "사전 검증 스크립트 실행 중..."

    local gpu_flag=""
    if [ "${1:-}" = "--gpu" ]; then
        gpu_flag="--gpu"
    fi

    if ! "$SCRIPT_DIR/validate-prod-config.sh" $gpu_flag; then
        error "사전 검증 실패. 위 오류를 수정한 후 다시 시도하세요."
    fi

    info "사전 검증 완료"
}

# 빌드 및 실행
deploy() {
    local profile=""
    if [ "${1:-}" = "--gpu" ]; then
        profile="--profile gpu"
        info "GPU 모드로 배포합니다"
    fi

    info "Docker 이미지 빌드 중..."
    cd "$DOCKER_DIR"
    docker compose -f docker-compose.yml -f docker-compose.prod.yml $profile build

    info "서비스 시작 중..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml $profile up -d

    info "헬스체크 대기 중..."
    sleep 5

    # 헬스체크
    local max_retries=12
    local retry=0
    while [ $retry -lt $max_retries ]; do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            info "서비스가 정상 실행 중입니다"
            echo ""
            info "배포 완료!"
            echo "  - API: http://localhost:8000"
            echo "  - Health: http://localhost:8000/health"
            return 0
        fi
        retry=$((retry + 1))
        warn "헬스체크 대기 중... ($retry/$max_retries)"
        sleep 5
    done

    error "서비스가 정상적으로 시작되지 않았습니다. 로그를 확인하세요:\n  docker compose -f docker-compose.yml -f docker-compose.prod.yml logs"
}

# 메인
check_prerequisites "${1:-}"
deploy "$@"
