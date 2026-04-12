#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PG_DATA="$ROOT_DIR/.postgres/data"
PG_BIN="$(brew --prefix postgresql@16)/bin"

if [[ ! -f "$PG_DATA/PG_VERSION" ]]; then
  echo "No project-local PostgreSQL data directory found."
  exit 1
fi

"$PG_BIN/pg_ctl" -D "$PG_DATA" status
