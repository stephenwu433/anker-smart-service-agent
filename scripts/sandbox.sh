#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"
require_venv

EXPERIMENT="${1:-${PROJECT_ROOT}/sandbox/experiments/example_health_check.py}"
if [[ ! -f "${EXPERIMENT}" ]]; then
  log_error "experiment 文件不存在: ${EXPERIMENT}"
  exit 1
fi

export APP_CONFIG_FILE="${APP_CONFIG_FILE:-${PROJECT_ROOT}/config/development.env}"
export SANDBOX_OUTPUT_DIR="${PROJECT_ROOT}/sandbox/output"
mkdir -p "${SANDBOX_OUTPUT_DIR}"

cd "${PROJECT_ROOT}"
exec "${VENV_DIR}/bin/python" "${EXPERIMENT}"
