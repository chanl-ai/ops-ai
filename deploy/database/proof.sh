#!/bin/sh
# Proves the DBA scripts on a throwaway PostgreSQL of its own (container ops-schema-proof on :15499, removed at the end;
# never the dev stack's). Prints PASS or FAIL per check and exits 1 on any FAIL.
#   1 the baseline applied to an empty database equals what the chains build (Alembic, online)
#   2 an older ref's baseline, seeded with rows in every table a step fills, plus the upgrade to this ref equals what
#     the chains build
#   2a each fill wrote the values the store would (a step that skips its fill offline fails here)
#   2c downgrade.sql then upgrade.sql again keeps every seeded row and fills them the same way
#   3 a runtime role reads and writes its own tables (and the ones its code declares) and is refused DDL
#   4 drift is green on a clean install, red on a hand-made index, green again once it is dropped
#   5 a service refuses to start on a database whose recorded version is behind its chain
#   sh deploy/database/proof.sh [FROM]     KEEP=1 leaves the container and output; TO=. proves this folder as it is
# FROM defaults to the first commit after every ONLINE_ONLY revision in schema.py (agents 0115), since an offline
# upgrade across one is refused; docs/deploy/database.md gives the path from older releases.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# The offline-upgrade floor; ci.yml reads this line.
FLOOR=874530fa
FROM=${1:-$FLOOR}
TO=${TO:-HEAD}
NAME=ops-schema-proof
PORT=${OPS_SCHEMA_PROOF_PORT:-15499}
SERVER=postgresql://postgres:proof@localhost:$PORT/postgres
OUT=$(mktemp -d)
TOOL="uv run --quiet --project $ROOT python $ROOT/deploy/database/schema.py"
failed=0
check() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=1; fi; }
psql_as() { url=$1; shift; docker exec -i $NAME psql -v ON_ERROR_STOP=1 -q "$url" "$@"; }
cleanup() { [ "${KEEP:-0}" = 1 ] && { echo "proof: kept $NAME and $OUT"; return; }; docker rm -fv $NAME >/dev/null 2>&1 || true; rm -r "$OUT"; }
trap cleanup EXIT

docker rm -fv $NAME >/dev/null 2>&1 || true
docker run -d --name $NAME -e POSTGRES_PASSWORD=proof -p 127.0.0.1:$PORT:5432 pgvector/pgvector:pg17 >/dev/null
# The image first runs a temporary server on its socket only while it initialises; wait for the real one on TCP.
until docker exec $NAME pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do sleep 1; done

# Installs a baseline as a DBA would: roles as the superuser, then the bundle and grants as the migrator.
install() {
  dir=$1 db=$2
  psql_as "postgresql://postgres:proof@localhost/postgres" < "$dir/roles.sql" 2>&1 | grep -v "^NOTICE" || true
  for role in ops_migrator $(sed -n 's/.*"runtimeRole": "\([a-z_]*\)".*/\1/p' "$dir/manifest.json"); do
    psql_as "postgresql://postgres:proof@localhost/postgres" -c "ALTER ROLE $role PASSWORD 'proof'"
  done
  psql_as "postgresql://postgres:proof@localhost/postgres" -c "CREATE DATABASE $db OWNER ops_migrator"
  psql_as "postgresql://postgres:proof@localhost/$db" -c "CREATE EXTENSION IF NOT EXISTS vector"
  psql_as "postgresql://ops_migrator:proof@localhost/$db" < "$dir/bundle.sql" >/dev/null
  psql_as "postgresql://ops_migrator:proof@localhost/$db" < "$dir/grants.sql" >/dev/null
}

echo "proof: baseline at $TO and at $FROM, the upgrade between them"
$TOOL ddl --server "$SERVER" --out "$OUT/head" --ref "$TO" | head -1
$TOOL ddl --server "$SERVER" --out "$OUT/from" --ref "$FROM" | head -1
$TOOL upgrade-sql --from "$FROM" --to "$TO" --out "$OUT/upgrade"

echo "proof: the chains at $TO, run by Alembic"
docker exec $NAME psql -q -U postgres -c "CREATE DATABASE migrated"
if [ "$TO" = . ]; then
  ln -s "$ROOT" "$OUT/checkout"
else
  mkdir -p "$OUT/checkout" && (cd "$ROOT" && git archive "$TO" | tar -x -C "$OUT/checkout")
  (cd "$OUT/checkout" && VIRTUAL_ENV= uv sync --frozen --no-dev --quiet)
fi
OPS_ROOT="$OUT/checkout" ALEMBIC="$OUT/checkout/.venv/bin/alembic" OPS_MIGRATE_SKIP_BOOTSTRAP=1 \
  OPS_DATABASE_URL="postgresql+asyncpg://postgres:proof@localhost:$PORT/migrated" sh "$ROOT/deploy/images/migrate.sh" >/dev/null

install "$OUT/head" fresh
set +e
$TOOL diff "postgresql://postgres:proof@localhost:$PORT/migrated" "postgresql://postgres:proof@localhost:$PORT/fresh"
check "1 the HEAD baseline on an empty database equals the Alembic-built schema" $?

install "$OUT/from" upgraded
# Rows in every table a step after FROM fills (as the superuser, past each table's forced policy), with the values the
# store's own code works out for them checked below; a step that adds a NOT NULL column with no offline fill, or
# leaves a nullable one empty, fails here instead of on a DBA's first real install.
as_super="postgresql://postgres:proof@localhost/upgraded"
psql_as "$as_super" < "$ROOT/deploy/database/proof_seed.sql" >/dev/null
filled() {
  psql_as "$as_super" -At -F' ' -c "SELECT id, passed, total, regressions, checks_failing FROM registry_validations ORDER BY id" \
    -c "SELECT workflow_id, coalesce(mailbox, '-') FROM engine_definitions ORDER BY workflow_id" | tr '\n' ' '
}
want="v1 3 4 1 0 v2 0 0 0 0 w1 help@example.com w2 - "
psql_as "$as_super" < "$OUT/upgrade/upgrade-roles.sql" >/dev/null
psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/upgrade/upgrade.sql" >/dev/null 2>"$OUT/upgrade.err"
upgraded=$?
[ "$upgraded" = 0 ] || grep -m2 -A1 "ERROR" "$OUT/upgrade.err" | sed 's/^/  /'
psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/head/grants.sql"
$TOOL diff "postgresql://postgres:proof@localhost:$PORT/migrated" "postgresql://postgres:proof@localhost:$PORT/upgraded"
check "2 the seeded $FROM baseline plus upgrade.sql equals the Alembic-built $TO schema" $(( $? + upgraded ))
got=$(filled 2>&1)
echo "  filled: $got"
[ "$got" = "$want" ]
check "2a each fill in upgrade.sql wrote the values the store's code works out for the seeded rows" $(( $? + upgraded ))

psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/upgrade/upgrade.sql" 2>"$OUT/again.err"
again=$?
grep -q "this step needs" "$OUT/again.err"
check "2b running upgrade.sql again is refused by its first guard, before any DDL" $(( (again == 0) + $? ))

psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/upgrade/downgrade.sql" >/dev/null 2>"$OUT/down.err"
down=$?
[ "$down" = 0 ] || grep -m2 -A1 "ERROR" "$OUT/down.err" | sed 's/^/  /'
psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/upgrade/upgrade.sql" >/dev/null 2>"$OUT/up2.err"
up2=$?
[ "$up2" = 0 ] || grep -m2 -A1 "ERROR" "$OUT/up2.err" | sed 's/^/  /'
got=$(filled 2>&1)
echo "  after down and up: $got"
[ "$got" = "$want" ]
check "2c downgrade.sql then upgrade.sql keeps every seeded row and fills it the same way" $(( down + up2 + $? ))

as_runtime="postgresql://ops_agents_runtime:proof@localhost/fresh"
psql_as "$as_runtime" -c "SELECT count(*) FROM graph_threads" -c "INSERT INTO registry_agents (id) SELECT 'x' WHERE false" >/dev/null
dml=$?
psql_as "$as_runtime" -c "CREATE TABLE intruder (id int)" 2>"$OUT/ddl.err"
ddl=$?
grep -q "permission denied" "$OUT/ddl.err"
check "3 ops_agents_runtime reads and writes its tables and is refused CREATE TABLE ($(head -1 "$OUT/ddl.err"))" $(( dml + (ddl == 0) + $? ))
psql_as "$as_runtime" -c "DROP TABLE graph_threads" 2>/dev/null
check "3b ops_agents_runtime is refused DROP TABLE on its own table" $(( $? == 0 ))
psql_as "postgresql://ops_tools_runtime:proof@localhost/fresh" -c "SELECT count(*) FROM users" 2>/dev/null
check "3c ops_tools_runtime is refused platform-service's tables" $(( $? == 0 ))
psql_as "postgresql://ops_tools_runtime:proof@localhost/fresh" -At -c "SELECT has_table_privilege('gateway_calls', 'INSERT')" | grep -q t
check "3d ops_tools_runtime may write gateway_calls, which its code declares though the agents chain creates it" $?

$TOOL drift --ref "$TO" --server "$SERVER" --database "postgresql://ops_migrator:proof@localhost:$PORT/fresh" >/dev/null
check "4 drift on the fresh install is green" $?
psql_as "postgresql://ops_migrator:proof@localhost/fresh" -c "CREATE INDEX ix_by_hand ON graph_threads (created_at)"
$TOOL drift --ref "$TO" --server "$SERVER" --database "postgresql://ops_migrator:proof@localhost:$PORT/fresh" >"$OUT/drift.txt"
red=$?
cat "$OUT/drift.txt" | sed 's/^/  /'
grep -q "extra    INDEX ix_by_hand" "$OUT/drift.txt"
check "4b drift goes red on the hand-made index and names it" $(( (red == 0) + $? ))
psql_as "postgresql://ops_migrator:proof@localhost/fresh" -c "DROP INDEX ix_by_hand"
$TOOL drift --ref "$TO" --server "$SERVER" --database "postgresql://ops_migrator:proof@localhost:$PORT/fresh" >/dev/null
check "4c drift is green again once the index is dropped" $?

install "$OUT/from" behind
# agents-service: its chain has steps after FROM, so the database it meets is behind. A service that did not refuse
# would serve until stopped; it is given 60 s, and still running counts as started.
(cd "$OUT/checkout/services/agents-service" && OPS_DATABASE_URL="postgresql+asyncpg://ops_agents_runtime:proof@localhost:$PORT/behind" \
  OPS_ENVIRONMENT=dev OPS_PORT=18765 OPS_PLATFORM_URL=http://localhost:1 OPS_PLATFORM_INTERNAL_URL=http://localhost:1 \
  "$OUT/checkout/.venv/bin/python" -c 'import subprocess, sys
try:
    sys.exit(subprocess.run([sys.executable, "-m", "ops_agents.api"], timeout=60).returncode)
except subprocess.TimeoutExpired:
    print("still serving after 60 s")') >"$OUT/behind.txt" 2>&1
started=$?
grep -m1 "behind\|still serving" "$OUT/behind.txt" | cut -c1-200 | sed 's/^/  /'
grep -q "schema is behind" "$OUT/behind.txt"
check "5 agents-service at $TO refuses to start on the $FROM schema" $(( (started == 0) + $? ))
set -e

[ "$failed" = 0 ] && echo "proof: all checks passed" || echo "proof: a check failed"
exit $failed
