#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

MONGOD_BIN="${MONGOD_BIN:-mongod}"
MONGODB_PORT="${MONGODB_PORT:-27017}"
MONGODB_DATA_DIR="${MONGODB_DATA_DIR:-${PROJECT_ROOT}/data/mongodb}"

if ! command -v "${MONGOD_BIN}" >/dev/null 2>&1; then
  log_error "找不到 MongoDB server command: ${MONGOD_BIN}"
  exit 1
fi

if [[ ! "${MONGODB_PORT}" =~ ^[0-9]+$ ]]; then
  log_error "MONGODB_PORT 必须是数字"
  exit 1
fi

mkdir -p "${MONGODB_DATA_DIR}"
log_info "MongoDB data directory: ${MONGODB_DATA_DIR}"
exec "${MONGOD_BIN}" \
  --dbpath "${MONGODB_DATA_DIR}" \
  --bind_ip 127.0.0.1 \
  --port "${MONGODB_PORT}"
