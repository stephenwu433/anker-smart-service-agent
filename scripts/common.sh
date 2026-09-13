#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/.venv"

log_info() {
  printf '[INFO] %s\n' "$*" >&2
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

require_venv() {
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log_error "未找到 virtual environment，请先运行 scripts/bootstrap.sh"
    return 1
  fi
}
