#!/usr/bin/env bash
set -euo pipefail

# validate-prod-config.sh 검증 테스트
# 의도적으로 설정을 빠뜨려 스크립트가 올바르게 감지하는지 확인

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VALIDATE_SCRIPT="$PROJECT_DIR/scripts/validate-prod-config.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

PASSED=0
FAILED=0

assert_fail() {
    local desc="$1"
    if bash "$VALIDATE_SCRIPT" >/dev/null 2>&1; then
        echo -e "${RED}[FAIL]${NC} $desc — 검증이 통과했으나 실패해야 합니다"
        FAILED=$((FAILED + 1))
    else
        echo -e "${GREEN}[PASS]${NC} $desc"
        PASSED=$((PASSED + 1))
    fi
}

assert_pass() {
    local desc="$1"
    if bash "$VALIDATE_SCRIPT" >/dev/null 2>&1; then
        echo -e "${GREEN}[PASS]${NC} $desc"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}[FAIL]${NC} $desc — 검증이 실패했으나 통과해야 합니다"
        FAILED=$((FAILED + 1))
    fi
}

cleanup() {
    rm -f "$PROJECT_DIR/.env" "$PROJECT_DIR/docker/.env"
}
trap cleanup EXIT

echo "=== validate-prod-config.sh 테스트 ==="
echo ""

# 테스트 1: .env 파일 없음
cleanup
assert_fail "테스트 1: .env 파일 없으면 실패"

# 테스트 2: 기본값 그대로
cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
cp "$PROJECT_DIR/docker/.env.example" "$PROJECT_DIR/docker/.env"
assert_fail "테스트 2: 기본값 그대로면 실패"

# 테스트 3: JWT만 변경, Redis 기본값
sed -i 's/change-me-to-a-random-secret-key/my-super-strong-key-12345/' "$PROJECT_DIR/.env"
assert_fail "테스트 3: Redis 기본값이면 실패"

# 테스트 4: JWT+Redis 변경, 도메인 기본값
sed -i 's/changeme_use_strong_password/strong-redis-pw-xyz/' "$PROJECT_DIR/docker/.env"
assert_fail "테스트 4: 도메인 기본값이면 실패"

# 테스트 5: 모두 변경 (Docker 미설치 환경에서는 여전히 실패할 수 있음)
sed -i 's/example.com/extube.example.org/' "$PROJECT_DIR/docker/.env"
# Docker가 설치되어 있지 않으면 이 테스트는 실패 — 환경 의존적이므로 skip
echo -e "${GREEN}[SKIP]${NC} 테스트 5: 전체 통과 (Docker 설치 여부에 의존)"

echo ""
echo "========================================="
echo "결과: 통과 $PASSED / 실패 $FAILED"
echo "========================================="

[ $FAILED -eq 0 ] && exit 0 || exit 1
