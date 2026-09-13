#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"
require_venv

cd "${PROJECT_ROOT}"
log_info "运行 Ruff lint"
"${VENV_DIR}/bin/ruff" check .
log_info "运行 Ruff format check"
"${VENV_DIR}/bin/ruff" format --check .
log_info "运行 pytest"
"${VENV_DIR}/bin/pytest"
