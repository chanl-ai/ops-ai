#!/usr/bin/env bash
# A throwaway SQL Server on this machine for the store tests that run on both databases (OPS_MSSQL_SERVER and
# MSSQL_SA_PASSWORD), and a Linux client container to run them in, since a Mac has no ODBC Driver 18.
#
#   deploy/database/mssql_local.sh start                      the server container, on 127.0.0.1:14330
#   deploy/database/mssql_local.sh test <member> [pytest args]   e.g. test packages/ops_store -rs tests
#   deploy/database/mssql_local.sh stop
#
# On Apple silicon the server is Azure SQL Edge (arm64, SQL Server engine 15): the 2022 and 2025 amd64 images crash
# under Docker Desktop's QEMU emulation, and Edge has no Full-Text Search. The password is generated here, held only in
# the container's environment, read back from it per run, and masked in the output; it is never written to a file.
# PostgreSQL is the dev stack's (`make db-up`), reached from the client container as host.docker.internal.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SERVER=${OPS_MSSQL_CONTAINER:-ops-mssql-test}
PORT=${OPS_MSSQL_PORT:-14330}
CLIENT=ops-mssql-client
PG_PORT=${OPS_PG_PORT:-5477}

client_image() {
  docker image inspect "$CLIENT" >/dev/null 2>&1 && return
  docker build -q -t "$CLIENT" - >/dev/null <<'EOF'
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates build-essential libpq-dev \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 mssql-tools18 unixodbc unixodbc-dev \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
# The venv lives in a volume, never in the mounted tree, whose .venv is the host's.
ENV UV_PROJECT_ENVIRONMENT=/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.12 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
EOF
}

case "${1:-}" in
  start)
    if docker ps --format '{{.Names}}' | grep -qx "$SERVER"; then echo "$SERVER: running on 127.0.0.1:$PORT"; exit 0; fi
    # Letters and digits only, so the password cannot hide behind URL encoding in a traceback.
    MSSQL_SA_PASSWORD=$(python3 -c 'import secrets,string;p=[secrets.choice(s) for s in (string.ascii_uppercase,string.ascii_lowercase,string.digits) for _ in range(8)];secrets.SystemRandom().shuffle(p);print("".join(p))') \
      docker run -d --name "$SERVER" --restart unless-stopped -e ACCEPT_EULA=1 -e MSSQL_PID=Developer -e MSSQL_SA_PASSWORD \
      -p "127.0.0.1:$PORT:1433" mcr.microsoft.com/azure-sql-edge:latest >/dev/null
    until docker logs "$SERVER" 2>&1 | grep -q "ready for client"; do sleep 2; done
    echo "$SERVER: running on 127.0.0.1:$PORT"
    ;;
  test)
    shift
    member=${1:?member folder, e.g. packages/ops_store}
    shift
    client_image
    pw=$(docker exec "$SERVER" printenv MSSQL_SA_PASSWORD)
    db=ops_test_mssql_$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')
    docker run --rm -v "$ROOT":/src:ro -v ops-mssql-venv:/venv -v ops-mssql-uvcache:/root/.cache/uv \
      -e MSSQL_SA_PASSWORD="$pw" -e OPS_MSSQL_SERVER="host.docker.internal,$PORT" \
      -e OPS_DATABASE_URL="postgresql+asyncpg://ops:ops@host.docker.internal:$PG_PORT/$db" \
      -e OPS_TEST_DATABASE_URL="postgresql+asyncpg://ops:ops@host.docker.internal:$PG_PORT/$db" -w "/src/$member" "$CLIENT" \
      sh -c 'uv sync -q --frozen --all-packages && /venv/bin/python /src/scripts/test_db.py "$OPS_DATABASE_URL" \
        && /venv/bin/python -m pytest -p no:cacheprovider "$@"' sh "$@" 2>&1 | sed "s/$pw/***/g"
    ;;
  stop) docker rm -f "$SERVER" >/dev/null && echo "$SERVER: removed" ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
