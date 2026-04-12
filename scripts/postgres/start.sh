#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PG_HOME="$ROOT_DIR/.postgres"
PG_DATA="$PG_HOME/data"
PG_LOGS="$PG_HOME/logs"
PG_PORT="${PG_PORT:-55432}"
PG_BIN="$(brew --prefix postgresql@16)/bin"

if [[ ! -f "$PG_DATA/PG_VERSION" ]]; then
  echo "PostgreSQL data directory is missing. Run install_local_postgres.sh first."
  exit 1
fi

mkdir -p "$PG_LOGS"
"$PG_BIN/pg_ctl" -D "$PG_DATA" -l "$PG_LOGS/postgres.log" -o "-p $PG_PORT" start
