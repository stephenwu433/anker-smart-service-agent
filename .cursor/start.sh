#!/usr/bin/env bash
# Per-boot startup: bring up a local MongoDB for the Smart Service Agent API.
# Idempotent: detects an already-running server, clears stale lock/socket state
# from an unclean shutdown, waits for readiness, then returns.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

MONGODB_PORT="${MONGODB_PORT:-27017}"
MONGODB_DATA_DIR="${MONGODB_DATA_DIR:-${PROJECT_ROOT}/data/mongodb}"
MONGODB_LOG="${MONGODB_LOG:-${PROJECT_ROOT}/data/mongod.log}"
MONGODB_URI="mongodb://127.0.0.1:${MONGODB_PORT}"

is_ready() {
  mongosh --quiet --eval 'db.runCommand({ping:1}).ok' "${MONGODB_URI}" >/dev/null 2>&1
}

if is_ready; then
  echo "[start] MongoDB already running on ${MONGODB_URI}"
  exit 0
fi

mkdir -p "${MONGODB_DATA_DIR}"

# A leftover lock from a previous unclean shutdown blocks startup; safe to
# remove only because the readiness probe above confirmed no live server.
if [[ -f "${MONGODB_DATA_DIR}/mongod.lock" ]]; then
  rm -f "${MONGODB_DATA_DIR}/mongod.lock"
fi

echo "[start] launching mongod (dbpath=${MONGODB_DATA_DIR}, port=${MONGODB_PORT})"
mongod \
  --dbpath "${MONGODB_DATA_DIR}" \
  --bind_ip 127.0.0.1 \
  --port "${MONGODB_PORT}" \
  --logpath "${MONGODB_LOG}" \
  --fork >/dev/null

for _ in $(seq 1 30); do
  if is_ready; then
    echo "[start] MongoDB ready on ${MONGODB_URI}"
    exit 0
  fi
  sleep 1
done

echo "[start] ERROR: MongoDB did not become ready in time" >&2
exit 1
