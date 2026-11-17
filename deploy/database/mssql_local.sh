#!/usr/bin/env bash
# A throwaway SQL Server on this machine for the store tests that run on both databases (OPS_MSSQL_SERVER and
# MSSQL_SA_PASSWORD), and a Linux client container to run them in, since a Mac has no ODBC Driver 18.
#
#   deploy/database/mssql_local.sh start                      the server container, on 127.0.0.1:14330
#   deploy/database/mssql_local.sh test <member> [pytest args]   e.g. test packages/ops_store -rs tests
#   deploy/database/mssql_local.sh stop
#
# The golden schema needs compatibility level 160, which Edge lacks, so the services' store tests refuse it here;
# deploy/database/mssql_remote.sh runs the same client against a shared SQL Server 2025 on Fly instead.
#
# On Apple silicon the server is Azure SQL Edge (arm64, SQL Server engine 15): the 2022 and 2025 amd64 images crash
# under Docker Desktop's QEMU emulation, and Edge has no Full-Text Search. The password is generated here, held only in
# the container's environment, read back from it per run, and masked in the output; it is never written to a file.
# PostgreSQL is the dev stack's (`make db-up`), reached from the client container as host.docker.internal.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SERVER=${OPS_MSSQL_CONTAINER:-ops-mssql-test}
PORT=${OPS_MSSQL_PORT:-14330}
CLIENT=ops-mssql-client:2
PG_PORT=${OPS_PG_PORT:-5477}

client_image() {
  docker image inspect "$CLIENT" >/dev/null 2>&1 && return
  docker build -q -t "$CLIENT" - >/dev/null <<'EOF'
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates build-essential libpq-dev git \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 mssql-tools18 unixodbc unixodbc-dev \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
# The venv lives in a volume, never in the mounted tree, whose .venv is the host's.
ENV UV_PROJECT_ENVIRONMENT=/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.12 \
    PYTHONDONTWRITEBYTECODE=1
# The repository scans (ops_store's baseline history) run git on the mounted tree, which another user owns.
RUN git config --system --add safe.directory '*'
WORKDIR /src
EOF
}

# The client container gets a copy of the tree made here, not a bind mount of it. Docker Desktop's file sharing served
# stale files through the mount (a file cut off at line 158 of 189, a migration at 3777 bytes of 5022), so a run tested
# old code and said nothing. The files are read on the host, by git's list of tracked and untracked ones, and streamed
# into a throwaway volume; images are left out. A worktree's `.git` file is copied too (the git directory it names is
# mounted at the same path below); a main checkout's `.git` folder is mounted read-only.
sync_tree() { # <volume> <root>
  docker volume create "$1" >/dev/null
  python3 - "$2" <<'PY' | docker run -i --rm -v "$1":/src "$CLIENT" sh -c 'find /src -mindepth 1 -delete; tar -x -C /src'
import os, subprocess, sys, tarfile
root = sys.argv[1]
names = subprocess.run(["git", "-C", root, "ls-files", "-z", "-c", "-o", "--exclude-standard"], capture_output=True, check=True).stdout.split(b"\0")
skip = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".mp4")
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
    for raw in sorted(set(n for n in names if n)):
        name = raw.decode()
        path = os.path.join(root, name)
        if name.lower().endswith(skip) or not os.path.lexists(path) or os.path.isdir(path):
            continue
        tar.add(path, arcname=name, recursive=False)
    if os.path.isfile(os.path.join(root, ".git")):
        tar.add(os.path.join(root, ".git"), arcname=".git", recursive=False)
PY
}

case "${1:-}" in
  sync-self-test)
    # Plants a change after a copy, a file that was deleted and an image, and sees the copy follow the host.
    client_image
    t=$(mktemp -d); v=ops-mssql-src-selftest-$$
    trap 'rm -rf "$t"; docker volume rm -f "$v" >/dev/null 2>&1' EXIT
    git -C "$t" init -q; printf 'one\n' > "$t/a.py"; printf 'x\n' > "$t/gone.py"; printf 'img' > "$t/p.png"
    git -C "$t" add . ; sync_tree "$v" "$t"
    printf 'one\ntwo\nthree\n' > "$t/a.py"; rm "$t/gone.py"; printf 'new\n' > "$t/new.py"
    sync_tree "$v" "$t"
    got=$(docker run --rm -v "$v":/src:ro "$CLIENT" sh -c 'cd /src; wc -l < a.py; ls')
    case "$got" in *3*a.py*new.py*) ;; *) echo "sync-self-test: FAILED, the copy did not follow the host: $got" >&2; exit 1 ;; esac
    case "$got" in *gone.py*|*p.png*) echo "sync-self-test: FAILED, a deleted file or an image is in the copy: $got" >&2; exit 1 ;; esac
    echo "sync-self-test: the copy follows the host" ;;
  start)
    if docker ps --format '{{.Names}}' | grep -qx "$SERVER"; then echo "$SERVER: running on 127.0.0.1:$PORT"; exit 0; fi
    # Letters and digits only, so the password cannot hide behind URL encoding in a traceback.
    MSSQL_SA_PASSWORD=$(python3 -c 'import secrets,string;p=[secrets.choice(s) for s in (string.ascii_uppercase,string.ascii_lowercase,string.digits) for _ in range(8)];secrets.SystemRandom().shuffle(p);print("".join(p))') \
      docker run -d --name "$SERVER" --restart unless-stopped -e ACCEPT_EULA=1 -e MSSQL_PID=Developer -e MSSQL_SA_PASSWORD \
      -p "127.0.0.1:$PORT:1433" mcr.microsoft.com/azure-sql-edge:latest >/dev/null
    until docker logs "$SERVER" 2>&1 | grep -q "ready for client"; do sleep 2; done
    echo "$SERVER: running on 127.0.0.1:$PORT"
    ;;
  client) client_image ;;
  test)
    shift
    member=${1:?member folder, e.g. packages/ops_store}
    shift
    client_image
    # deploy/database/mssql_remote.sh points the run at the shared Fly server through its proxy: OPS_MSSQL_ADDR is
    # that address as the client container sees it, OPS_MSSQL_PASSWORD_FILE the file holding its SA password.
    if [ -n "${OPS_MSSQL_PASSWORD_FILE:-}" ]; then pw=$(cat "$OPS_MSSQL_PASSWORD_FILE")
    else pw=$(docker exec "$SERVER" printenv MSSQL_SA_PASSWORD); fi
    addr=${OPS_MSSQL_ADDR:-host.docker.internal,$PORT}
    db=ops_test_mssql_$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')
    # Tests that start their own OPA (ops_service_kit.opa_server) need docker, which the client container has not: this
    # run starts one on the host instead and hands it over as OPS_INFRA=external, never the stack's shared OPA.
    extra=()
    if grep -rqs "opa_server" "$ROOT/$member/tests"; then
      cid=$(docker run -d --rm -p 127.0.0.1::8181 -v "$ROOT/services/tools-service/policy:/policy:ro" \
        openpolicyagent/opa:1.21.4 run --server --addr 0.0.0.0:8181 --log-level error /policy)
      extra+=(-e OPS_INFRA=external -e "OPS_OPA_URL=http://host.docker.internal:$(docker port "$cid" 8181/tcp | head -1 | cut -d: -f2)")
    fi
    # A worktree's .git names the main checkout's git directory by its host path, so that is mounted at the same path.
    gitdir=$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)
    if [ "$gitdir" = "$ROOT/.git" ]; then extra+=(-v "$gitdir:/src/.git:ro"); else extra+=(-v "$gitdir:$gitdir:ro"); fi
    src=ops-mssql-src-$$
    trap 'docker rm -f "${cid:-}" >/dev/null 2>&1; docker volume rm -f "$src" >/dev/null 2>&1' EXIT
    sync_tree "$src" "$ROOT"
    # The password goes in by name from this process's environment, so it is not on docker's command line.
    MSSQL_SA_PASSWORD="$pw" docker run --rm -v "$src":/src -v ops-mssql-venv:/venv -v ops-mssql-uvcache:/root/.cache/uv \
      -e MSSQL_SA_PASSWORD -e OPS_MSSQL_SERVER="$addr" -e OPS_TEST_HANG_SECONDS ${extra[@]+"${extra[@]}"} \
      -e OPS_DATABASE_URL="postgresql+asyncpg://ops:ops@host.docker.internal:$PG_PORT/$db" \
      -e OPS_TEST_DATABASE_URL="postgresql+asyncpg://ops:ops@host.docker.internal:$PG_PORT/$db" -w "/src/$member" "$CLIENT" \
      sh -c 'uv sync -q --frozen --all-packages && /venv/bin/python /src/scripts/test_db.py "$OPS_DATABASE_URL" \
        && /venv/bin/python -m pytest -p no:cacheprovider "$@"' sh "$@" 2>&1 | sed "s/$pw/***/g"
    ;;
  stop) docker rm -f "$SERVER" >/dev/null && echo "$SERVER: removed" ;;
  *) sed -n 2,15p "$0"; exit 2 ;;
esac
