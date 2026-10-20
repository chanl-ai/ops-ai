#!/bin/sh
# Proves c-369 on this machine: test runs and builds clean up after themselves. PASS or FAIL per check; exit 1 on any.
# Touches only what it makes: one scratch database per sweep check, one container, one throwaway image.
#   sh scripts/disk_proof.sh
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PG=${OPS_PG_CONTAINER:-ops-runtime-postgres-1}
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=1; fi; }
sql() { docker exec "$PG" psql -U ops -d postgres -At -c "$1"; }
count() { sql "SELECT count(*) FROM pg_database WHERE datname ~ '$1'"; }

# 1 The gateway ownership test makes a scratch database per test and drops each one.
before=$(count '^ops_tools_p[0-9]+_')
db=postgresql+asyncpg://ops:ops@localhost:5477/ops_c369_proof
(cd "$ROOT/services/agents-service" && uv run --quiet python ../../scripts/test_db.py "$db" >/dev/null 2>&1 \
  && OPS_TEST_DATABASE_URL=$db OPS_DATABASE_URL=$db uv run --quiet pytest -q -p no:cacheprovider tests/gateway/test_tools_ownership.py >/dev/null 2>&1)
ran=$?
sql "DROP DATABASE IF EXISTS ops_c369_proof WITH (FORCE)" >/dev/null
check "1 the gateway ownership tests pass and leave no scratch database ($before before, $(count '^ops_tools_p[0-9]+_') after)" $(( ran + ($(count '^ops_tools_p[0-9]+_') != before) ))

# 2 The sweep drops a dead run's database and keeps a live one's.
sleep 60 & dead=$!; kill $dead; wait $dead 2>/dev/null
sql "CREATE DATABASE ops_usecase_r${dead}_c369aa" >/dev/null
sql "CREATE DATABASE ops_usecase_r$$_c369bb" >/dev/null
uv run --quiet --project "$ROOT" python "$ROOT/scripts/scratch_db_sweep.py" >/dev/null
gone=$(count "^ops_usecase_r${dead}_c369aa$")
kept=$(count "^ops_usecase_r$$_c369bb$")
sql "DROP DATABASE IF EXISTS ops_usecase_r$$_c369bb" >/dev/null
check "2 the sweep drops a dead run's database (pid $dead) and keeps a live run's (pid $$)" $(( (gone != 0) + (kept != 1) ))

# 3 A proof's database container goes with its volume (docker rm -fv).
cid=$(docker run -d -e POSTGRES_PASSWORD=x postgres:17-alpine)
vol=$(docker inspect -f '{{range .Mounts}}{{.Name}}{{end}}' "$cid")
docker rm -fv "$cid" >/dev/null
docker volume inspect "$vol" >/dev/null 2>&1
check "3 removing a proof's container with -v removes its anonymous volume ($vol)" $(( $? == 0 ))

# 4 An isolated stack's down removes its own volume; the shared stack's keeps its.
make -s -C "$ROOT" -n db-down ISOLATED=1 | grep -q -- "--volumes" && ! make -s -C "$ROOT" -n db-down | grep -q -- "--volumes"
check "4 make db-down ISOLATED=1 removes the isolated volume, make db-down keeps the shared one" $?

# 5 The build cache is pruned down to the cap: a throwaway image's cache, private once the image is gone, goes.
work=$(mktemp -d)
printf 'FROM postgres:17-alpine\nRUN head -c 200000000 /dev/urandom > /blob-%s\n' "$$" > "$work/Dockerfile"
docker build -q -t ops-c369-cache:$$ "$work" >/dev/null && docker rmi ops-c369-cache:$$ >/dev/null
rm -r "$work"
before=$(docker buildx du 2>/dev/null | sed -n 's/^Private:[[:space:]]*//p')
out=$(OPS_BUILD_CACHE_CAP=0.1 sh "$ROOT/deploy/images/prune_build_cache.sh")
after=$(docker buildx du 2>/dev/null | sed -n 's/^Private:[[:space:]]*//p')
echo "  $out"
check "5 past the cap (forced to 0.1 GB) the build cache prune frees the throwaway build ($before -> $after)" $([ "$before" != "$after" ] && echo 0 || echo 1)

# 6 make health warns over the Docker disk threshold.
OPS_DOCKER_DISK_WARN=1 "$ROOT/scripts/stack.sh" health 2>&1 | grep -q "WARNING: the Docker disk is"
check "6 make health warns when the Docker disk is over the threshold (forced to 1%)" $?

[ "$failed" = 0 ] && echo "disk proof: all checks passed" || echo "disk proof: a check failed"
exit $failed
