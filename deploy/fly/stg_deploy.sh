#!/bin/sh
# make stg-deploy: staging from one image on one Fly app (deploy/fly/fly.toml), in one command. From `git archive REF`
# (default HEAD), so other builders' uncommitted files never reach the image:
#   1 build   the runtime image on Fly's remote builder, pushed as registry.fly.io/<app>:<sha>
#   2 deploy  the release command migrates every chain as the superuser, then the machine is replaced in place
#   3 grants  grants.sql from `make db-ddl` at REF (a throwaway local PostgreSQL), applied through `fly proxy`, so a table
#             the migrations just added reaches its service's runtime login
#   4 health  every process the host runs (ops_host.py --check on the machine)
#   5 walk    docs/usecases/lib/stg_click_walk.mjs signs in and opens every console page and the first row of each list
# Each step prints its seconds; any failure exits non-zero. Secrets are read from ~/.config/ops-ai/ and never printed.
# Runbook: docs/deploy/fly-staging.md.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
app=${STG_APP:-<your-app>-one}
ref=${REF:-HEAD}
conf=${OPS_STAGING_CONFIG:-$HOME/.config/ops-ai}
case "$app" in <your-app>*) ;; *) echo "stg-deploy: only <your-app>* apps"; exit 2 ;; esac
sha=$(git -C "$root" rev-parse --short=8 "$ref")
origin="https://$app.fly.dev"
image="registry.fly.io/$app:$sha"
work=$(mktemp -d)
ddl_db="ops-stg-ddl-$$"
proxy=""
cleanup() {
  [ -z "$proxy" ] || kill "$proxy" 2>/dev/null || true
  docker rm -f "$ddl_db" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT INT TERM
step() { now=$(date +%s); echo "stg-deploy: $1 took $((now - started))s"; started=$now; }

mkdir -p "$work/src"
git -C "$root" archive "$sha" | tar -x -C "$work/src"
echo "stg-deploy: $app at $sha"
started=$(date +%s)
begin=$started

if [ "${SKIP_BUILD:-0}" != 1 ]; then
  fly deploy "$work/src" -c "$work/src/deploy/fly/fly.toml" -a "$app" --remote-only --build-only --push \
    --image-label "$sha"
  step build
fi

fly deploy "$work/src" -c "$work/src/deploy/fly/fly.toml" -a "$app" --image "$image" --ha=false \
  --wait-timeout 10m
step "deploy (release command and machine)"

# grants.sql at REF, built on a throwaway server of the cluster's major version.
docker run -d --rm --name "$ddl_db" -e POSTGRES_PASSWORD=ddl -p 127.0.0.1::5432 postgres:18-alpine >/dev/null
ddl_port=$(docker port "$ddl_db" 5432/tcp | head -1 | sed 's/.*://')
until docker exec "$ddl_db" pg_isready -U postgres -q 2>/dev/null; do sleep 1; done
make -s -C "$root" db-ddl SERVER="postgresql://postgres:ddl@127.0.0.1:$ddl_port/postgres" REF="$sha" OUT="$work/ddl" \
  >"$work/ddl.log" 2>&1 || { tail -20 "$work/ddl.log"; exit 1; }
proxy_port=${STG_PROXY_PORT:-15433}
fly proxy "$proxy_port:5432" -a <your-app>-db >/dev/null 2>&1 &
proxy=$!
for _ in $(seq 30); do nc -z 127.0.0.1 "$proxy_port" 2>/dev/null && break; sleep 1; done
# The attach's URL with the proxy's address; read from the file, never echoed.
superuser=$(sed -E "s#@[^/]+/#@127.0.0.1:$proxy_port/#; s#\?.*##" "$conf/staging-db-url.txt")
psql -q -v ON_ERROR_STOP=1 "$superuser" -f "$work/ddl/grants.sql" >"$work/grants.log" 2>&1 \
  || { tail -20 "$work/grants.log"; exit 1; }
kill "$proxy" 2>/dev/null || true
proxy=""
step grants

# `fly deploy` returns once the machine starts; the host then starts each process in turn. Wait for all of them.
health="python3 /app/deploy/host/ops_host.py --check /app/deploy/fly/processes.toml"
deadline=$(( $(date +%s) + ${STG_HEALTH_TIMEOUT:-300} ))
until fly ssh console -a "$app" -C "$health" >"$work/health.txt" 2>&1; do
  if [ "$(date +%s)" -ge "$deadline" ]; then cat "$work/health.txt"; exit 1; fi
  sleep 5
done
grep -E '^(ok|DOWN)' "$work/health.txt"
step "health (every process up)"

pair() { grep "^$1=" "$conf/staging-admin.env" | cut -d= -f2-; }
STG_ORIGIN="$origin" STG_EMAIL=$(pair OPS_BOOTSTRAP_ADMIN_EMAIL) STG_PASSWORD=$(pair OPS_BOOTSTRAP_ADMIN_PASSWORD) \
  node "$root/docs/usecases/lib/stg_click_walk.mjs" | tee "$work/walk.txt"
ok=$(grep -c '^OK' "$work/walk.txt" || true)
fail=$(grep -c '^FAIL' "$work/walk.txt" || true)
step "click walk ($ok OK, $fail FAIL)"
echo "stg-deploy: $app at $sha in $(( $(date +%s) - begin ))s; $origin"
[ "$fail" = 0 ] && [ "$ok" -gt 0 ]
