#!/bin/sh
# Proves the compose install end to end on this machine, as a bank would run it: builds every image one at a time,
# starts a throwaway PostgreSQL of its own (container ops-compose-proof-pg on :15498), installs the baseline there as a
# DBA would (make db-ddl's roles, bundle and grants: a migrator that owns the objects, one login per service with DML
# on its own tables), starts app.yaml plus try.yaml's fake model as project ops-compose on port 18890 with each
# service on its own login, connects the fake model, then walks the origin (deploy/fly/smoke.mjs): sign-in, chat, a
# workflow run on the worker, a document read and three console pages. No real model is called: the only provider
# connection is the fake's. Keys, passwords and the env file live in a temp folder and are never printed.
#   sh deploy/compose/proof.sh            KEEP=1 leaves the stack running; BUILD=0 skips the image builds
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PROJECT=ops-compose
PORT=${OPS_PROOF_PORT:-18890}
DB=ops_compose
PG=ops-compose-proof-pg
PG_PORT=${OPS_PROOF_PG_PORT:-15498}
ORIGIN=http://localhost:$PORT
WORK=$(mktemp -d)
ENV=$WORK/app.env
# OPS_PROOF_COMPOSE_EXTRA adds compose files (mailbox_proof.sh adds mailbox-demo.yaml).
COMPOSE="docker compose -p $PROJECT -f $ROOT/deploy/compose/app.yaml -f $ROOT/deploy/compose/try.yaml ${OPS_PROOF_COMPOSE_EXTRA:-} --env-file $ENV --profile fake-model"
cleanup() {
  [ "${KEEP:-0}" = 1 ] && { echo "proof: left running as $PROJECT on $ORIGIN (env $ENV)"; return; }
  $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
  docker rm -fv $PG >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

if [ "${BUILD:-1}" = 1 ]; then
  for target in console platform agents tools models kb files documents runner opa proxy; do
    echo "proof: building ops-ai/$target"
    docker build -q -f "$ROOT/deploy/fly/Dockerfile" --target "$target" -t "ops-ai/$target:dev" "$ROOT" >/dev/null
  done
  sh "$ROOT/deploy/images/prune_build_cache.sh"
fi

echo "proof: the baseline installed on a throwaway PostgreSQL, one login per service"
docker rm -fv $PG >/dev/null 2>&1 || true
docker run -d --name $PG -e POSTGRES_PASSWORD=proof -p 127.0.0.1:$PG_PORT:5432 postgres:17-alpine >/dev/null
# The image first runs a temporary server on its socket only while it initialises; wait for the real one on TCP.
until docker exec $PG pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do sleep 1; done
SERVER=postgresql://postgres:proof@localhost:$PG_PORT/postgres
SCHEMA="uv run --quiet --project $ROOT python $ROOT/deploy/database/schema.py"
$SCHEMA ddl --server "$SERVER" --out "$WORK/ddl" --ref . | head -1
$SCHEMA install --server "$SERVER" --dir "$WORK/ddl" --database $DB --passwords "$WORK/passwords"
dsn() { echo "postgresql+asyncpg://$1:$(sed -n "s/^$1=//p" "$WORK/passwords")@host.docker.internal:$PG_PORT/$DB"; }

PASSWORD="proof admin password $(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
{
  docker run --rm --entrypoint python ops-ai/platform:dev /app/deploy/fly/generate_keys.py
  cat <<EOF
OPS_PUBLIC_ORIGIN=$ORIGIN
OPS_PUBLIC_PORT=$PORT
OPS_DATABASE_URL=$(dsn ops_migrator)
OPS_DATABASE_URL_PLATFORM=$(dsn ops_platform_runtime)
OPS_DATABASE_URL_AGENTS=$(dsn ops_agents_runtime)
OPS_DATABASE_URL_TOOLS=$(dsn ops_tools_runtime)
OPS_DATABASE_URL_MODELS=$(dsn ops_models_runtime)
OPS_DATABASE_URL_KB=$(dsn ops_kb_runtime)
OPS_DATABASE_URL_FILES=$(dsn ops_files_runtime)
OPS_DATABASE_URL_DOCUMENTS=$(dsn ops_documents_runtime)
OPS_BOOTSTRAP_TENANT_ID=local
OPS_BOOTSTRAP_TENANT_NAME=Compose proof
OPS_BOOTSTRAP_TEAM_NAME=Security
OPS_BOOTSTRAP_ADMIN_EMAIL=admin@compose.example
OPS_BOOTSTRAP_ADMIN_NAME=Compose Admin
OPS_BOOTSTRAP_ADMIN_PASSWORD=$PASSWORD
EOF
} >"$ENV"

echo "proof: starting $PROJECT"
$COMPOSE up -d --wait --wait-timeout 180 migrate platform tools models kb files fake-model opa
echo "proof: connecting the fake model"
connect() {
  $COMPOSE run --rm -T --no-deps agents python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
    --base-url http://fake-model:8746/v1 --alias default --model fake-chat --input-price 1 --output-price 1 \
    --budget 5 --key-id "$1" | sed -n 's/^OPS_MODELS_KEY=//p'
}
printf 'OPS_MODELS_KEY_AGENTS=%s\nOPS_MODELS_KEY_DOCUMENTS=%s\n' "$(connect purpose:agents)" "$(connect purpose:documents)" >>"$ENV"
$COMPOSE up -d --wait --wait-timeout 240
$COMPOSE ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'

echo "proof: walking $ORIGIN"
OPS_SMOKE_EMAIL=admin@compose.example OPS_SMOKE_PASSWORD=$PASSWORD node "$ROOT/deploy/fly/smoke.mjs" "$ORIGIN"
echo "proof: provider connections in models-service (the fake's only):"
docker exec $PG psql -q -U postgres -d "$DB" -At -c "SELECT name || ' ' || base_url FROM provider_connections"
echo "proof: the logins the services hold (none a superuser):"
docker exec $PG psql -q -U postgres -d "$DB" -At -c "SELECT DISTINCT usename || ' superuser=' || usesuper FROM pg_stat_activity JOIN pg_user USING (usename) WHERE datname = '$DB' AND pid <> pg_backend_pid() ORDER BY 1"
