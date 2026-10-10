#!/usr/bin/env bash
# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
# Carefold Unified Component Launcher
# Coordinates FastAPI Backend (:8010) and Next.js Web UI (:3010).
# ==============================================================================
set -euo pipefail

# Ensure essential tools are discovered in standard environment paths
if [ -n "${HOME:-}" ]; then
    export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
else
    export PATH="${PATH:-/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"
fi

# Resolve real script directory following symlinks
SOURCE="${BASH_SOURCE[0]}"
while [ -h "${SOURCE}" ]; do
    DIR="$(cd -P "$(dirname "${SOURCE}")" && pwd)"
    SOURCE="$(readlink "${SOURCE}")"
    [[ ${SOURCE} != /* ]] && SOURCE="${DIR}/${SOURCE}"
done
SCRIPT_DIR="$(cd -P "$(dirname "${SOURCE}")" && pwd)"

if [ -f "${SCRIPT_DIR}/package.json" ]; then
    PROJECT_ROOT="${SCRIPT_DIR}"
elif [ -f "${SCRIPT_DIR}/../package.json" ]; then
    PROJECT_ROOT="$(cd -P "${SCRIPT_DIR}/.." && pwd)"
else
    PROJECT_ROOT="$(pwd)"
fi

# ANSI formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Track whether CAREFOLD_WEB_PORT was explicitly set by user
CAREFOLD_WEB_PORT_SET=0
if [ -n "${CAREFOLD_WEB_PORT:-}" ]; then
    CAREFOLD_WEB_PORT_SET=1
fi

# Default Configuration
CAREFOLD_BACKEND_PORT="${CAREFOLD_BACKEND_PORT:-${PORT:-8010}}"
CAREFOLD_BACKEND_HOST="${CAREFOLD_BACKEND_HOST:-${HOST:-127.0.0.1}}"
CAREFOLD_WEB_PORT="${CAREFOLD_WEB_PORT:-3010}"
CAREFOLD_WEB_HOST="${CAREFOLD_WEB_HOST:-localhost}"

LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${PROJECT_ROOT}/.carefold.pids"

# Tracking child PIDs for cleanup in foreground modes
CHILD_PIDS=()

log_info() {
    echo -e "${CYAN}[carefold]${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}[carefold:ok]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[carefold:warn]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[carefold:error]${NC} $1" >&2
}

check_prerequisites() {
    local target="${1:-all}"
    local missing=()

    # Node.js and pnpm checks (required for web, all, start, daemon)
    if [ "${target}" = "all" ] || [ "${target}" = "web" ]; then
        command -v node >/dev/null 2>&1 || missing+=("node (Node.js runtime >=22)")
        command -v pnpm >/dev/null 2>&1 || missing+=("pnpm (Node.js package manager)")
    fi

    # Python checks (required for backend, all, start, daemon)
    if [ "${target}" = "all" ] || [ "${target}" = "backend" ]; then
        local py_bin="${PROJECT_ROOT}/backend/.venv/bin/python3"
        if [ ! -x "${py_bin}" ] && ! command -v python3 >/dev/null 2>&1; then
            missing+=("python3 (Python >=3.12 or backend/.venv)")
        fi
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing required runtime tools in PATH:"
        for tool in "${missing[@]}"; do
            echo -e "  - ${YELLOW}${tool}${NC}" >&2
        done
        exit 1
    fi
}

ensure_dependencies() {
    if [ ! -d "${PROJECT_ROOT}/apps/web/node_modules" ]; then
        log_info "Installing dependencies via pnpm..."
        cd "${PROJECT_ROOT}"
        pnpm install
    fi
}

is_port_in_use() {
    local port="$1"
    lsof -iTCP:"${port}" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

kill_port_process() {
    local port="$1"
    local pids
    pids=$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "${pids}" ]; then
        for pid in ${pids}; do
            kill -TERM "${pid}" 2>/dev/null || true
        done
        sleep 0.5
        pids=$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)
        if [ -n "${pids}" ]; then
            for pid in ${pids}; do
                kill -9 "${pid}" 2>/dev/null || true
            done
        fi
    fi
}

cleanup_foreground() {
    if [ ${#CHILD_PIDS[@]} -gt 0 ]; then
        log_info "Shutting down child processes..."
        for pid in "${CHILD_PIDS[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                kill -TERM "${pid}" 2>/dev/null || true
            fi
        done
        wait 2>/dev/null || true
        kill_port_process "${CAREFOLD_BACKEND_PORT}"
        kill_port_process "${CAREFOLD_WEB_PORT}"
        rm -f "${PID_FILE}" 2>/dev/null || true
        log_success "All child processes stopped."
    fi
}

resolve_python_bin() {
    local venv_py="${PROJECT_ROOT}/backend/.venv/bin/python3"
    if [ -x "${venv_py}" ]; then
        echo "${venv_py}"
    elif command -v python3 >/dev/null 2>&1; then
        echo "$(command -v python3)"
    else
        echo "python3"
    fi
}

start_backend() {
    local bg_mode="$1"
    local log_out="${2:-/dev/stdout}"
    local log_err="${3:-/dev/stderr}"

    if is_port_in_use "${CAREFOLD_BACKEND_PORT}"; then
        log_warn "Backend port ${CAREFOLD_BACKEND_PORT} is already in use. Skipping start."
        return 0
    fi

    check_prerequisites "backend"

    log_info "Starting Backend API on http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}..."
    cd "${PROJECT_ROOT}/backend"

    local py_bin
    py_bin="$(resolve_python_bin)"

    if [ "${bg_mode}" = "true" ]; then
        nohup env PYTHONPATH="${PROJECT_ROOT}/backend/src:${PYTHONPATH:-}" \
            CAREFOLD_BACKEND_HOST="${CAREFOLD_BACKEND_HOST}" \
            CAREFOLD_BACKEND_PORT="${CAREFOLD_BACKEND_PORT}" \
            PORT="${CAREFOLD_BACKEND_PORT}" \
            "${py_bin}" -m uvicorn carefold.main:app \
            --host "${CAREFOLD_BACKEND_HOST}" \
            --port "${CAREFOLD_BACKEND_PORT}" \
            >"${log_out}" 2>"${log_err}" &
        local pid=$!
        CHILD_PIDS+=("${pid}")
        echo "backend:${pid}" >> "${PID_FILE}"
        log_success "Backend running (PID: ${pid})"
    else
        exec env PYTHONPATH="${PROJECT_ROOT}/backend/src:${PYTHONPATH:-}" \
            CAREFOLD_BACKEND_HOST="${CAREFOLD_BACKEND_HOST}" \
            CAREFOLD_BACKEND_PORT="${CAREFOLD_BACKEND_PORT}" \
            PORT="${CAREFOLD_BACKEND_PORT}" \
            "${py_bin}" -m uvicorn carefold.main:app \
            --host "${CAREFOLD_BACKEND_HOST}" \
            --port "${CAREFOLD_BACKEND_PORT}"
    fi
}

start_web() {
    local bg_mode="$1"
    local log_out="${2:-/dev/stdout}"
    local log_err="${3:-/dev/stderr}"

    if is_port_in_use "${CAREFOLD_WEB_PORT}"; then
        log_warn "Web port ${CAREFOLD_WEB_PORT} is already in use. Skipping start."
        return 0
    fi

    check_prerequisites "web"
    ensure_dependencies

    log_info "Starting Next.js Web UI on http://${CAREFOLD_WEB_HOST}:${CAREFOLD_WEB_PORT}..."
    cd "${PROJECT_ROOT}/apps/web"

    local next_bin="${PROJECT_ROOT}/apps/web/node_modules/.bin/next"
    local backend_url="http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}"

    if [ "${bg_mode}" = "true" ]; then
        if [ -x "${next_bin}" ]; then
            nohup env NEXT_TELEMETRY_DISABLED=1 \
                BACKEND_URL="${backend_url}" \
                PORT="${CAREFOLD_WEB_PORT}" \
                "${next_bin}" dev --port "${CAREFOLD_WEB_PORT}" </dev/null >"${log_out}" 2>"${log_err}" &
        else
            nohup env NEXT_TELEMETRY_DISABLED=1 \
                BACKEND_URL="${backend_url}" \
                PORT="${CAREFOLD_WEB_PORT}" \
                pnpm dev --port "${CAREFOLD_WEB_PORT}" </dev/null >"${log_out}" 2>"${log_err}" &
        fi
        local pid=$!
        CHILD_PIDS+=("${pid}")
        echo "web:${pid}" >> "${PID_FILE}"
        log_success "Web UI running (PID: ${pid})"
    else
        if [ -x "${next_bin}" ]; then
            exec env NEXT_TELEMETRY_DISABLED=1 \
                BACKEND_URL="${backend_url}" \
                PORT="${CAREFOLD_WEB_PORT}" \
                "${next_bin}" dev --port "${CAREFOLD_WEB_PORT}"
        else
            exec env NEXT_TELEMETRY_DISABLED=1 \
                BACKEND_URL="${backend_url}" \
                PORT="${CAREFOLD_WEB_PORT}" \
                pnpm dev --port "${CAREFOLD_WEB_PORT}"
        fi
    fi
}

wait_for_health() {
    local port="$1"
    local name="$2"
    local max_wait=30
    local elapsed=0

    log_info "Waiting for ${name} on port ${port} to be ready..."
    while ! is_port_in_use "${port}" && [ "${elapsed}" -lt "${max_wait}" ]; do
        sleep 0.5
        elapsed=$((elapsed + 1))
    done

    if is_port_in_use "${port}"; then
        log_success "${name} is healthy on port ${port}."
        return 0
    else
        log_warn "${name} did not become ready within ${max_wait}s on port ${port}."
        return 1
    fi
}

show_dashboard() {
    echo ""
    echo -e "${BOLD}${CYAN}==============================================================================${NC}"
    echo -e "${BOLD}${CYAN}                     Carefold AI Platform Active                              ${NC}"
    echo -e "${BOLD}${CYAN}==============================================================================${NC}"
    echo -e "  ${BOLD}Next.js Web UI:${NC}            ${GREEN}http://${CAREFOLD_WEB_HOST}:${CAREFOLD_WEB_PORT}${NC}"
    echo -e "  ${BOLD}FastAPI Backend API:${NC}       ${GREEN}http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}${NC}"
    echo -e "    ├─ Health Check:          ${BLUE}http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}/health${NC}"
    echo -e "    ├─ Interactive API Docs:  ${BLUE}http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}/docs${NC}"
    echo -e "    └─ OpenAPI Specification: ${BLUE}http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}/openapi.json${NC}"
    echo -e "${BOLD}${CYAN}==============================================================================${NC}"
    echo ""
}

cmd_all() {
    mkdir -p "${LOG_DIR}"
    : > "${PID_FILE}"
    trap cleanup_foreground INT TERM EXIT

    log_info "Starting full Carefold stack (Backend API + Web UI)..."
    start_backend "true" "${LOG_DIR}/backend.log" "${LOG_DIR}/backend.err.log"
    start_web "true" "${LOG_DIR}/web.log" "${LOG_DIR}/web.err.log"

    wait_for_health "${CAREFOLD_BACKEND_PORT}" "Backend API" || true
    wait_for_health "${CAREFOLD_WEB_PORT}" "Web UI" || true

    show_dashboard

    echo -e "${YELLOW}Logs are streaming to:${NC} ${LOG_DIR}/"
    echo -e "  - Backend API: ${LOG_DIR}/backend.log"
    echo -e "  - Web UI:      ${LOG_DIR}/web.log"
    echo ""
    echo -e "${BOLD}Press Ctrl+C to stop all components.${NC}"

    # Wait on child processes
    wait
}

cmd_start_daemon() {
    mkdir -p "${LOG_DIR}"
    : > "${PID_FILE}"

    log_info "Starting Carefold stack in background daemon mode..."
    start_backend "true" "${LOG_DIR}/backend.log" "${LOG_DIR}/backend.err.log"
    start_web "true" "${LOG_DIR}/web.log" "${LOG_DIR}/web.err.log"

    wait_for_health "${CAREFOLD_BACKEND_PORT}" "Backend API" || true
    wait_for_health "${CAREFOLD_WEB_PORT}" "Web UI" || true

    show_dashboard

    log_success "All components started in background. PIDs saved to ${PID_FILE}."
    echo -e "Use ${BOLD}./scripts/start.sh stop${NC} to terminate all background services."
    echo -e "Use ${BOLD}./scripts/start.sh status${NC} to inspect health."
}

cmd_stop() {
    log_info "Stopping Carefold components..."
    if [ -f "${PID_FILE}" ]; then
        while IFS=: read -r comp pid; do
            if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
                log_info "Stopping ${comp} (PID: ${pid})..."
                kill -TERM "${pid}" 2>/dev/null || true
            fi
        done < "${PID_FILE}"
        rm -f "${PID_FILE}"
    fi

    # Ensure ports are cleared
    kill_port_process "${CAREFOLD_BACKEND_PORT}"
    kill_port_process "${CAREFOLD_WEB_PORT}"

    log_success "All Carefold components stopped."
}

cmd_status() {
    echo -e "${BOLD}=== Carefold Service Status ===${NC}"

    printf "%-16s %-10s %-12s %-28s\n" "Component" "Port" "Status" "URL"
    printf "%-16s %-10s %-12s %-28s\n" "----------------" "----------" "------------" "----------------------------"

    local backend_status="STOPPED"
    if is_port_in_use "${CAREFOLD_BACKEND_PORT}"; then backend_status="${GREEN}RUNNING${NC}"; else backend_status="${RED}STOPPED${NC}"; fi
    printf "%-16s %-10s %-22b %-28s\n" "Backend API" "${CAREFOLD_BACKEND_PORT}" "${backend_status}" "http://${CAREFOLD_BACKEND_HOST}:${CAREFOLD_BACKEND_PORT}"

    local web_status="STOPPED"
    if is_port_in_use "${CAREFOLD_WEB_PORT}"; then web_status="${GREEN}RUNNING${NC}"; else web_status="${RED}STOPPED${NC}"; fi
    printf "%-16s %-10s %-22b %-28s\n" "Web UI" "${CAREFOLD_WEB_PORT}" "${web_status}" "http://${CAREFOLD_WEB_HOST}:${CAREFOLD_WEB_PORT}"

    echo ""
}

cmd_help() {
    echo -e "${BOLD}Usage:${NC} ./scripts/start.sh [COMMAND] [OPTIONS]"
    echo ""
    echo -e "${BOLD}Commands:${NC}"
    echo -e "  ${GREEN}all${NC}                 Start Backend API and Web UI in foreground (default)"
    echo -e "  ${GREEN}start, daemon${NC}       Start all components in background daemon mode (writes .carefold.pids)"
    echo -e "  ${GREEN}stop${NC}                Stop all running components and clear ports"
    echo -e "  ${GREEN}status${NC}              Check status and active URLs of all components"
    echo -e "  ${GREEN}backend${NC}             Start only the FastAPI Backend in foreground (on :${CAREFOLD_BACKEND_PORT})"
    echo -e "  ${GREEN}web${NC}                 Start only the Next.js Web UI in foreground (on :${CAREFOLD_WEB_PORT})"
    echo -e "  ${GREEN}help, --help, -h${NC}    Show this help message"
    echo ""
    echo -e "${BOLD}Environment Variables:${NC}"
    echo -e "  CAREFOLD_BACKEND_PORT     Port for FastAPI Backend API (default: 8010)"
    echo -e "  CAREFOLD_BACKEND_HOST     Host for FastAPI Backend API (default: 127.0.0.1)"
    echo -e "  CAREFOLD_WEB_PORT         Port for Next.js Web UI (default: 3010)"
    echo -e "  CAREFOLD_WEB_HOST         Host for Next.js Web UI (default: localhost)"
    echo -e "  PORT                      Generic fallback port override for backend or standalone commands"
    echo ""
}

# Main Dispatcher
main() {
    local cmd="${1:-all}"

    # Handle administrative, diagnostic, and help commands before any prerequisite or dependency checks
    case "${cmd}" in
        help|--help|-h)
            cmd_help
            return 0
            ;;
        status)
            cmd_status
            return 0
            ;;
        stop)
            cmd_stop
            return 0
            ;;
    esac

    # Command-specific prerequisite validation and execution
    case "${cmd}" in
        all)
            check_prerequisites "all"
            ensure_dependencies
            cmd_all
            ;;
        start|daemon)
            check_prerequisites "all"
            ensure_dependencies
            cmd_start_daemon
            ;;
        backend)
            start_backend "false"
            ;;
        web)
            if [ -n "${PORT:-}" ] && [ "${CAREFOLD_WEB_PORT_SET}" -eq 0 ]; then
                CAREFOLD_WEB_PORT="${PORT}"
            fi
            start_web "false"
            ;;
        *)
            log_error "Unknown command: ${cmd}"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
