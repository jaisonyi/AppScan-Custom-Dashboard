#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PG_HOME="$ROOT_DIR/.postgres"
PG_DATA="$PG_HOME/data"
PG_LOGS="$PG_HOME/logs"
PG_PORT="${PG_PORT:-55432}"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install PostgreSQL binaries."
  exit 1
fi

if ! brew list postgresql@16 >/dev/null 2>&1; then
  echo "Installing postgresql@16 via Homebrew..."
  brew install postgresql@16
fi

PG_BIN="$(brew --prefix postgresql@16)/bin"
INITDB="$PG_BIN/initdb"
PG_CTL="$PG_BIN/pg_ctl"

mkdir -p "$PG_DATA" "$PG_LOGS"

if [[ ! -f "$PG_DATA/PG_VERSION" ]]; then
  echo "Initializing PostgreSQL cluster in $PG_DATA"
  "$INITDB" -D "$PG_DATA" -U postgres --auth=trust
fi

CONF_FILE="$PG_DATA/postgresql.conf"
if ! grep -q "^port = $PG_PORT" "$CONF_FILE"; then
  {
    echo ""
    echo "# Project-local ASPM PostgreSQL settings"
    echo "port = $PG_PORT"
    echo "listen_addresses = '127.0.0.1'"
  } >> "$CONF_FILE"
fi

if ! grep -q "^unix_socket_directories = '$PG_HOME'" "$CONF_FILE"; then
  echo "unix_socket_directories = '$PG_HOME'" >> "$CONF_FILE"
fi

if ! "$PG_CTL" -D "$PG_DATA" status >/dev/null 2>&1; then
  echo "Starting PostgreSQL on port $PG_PORT"
  "$PG_CTL" -D "$PG_DATA" -l "$PG_LOGS/postgres.log" -o "-p $PG_PORT" start
fi

"$PG_BIN/createdb" -h 127.0.0.1 -p "$PG_PORT" -U postgres aspm >/dev/null 2>&1 || true

echo "Local PostgreSQL is ready."
echo "DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:$PG_PORT/aspm"
