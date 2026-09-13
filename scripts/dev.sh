#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"
require_venv

CONFIG_FILE="${1:-${PROJECT_ROOT}/config/development.env}"
if [[ ! -f "${CONFIG_FILE}" ]]; then
  log_error "config 文件不存在: ${CONFIG_FILE}"
  exit 1
fi

cd "${PROJECT_ROOT}"
export APP_CONFIG_FILE="${CONFIG_FILE}"
exec "${VENV_DIR}/bin/python" -m smart_service_agent.cli
