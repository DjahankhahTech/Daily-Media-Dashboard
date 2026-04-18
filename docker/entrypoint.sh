#!/bin/sh
# Fly.io entrypoint: bootstrap SQLite on first boot, then hand off to uvicorn.
#
# On a fresh Fly volume the DB file won't exist. If CCMD_DEMO=1 we load the
# 50-article canned dataset; otherwise we just create empty tables + seed
# CCMDs/feeds. On subsequent boots the DB is already there — we never wipe
# it, so analyst notes + OIC flags survive deploys.
set -eu

DATA_DIR="${CCMD_DATA_DIR:-/data}"
DB_FILE="${DATA_DIR}/dashboard.db"
HOST="${CCMD_HOST:-0.0.0.0}"
PORT="${CCMD_PORT:-8080}"

mkdir -p "$DATA_DIR" "$DATA_DIR/raw_feeds"

if [ ! -f "$DB_FILE" ]; then
  if [ "${CCMD_DEMO:-0}" = "1" ]; then
    echo "[entrypoint] no DB at $DB_FILE — bootstrapping demo dataset (no MDM)"
    # --no-mdm keeps first boot fast: MDM runs sentence-transformers on CPU
    # which OOMs a 1 GB VM when batched over 50 articles. The analyst
    # triggers MDM per-article from the UI at runtime instead.
    dashboard demo --load-only --no-mdm
  else
    echo "[entrypoint] no DB at $DB_FILE — initializing empty schema"
    dashboard init-db
  fi
else
  echo "[entrypoint] reusing existing DB at $DB_FILE"
fi

echo "[entrypoint] serving on ${HOST}:${PORT}"
exec dashboard serve --host "$HOST" --port "$PORT"
