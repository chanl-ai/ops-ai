#!/bin/sh
# make stg-deploy: staging from one image on one Fly app (deploy/fly/fly.toml), in one command. From `git archive REF`
# (default HEAD), so other builders' uncommitted files never reach the image:
#   1 build   the runtime image on Fly's remote builder, pushed as registry.fly.io/<app>:<sha>
#   2 deploy  the release command migrates every chain as the superuser, then the machine is replaced in place
#   3 grants  grants.sql from `make db-ddl` at REF (a throwaway local PostgreSQL), applied through `fly proxy`, so a table
#             the migrations just added reaches its service's runtime login
#   4 health  every process the host runs (ops_host.py --check on the machine)
#   5 walk    docs/usecases/lib/stg_click_walk.mjs signs in and opens every console page and the first row of each list
# Each step prints its seconds; any failure exits non-zero. App names come from ~/.config/ops-ai/staging.env
# (template deploy/fly/staging.env.example); secrets are read from the same directory and never printed.
# Runbook: docs/deploy/fly-staging.md.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
# App names come from staging.env (stg_env.sh), which also refuses an app outside STG_APP_PREFIX.
. "$root/deploy/fly/stg_env.sh"
app=$STG_APP
ref=${REF:-HEAD}
conf=$stg_conf
sha=$(git -C "$root" rev-parse --short=8 "$ref")
# An open release PR pins staging to its build so it can be tested and rolled back to before merge (owner, 2026-10-28).
# repo.sh snapshot writes the pin and repo.sh merge clears it; STG_UNPIN=1 deploys another build anyway.
pin=$(cat "$conf/staging-pin" 2>/dev/null || true)
if [ -n "$pin" ] && [ "$pin" != "$sha" ] && [ "${STG_UNPIN:-0}" != 1 ]; then
  echo "stg-deploy: staging is pinned to $pin for an open release PR; merge it first or set STG_UNPIN=1"; exit 2
fi
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
# fly.toml names the app and its public URLs as <your-app>; fill them in from staging.env in the archive copy.
sed -i.bak "s/<your-app>/$app/g" "$work/src/deploy/fly/fly.toml" && rm -f "$work/src/deploy/fly/fly.toml.bak"
echo "stg-deploy: $app at $sha"
started=$(date +%s)
begin=$started

if [ "${SKIP_BUILD:-0}" != 1 ]; then
  # What's new shows the release tag on a tagged commit, else the commit (next.config.ts); the archive has no .git.
  tag=$(git -C "$root" describe --tags --exact-match --match 'v*' "$sha" 2>/dev/null || true)
  fly deploy "$work/src" -c "$work/src/deploy/fly/fly.toml" -a "$app" --remote-only --build-only --push \
    --image-label "$sha" --build-arg OPS_VERSION="$tag" --build-arg OPS_COMMIT="$sha"
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
fly proxy "$proxy_port:5432" -a "$STG_DB_APP" >/dev/null 2>&1 &
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
# The machine auto-stops when idle (fly.toml min_machines_running = 0) and can stop between steps; ssh never wakes it.
wake() { for m in $(fly machine list -a "$app" -q); do fly machine start "$m" -a "$app" >/dev/null 2>&1 || true; done; }
wake
until fly ssh console -a "$app" -C "$health" >"$work/health.txt" 2>&1; do
  wake
  if [ "$(date +%s)" -ge "$deadline" ]; then cat "$work/health.txt"; exit 1; fi
  sleep 5
done
grep -E '^(ok|DOWN)' "$work/health.txt"
step "health (every process up)"
# A 200 for /login proves nothing if the page is a cached copy from the previous build: check that a script it names exists.
python3 - "$origin" <<'PY' || { echo "stg-deploy: /login references scripts this build does not serve"; exit 1; }
import re, sys, urllib.request
o = sys.argv[1]
html = urllib.request.urlopen(o + "/login", timeout=120).read().decode()
src = re.findall(r"/_next/static/[^\"'\s]+[.]js", html)
assert src, "no scripts on /login"
for s in src[:5]:
    assert urllib.request.urlopen(o + s, timeout=60).status == 200, s
PY
step "login page assets"

pair() { grep "^$1=" "$conf/staging-admin.env" | cut -d= -f2-; }
# Counted through tee, so a walk that crashes after some OK lines would pass; its exit status becomes a FAIL line.
{
  STG_ORIGIN="$origin" STG_EMAIL=$(pair OPS_BOOTSTRAP_ADMIN_EMAIL) STG_PASSWORD=$(pair OPS_BOOTSTRAP_ADMIN_PASSWORD) \
    node "$root/docs/usecases/lib/stg_click_walk.mjs" || echo "FAIL click walk exited $?"
} | tee "$work/walk.txt"
ok=$(grep -c '^OK' "$work/walk.txt" || true)
fail=$(grep -c '^FAIL' "$work/walk.txt" || true)
step "click walk ($ok OK, $fail FAIL)"
echo "stg-deploy: $app at $sha in $(( $(date +%s) - begin ))s; $origin"
[ "$fail" = 0 ] && [ "$ok" -gt 0 ]
