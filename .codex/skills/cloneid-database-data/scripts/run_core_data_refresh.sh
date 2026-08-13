#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORKDIR=$(pwd)
USER_NAME=${USER_NAME:-$(id -un)}

REPOSITORY_ROOT=$SCRIPT_DIR
while [[ "$REPOSITORY_ROOT" != "/" ]]; do
  if [[ -f "$REPOSITORY_ROOT/scripts/agentRrunner.sh" && -f "$REPOSITORY_ROOT/AGENTS.md" ]]; then
    break
  fi
  REPOSITORY_ROOT=$(dirname "$REPOSITORY_ROOT")
done
if [[ "$REPOSITORY_ROOT" == "/" ]]; then
  echo "Could not locate the cloneID repository root." >&2
  exit 1
fi

MYSQLCLIENT_LIBRARY=${CLONEID_MYSQLCLIENT_LIBRARY:-/app/eb/software/Anaconda3/2024.02-1/lib/libmysqlclient.so.21}
if [[ -f "$MYSQLCLIENT_LIBRARY" ]]; then
  DRIVER_BIND="$MYSQLCLIENT_LIBRARY:/usr/lib/x86_64-linux-gnu/libmysqlclient.so.21"
  if [[ -n "${BINDS:-}" ]]; then
    export BINDS="$BINDS -B $DRIVER_BIND"
  else
    CACHE_DIR="$WORKDIR/.cache"
    TMP_DIR="$WORKDIR/.tmp"
    mkdir -p "$CACHE_DIR" "$TMP_DIR"
    BIND_PATHS="/home/$USER_NAME,/share,/etc/passwd,/etc/group,$SCRIPT_DIR,$WORKDIR,$CACHE_DIR,$TMP_DIR,$DRIVER_BIND"
    export BINDS="-B $BIND_PATHS"
  fi
fi

exec "$REPOSITORY_ROOT/scripts/agentRrunner.sh" "$SCRIPT_DIR/refresh_core_data.R" "$@"
