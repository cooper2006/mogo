#!/bin/bash

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_WEB_DIR="$ROOT_DIR/apps/user-web"
CHAT_API_DIR="$ROOT_DIR/services/chat-api"
ADMIN_WEB_DIR="$ROOT_DIR/apps/admin-web"
ADMIN_API_DIR="$ROOT_DIR/services/admin-api"
DOCUMENT_PARSER_DIR="$ROOT_DIR/services/document-parser"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
ADMIN_API_PORT="${ADMIN_API_PORT:-8100}"
ADMIN_WEB_PORT="${ADMIN_WEB_PORT:-3100}"
DOC_PROCESSING_PORT="${DOC_PROCESSING_PORT:-8200}"
ASKAI_REDIS_URL="${ASKAI_REDIS_URL:-redis://127.0.0.1:6379/0}"
BACKEND_PYTHON_BIN=""
DOC_PROCESSING_PYTHON_BIN=""

# 环境 profile：与 ./mogo 共用同一套归一化与校验（deploy/cli/env-profiles.sh），
# 允许 `./dev.sh --profile dev`、`./dev.sh --profile=test`，或 MOGO_PROFILE=dev。
# dev.sh 起的都是宿主原生进程（uvicorn / vite / celery），没有容器平台可钉，
# 所以调用时把 pin_platform 关掉——否则 arm64 开发机跑 --profile prod 会被
# "请先指定架构"拦下，而这里根本不存在架构问题。
export MOGO_PROFILE="${MOGO_PROFILE:-}"
if [[ $# -gt 0 ]]; then
    profile_args=()
    while [[ $# -gt 0 ]]; do
        case "${1}" in
            --profile)
                if [[ -z "${2:-}" ]]; then
                    printf 'Error: --profile requires one of dev, test, prod.\n' >&2
                    exit 2
                fi
                MOGO_PROFILE="${2}"
                shift 2
                ;;
            --profile=*)
                MOGO_PROFILE="${1#*=}"
                shift
                ;;
            *)
                profile_args+=("${1}")
                shift
                ;;
        esac
    done
    set -- ${profile_args[@]+"${profile_args[@]}"}
fi

# shellcheck source=deploy/cli/i18n.sh
source "$ROOT_DIR/deploy/cli/i18n.sh"
mogo_detect_locale
# shellcheck source=deploy/cli/env-profiles.sh
source "$ROOT_DIR/deploy/cli/env-profiles.sh"

# 归一化 + 冲突校验（dev 必须 mongo 后端、test/prod 不能开外部库模式等）。
# 失败就停在这里，不去动端口和 venv。
mogo_apply_profile true false || exit $?

# One credential must be shared by admin-api and chat-api in local source mode.
# shellcheck source=scripts/dev/internal_service_auth.sh
source "$ROOT_DIR/scripts/dev/internal_service_auth.sh"

kill_port() {
    local port="$1"
    local pids
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [ -n "$pids" ]; then
        echo "Releasing port :$port ..."
        kill $pids 2>/dev/null || true
        sleep 1
        pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
        if [ -n "$pids" ]; then
            kill -9 $pids 2>/dev/null || true
        fi
    fi
}

cleanup_ports() {
    kill_port "$BACKEND_PORT"
    kill_port "$FRONTEND_PORT"
    kill_port "$ADMIN_API_PORT"
    kill_port "$ADMIN_WEB_PORT"
    kill_port "$DOC_PROCESSING_PORT"
}

ensure_redis() {
    if ! command -v redis-cli >/dev/null 2>&1; then
        echo "Redis CLI not found. Install Redis first: brew install redis && brew services start redis"
        exit 1
    fi
    if ! redis-cli -u "$ASKAI_REDIS_URL" ping >/dev/null 2>&1; then
        echo "Redis is not available at $ASKAI_REDIS_URL"
        echo "Start Redis first: brew services start redis"
        exit 1
    fi
}

cleanup() {
    echo ""
    echo "Stopping services..."
    kill $(jobs -p) 2>/dev/null || true
    cleanup_ports
    exit
}

trap cleanup SIGINT SIGTERM

ensure_backend_venv() {
    cd "$CHAT_API_DIR"
    : > backend.log
    if [ -d "venv" ]; then
        source venv/bin/activate
    else
        python -m venv venv
        source venv/bin/activate
    fi
    export PATH="$(pwd)/venv/bin:$PATH"
    export PYTHONUTF8=1
    export PYTHONIOENCODING=utf-8
    export LANG="${LANG:-en_US.UTF-8}"
    export LC_ALL="${LC_ALL:-en_US.UTF-8}"
    export ASKAI_ADMIN_APP_ENV="${ASKAI_ADMIN_APP_ENV:-development}"
    export ASKAI_ADMIN_DOCUMENT_PROCESSING_BASE_URL="${ASKAI_ADMIN_DOCUMENT_PROCESSING_BASE_URL:-http://127.0.0.1:$DOC_PROCESSING_PORT}"
    export ASKAI_ADMIN_ADMIN_API_PUBLIC_BASE_URL="${ASKAI_ADMIN_ADMIN_API_PUBLIC_BASE_URL:-http://127.0.0.1:$ADMIN_API_PORT}"
    export ASKAI_DOC_PROCESSING_REDIS_URL="${ASKAI_DOC_PROCESSING_REDIS_URL:-$ASKAI_REDIS_URL}"
    BACKEND_PYTHON_BIN="$(pwd)/venv/bin/python"
    cd "$ROOT_DIR"
}

ensure_document_processing_venv() {
    cd "$DOCUMENT_PARSER_DIR"
    if [ -d ".venv" ]; then
        :
    else
        "$BACKEND_PYTHON_BIN" -m venv .venv
    fi
    DOC_PROCESSING_PYTHON_BIN="$(pwd)/.venv/bin/python"
    if ! "$DOC_PROCESSING_PYTHON_BIN" -c "import celery, fastapi, oss2, pymongo, pydantic_settings, redis, uvicorn" >/dev/null 2>&1; then
        "$DOC_PROCESSING_PYTHON_BIN" -m pip install -r requirements.txt
    fi
    cd "$ROOT_DIR"
}

# 宿主进程连的是 .env 里配的数据库；dev/test profile 预期那个库由栈内容器提供。
# 没起就在这儿提示一句，不自动 docker compose up（不动用户现成的栈）。
ensure_profile_database() {
    local service_name=""
    case "${MOGO_PROFILE}" in
        dev) service_name="mongo" ;;
        test) service_name="panweidb" ;;
        *) return 0 ;;
    esac
    command -v docker >/dev/null 2>&1 || return 0
    if ! docker ps --format '{{.Label "com.docker.compose.service"}}' 2>/dev/null | grep -qx "${service_name}"; then
        echo "Hint: the ${MOGO_PROFILE} profile expects the local ${service_name} container."
        echo "      Start it with: docker compose --profile ${MOGO_PROFILE} up -d ${service_name}"
    fi
}

start_runtime_backend() {
    echo "Starting Backend on :$BACKEND_PORT ..."
    cd "$CHAT_API_DIR"
    PYTHONPATH="$(pwd)" "$BACKEND_PYTHON_BIN" -m uvicorn app.main:app --reload --reload-dir app --port "$BACKEND_PORT" \
        --timeout-graceful-shutdown "${BACKEND_GRACEFUL_SHUTDOWN_SECONDS:-5}" \
        --reload-exclude "backend.log" \
        --reload-exclude "static/*" \
        --reload-exclude "*.pyc" \
        --reload-exclude "__pycache__/*" &
    cd "$ROOT_DIR"
}

start_frontend() {
    echo "Starting Frontend on :$FRONTEND_PORT ..."
    cd "$USER_WEB_DIR"
    npm run dev &
    cd "$ROOT_DIR"
}

start_admin_api() {
    echo "Starting Admin API on :$ADMIN_API_PORT ..."
    cd "$ADMIN_API_DIR"
    PYTHONPATH="$(pwd)" "$BACKEND_PYTHON_BIN" -m uvicorn app.main:app --reload --reload-dir app --port "$ADMIN_API_PORT" &
    cd "$ROOT_DIR"
}

start_document_processing_service() {
    echo "Starting Document Processing Service on :$DOC_PROCESSING_PORT ..."
    cd "$DOCUMENT_PARSER_DIR"
    PYTHONPATH="$(pwd)" "$DOC_PROCESSING_PYTHON_BIN" -m uvicorn app.main:app --reload --reload-dir app --port "$DOC_PROCESSING_PORT" &
    cd "$ROOT_DIR"
}

start_document_worker() {
    echo "Starting Document Worker ..."
    cd "$DOCUMENT_PARSER_DIR"
    PYTHONPATH="$(pwd)" "$DOC_PROCESSING_PYTHON_BIN" -m celery -A app.workers.celery_app:celery_app worker \
        --loglevel=info \
        --queues="${ASKAI_DOC_PROCESSING_CELERY_QUEUE:-document_processing}" &
    cd "$ROOT_DIR"
}

start_admin_web() {
    echo "Starting Admin Web on :$ADMIN_WEB_PORT ..."
    cd "$ADMIN_WEB_DIR"
    npm run dev &
    cd "$ROOT_DIR"
}

echo "Starting AskAI Platform..."
mogo_prepare_internal_service_auth "$ROOT_DIR"
cleanup_ports
ensure_backend_venv
ensure_document_processing_venv
ensure_redis
ensure_profile_database
echo "Using Backend Python: $BACKEND_PYTHON_BIN"
echo "Using Doc Processing Python: $DOC_PROCESSING_PYTHON_BIN"

start_runtime_backend
start_frontend
start_admin_api
start_document_processing_service
start_document_worker
start_admin_web

echo ""
echo "Services are starting up!"
echo "  - Frontend:    http://localhost:$FRONTEND_PORT"
echo "  - Backend:     http://localhost:$BACKEND_PORT/docs"
echo "  - Admin Web:   http://localhost:$ADMIN_WEB_PORT"
echo "  - Admin API:   http://localhost:$ADMIN_API_PORT/docs"
echo "  - Doc Process: http://localhost:$DOC_PROCESSING_PORT/docs"
echo "  - Redis:       $ASKAI_REDIS_URL"
echo ""
echo "Press Ctrl+C to stop all services."

wait
