#!/bin/sh
# Proves the DBA scripts on a throwaway PostgreSQL of its own (container ops-schema-proof on :15499, removed at the end;
# never the dev stack's). Prints PASS or FAIL per check and exits 1 on any FAIL.
#   1 the baseline applied to an empty database equals what the chains build (Alembic, online)
#   2 an older ref's baseline plus the upgrade to this ref equals what the chains build
#   3 a runtime role reads and writes its own tables (and the ones its code declares) and is refused DDL
#   4 drift is green on a clean install, red on a hand-made index, green again once it is dropped
#   5 a service refuses to start on a database whose recorded version is behind its chain
#   sh deploy/database/proof.sh [FROM]     FROM defaults to c60afb6c; KEEP=1 leaves the container and output
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
FROM=${1:-c60afb6c}
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
docker run -d --name $NAME -e POSTGRES_PASSWORD=proof -p 127.0.0.1:$PORT:5432 postgres:17-alpine >/dev/null
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
  psql_as "postgresql://ops_migrator:proof@localhost/$db" < "$dir/bundle.sql" >/dev/null
  psql_as "postgresql://ops_migrator:proof@localhost/$db" < "$dir/grants.sql" >/dev/null
}

echo "proof: baseline at HEAD and at $FROM, the upgrade between them"
$TOOL ddl --server "$SERVER" --out "$OUT/head" --ref HEAD | head -1
$TOOL ddl --server "$SERVER" --out "$OUT/from" --ref "$FROM" | head -1
$TOOL upgrade-sql --from "$FROM" --to HEAD --out "$OUT/upgrade"

echo "proof: the chains at HEAD, run by Alembic"
docker exec $NAME psql -q -U postgres -c "CREATE DATABASE migrated"
mkdir -p "$OUT/checkout" && (cd "$ROOT" && git archive HEAD | tar -x -C "$OUT/checkout")
(cd "$OUT/checkout" && VIRTUAL_ENV= uv sync --frozen --no-dev --quiet)
OPS_ROOT="$OUT/checkout" ALEMBIC="$OUT/checkout/.venv/bin/alembic" OPS_MIGRATE_SKIP_BOOTSTRAP=1 \
  OPS_DATABASE_URL="postgresql+asyncpg://postgres:proof@localhost:$PORT/migrated" sh "$ROOT/deploy/images/migrate.sh" >/dev/null

install "$OUT/head" fresh
set +e
$TOOL diff "postgresql://postgres:proof@localhost:$PORT/migrated" "postgresql://postgres:proof@localhost:$PORT/fresh"
check "1 the HEAD baseline on an empty database equals the Alembic-built schema" $?

install "$OUT/from" upgraded
psql_as "postgresql://postgres:proof@localhost/upgraded" < "$OUT/upgrade/upgrade-roles.sql" >/dev/null
psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/upgrade/upgrade.sql" >/dev/null
upgraded=$?
psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/head/grants.sql"
$TOOL diff "postgresql://postgres:proof@localhost:$PORT/migrated" "postgresql://postgres:proof@localhost:$PORT/upgraded"
check "2 the $FROM baseline plus upgrade.sql equals the Alembic-built HEAD schema" $(( $? + upgraded ))

psql_as "postgresql://ops_migrator:proof@localhost/upgraded" < "$OUT/upgrade/upgrade.sql" 2>"$OUT/again.err"
again=$?
grep -q "this step needs" "$OUT/again.err"
check "2b running upgrade.sql again is refused by its first guard, before any DDL" $(( (again == 0) + $? ))

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

$TOOL drift --server "$SERVER" --database "postgresql://ops_migrator:proof@localhost:$PORT/fresh" >/dev/null
check "4 drift on the fresh install is green" $?
psql_as "postgresql://ops_migrator:proof@localhost/fresh" -c "CREATE INDEX ix_by_hand ON graph_threads (created_at)"
$TOOL drift --server "$SERVER" --database "postgresql://ops_migrator:proof@localhost:$PORT/fresh" >"$OUT/drift.txt"
red=$?
cat "$OUT/drift.txt" | sed 's/^/  /'
grep -q "extra    INDEX ix_by_hand" "$OUT/drift.txt"
check "4b drift goes red on the hand-made index and names it" $(( (red == 0) + $? ))
psql_as "postgresql://ops_migrator:proof@localhost/fresh" -c "DROP INDEX ix_by_hand"
$TOOL drift --server "$SERVER" --database "postgresql://ops_migrator:proof@localhost:$PORT/fresh" >/dev/null
check "4c drift is green again once the index is dropped" $?

install "$OUT/from" behind
(cd "$OUT/checkout/services/models-service" && OPS_DATABASE_URL="postgresql+asyncpg://ops_models_runtime:proof@localhost:$PORT/behind" \
  OPS_ENVIRONMENT=dev "$OUT/checkout/.venv/bin/python" -m ops_models) >"$OUT/behind.txt" 2>&1
started=$?
tail -1 "$OUT/behind.txt" | sed 's/^/  /'
grep -q "behind" "$OUT/behind.txt"
check "5 models-service at HEAD refuses to start on the $FROM schema" $(( (started == 0) + $? ))
set -e

[ "$failed" = 0 ] && echo "proof: all checks passed" || echo "proof: a check failed"
exit $failed
