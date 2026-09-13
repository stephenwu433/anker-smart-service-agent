#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"
require_venv

cd "${PROJECT_ROOT}"
exec "${VENV_DIR}/bin/pytest" "$@"
