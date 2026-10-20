#!/bin/sh
# Installs a release package the way a client team does, from the tarball alone, and proves it (docs/deploy/release-package.md):
# copies the tarball, the image bundle and their checksums to a temp folder outside the repo; checks them; removes this
# machine's copies of the package's images and loads them from the bundle; starts a PostgreSQL 17 with TLS as the
# client's database server, with an admin that is not a superuser (Azure Database for PostgreSQL 16+'s server admin:
# CREATEDB, CREATEROLE, BYPASSRLS); applies db/postgres with psql as the DBA would; fills the env from the template;
# starts compose (dba.yaml, try.yaml's fake model) as project ops-release-proof; walks the origin (deploy/fly/smoke.mjs,
# then every console page with docs/usecases/lib/stg_click_walk.mjs); shows a runtime login refused DDL and a service
# refusing a database without its schema; compares db/azure-sql with the golden files; backs up, restores into a new
# database and walks every page again on it. No real model is called. Passwords, keys and the env file stay in the temp
# folder and are never printed.
#   sh deploy/release/proof.sh dist/ops-ai-<version>.tar.gz     KEEP=1 leaves it running; OPS_PROOF_PORT, OPS_PROOF_PG_PORT
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TARBALL=$(cd "$(dirname "${1:?usage: proof.sh dist/ops-ai-<version>.tar.gz}")" && pwd)/$(basename "$1")
DIST=$(dirname "$TARBALL")
NAME=$(basename "$TARBALL" .tar.gz)
PROJECT=ops-release-proof
PORT=${OPS_PROOF_PORT:-18990}
PG=ops-release-proof-pg
PG_PORT=${OPS_PROOF_PG_PORT:-15601}
ORIGIN=http://localhost:$PORT
WORK=$(mktemp -d "${TMPDIR:-/tmp}/ops-release-proof.XXXXXX")
PKG=$WORK/$NAME
C="docker compose -p $PROJECT -f compose/app.yaml -f compose/dba.yaml -f compose/try.yaml --profile fake-model --env-file ops-ai.env"
# On a host that is not amd64 the images run under QEMU emulation, and this proof-only file adjusts two things an amd64
# VM never needs: each Python health check gets 60 s (a check took over its 5 s timeout while ten containers started
# on two CPUs), and the two Go images, proxy (Caddy) and opa, run as native builds of the same Dockerfile stages at the
# package's commit, because Go amd64 binaries abort under QEMU here (fatal error: taggedPointerPack).
NATIVE=ops-release-proof-native
if [ "$(docker info --format '{{.Architecture}}')" != x86_64 ]; then
  C="$C -f $WORK/emulation.yaml"
  {
    echo "services:"
    for s in platform agents worker tools models kb files documents console fake-model; do
      echo "  $s: { healthcheck: { timeout: 60s, interval: 20s, start_period: 300s, retries: 10 } }"
    done
    echo "  proxy: { image: $NATIVE/proxy:latest }"
    echo "  opa: { image: $NATIVE/opa:latest }"
  } >"$WORK/emulation.yaml"
  EMULATED=1
fi
cleanup() {
  [ "${KEEP:-0}" = 1 ] && { echo "proof: left running as $PROJECT on $ORIGIN (folder $WORK)"; return; }
  [ -f "$PKG/ops-ai.env" ] && (cd "$PKG" && $C down -v --remove-orphans >/dev/null 2>&1) || true
  docker rm -fv $PG >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
fail() { echo "proof: FAIL $*"; exit 1; }
secret() { od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; }

echo "proof: 1. the tarball alone, in $WORK"
cp "$TARBALL" "$DIST/$NAME-images.tar.gz" "$DIST/$NAME.SHA256SUMS" "$WORK/"
cd "$WORK"
sha256sum -c "$NAME.SHA256SUMS"
tar -xzf "$NAME.tar.gz"
cd "$PKG"
sha256sum -c SHA256SUMS | grep -v ': OK$' && fail "a package file differs from SHA256SUMS"
echo "proof: every file in $NAME matches SHA256SUMS ($(wc -l <SHA256SUMS | tr -d ' ') files)"
grep -rn 'build:' compose/ && fail "a compose file builds from source"
COMMIT=$(sed -n 's/^commit: //p' release.txt)

echo "proof: 2. images loaded from the bundle"
grep -v '^#' images.txt | while read -r image _ _ _; do docker image rm "$image" >/dev/null 2>&1 || true; done
docker load -i "../$NAME-images.tar.gz"
grep -v '^#' images.txt | while read -r image id platform _; do
  got=$(docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$image")
  [ "$got" = "$id $platform" ] || fail "$image is $got, images.txt says $id $platform"
  echo "proof: $image $platform matches images.txt"
done
if [ "${EMULATED:-0}" = 1 ]; then
  echo "proof: this host runs amd64 images under emulation: health checks get 60 s, and proxy and opa run as native builds of $COMMIT ($WORK/emulation.yaml)"
  mkdir "$WORK/src" && git -C "$ROOT" archive "$COMMIT" | tar -x -C "$WORK/src"
  for t in proxy opa; do
    docker build -q -f "$WORK/src/deploy/fly/Dockerfile" --target $t -t "$NATIVE/$t:latest" "$WORK/src" >/dev/null
  done
fi
PREFIX=$(sed -n 's/^OPS_IMAGE_PREFIX=//p' ops-ai.env.example)
TAG=$(sed -n 's/^OPS_IMAGE_TAG=//p' ops-ai.env.example)

echo "proof: 3. the database server: PostgreSQL 17 with TLS, an admin that is not a superuser"
ADMIN_PW=$(secret)
docker rm -fv $PG >/dev/null 2>&1 || true
docker run -d --name $PG -e POSTGRES_PASSWORD="$(secret)" -p 127.0.0.1:$PG_PORT:5432 postgres:17 \
  -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key >/dev/null
until docker exec $PG pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec $PG psql -q -U postgres -c "CREATE ROLE opsadmin LOGIN NOSUPERUSER CREATEDB CREATEROLE BYPASSRLS PASSWORD '$ADMIN_PW'"
ADMIN="host=localhost port=$PG_PORT user=opsadmin dbname=postgres sslmode=require"
db() { echo "host=localhost port=$PG_PORT user=$1 dbname=$2 sslmode=require"; }

echo "proof: 4. the DBA applies db/postgres with psql"
LOGINS="ops_migrator ops_platform_runtime ops_agents_runtime ops_tools_runtime ops_models_runtime ops_kb_runtime ops_files_runtime ops_documents_runtime"
for login in $LOGINS; do printf '%s=%s\n' "$login" "$(secret)"; done >"$WORK/passwords"
pw() { sed -n "s/^$1=//p" "$WORK/passwords"; }
(
  cd db/postgres
  export PGPASSWORD="$ADMIN_PW"
  psql -v ON_ERROR_STOP=1 "$ADMIN" -q -f roles.sql
  for login in $LOGINS; do psql -v ON_ERROR_STOP=1 "$ADMIN" -q -c "ALTER ROLE $login PASSWORD '$(pw "$login")'"; done
  psql -v ON_ERROR_STOP=1 "$ADMIN" -q -c "GRANT ops_migrator TO opsadmin"
  psql -v ON_ERROR_STOP=1 "$ADMIN" -q -c "CREATE DATABASE ops OWNER ops_migrator"
  export PGPASSWORD="$(pw ops_migrator)"
  psql -v ON_ERROR_STOP=1 "$(db ops_migrator ops)" -q -f bundle.sql >/dev/null
  psql -v ON_ERROR_STOP=1 "$(db ops_migrator ops)" -q -f grants.sql >/dev/null
)
echo "proof: roles.sql, CREATE DATABASE, bundle.sql and grants.sql applied as opsadmin and ops_migrator"

echo "proof: 5. the env file from the template"
cp ops-ai.env.example ops-ai.env
chmod 600 ops-ai.env
setenv() { V=$2 awk -v k="$1" 'BEGIN { v = ENVIRON["V"] } index($0, k "=") == 1 { print k "=" v; next } { print }' ops-ai.env >ops-ai.env.new && mv ops-ai.env.new ops-ai.env; }
docker run --rm --entrypoint python "$PREFIX/platform:$TAG" /app/deploy/fly/generate_keys.py >"$WORK/keys"
while IFS= read -r line; do setenv "${line%%=*}" "${line#*=}"; done <"$WORK/keys"
dsn() { echo "postgresql+asyncpg://$1:$(pw "$1")@host.docker.internal:$PG_PORT/$2?ssl=require"; }
usedb() { for s in platform agents tools models kb files documents; do setenv "OPS_DATABASE_URL_$(echo $s | tr a-z A-Z)" "$(dsn "ops_${s}_runtime" "$1")"; done; }
ADMIN_PASSWORD="proof admin $(secret)"
setenv OPS_PUBLIC_ORIGIN "$ORIGIN"
setenv OPS_PUBLIC_PORT "$PORT"
usedb ops
setenv OPS_BOOTSTRAP_TENANT_NAME "Release proof"
setenv OPS_BOOTSTRAP_ADMIN_EMAIL admin@example.com
setenv OPS_BOOTSTRAP_ADMIN_NAME "Release Admin"
setenv OPS_BOOTSTRAP_ADMIN_PASSWORD "$ADMIN_PASSWORD"
grep -c '^OPS_SVC_KEY_[A-Z]*=.' ops-ai.env | sed 's/^/proof: service keys set: /'

echo "proof: 6. docker compose up"
$C up -d --wait --wait-timeout 600 migrate platform tools models kb files opa fake-model
connect() {
  $C run --rm -T --no-deps agents python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
    --base-url http://fake-model:8746/v1 --alias default --model fake-chat --input-price 1 --output-price 1 \
    --budget 5 --key-id "$1" | sed -n 's/^OPS_MODELS_KEY=//p'
}
setenv OPS_MODELS_KEY_AGENTS "$(connect purpose:agents)"
setenv OPS_MODELS_KEY_DOCUMENTS "$(connect purpose:documents)"
$C up -d --wait --wait-timeout 600
$C ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
$C ps --format '{{.Image}}' | grep -v "^$PREFIX/" | grep -v "^$NATIVE/" | grep -v '^$' && fail "a container runs an image from outside the package"

curl -fsS "$ORIGIN/api/platform/v1/health" | head -c 200; echo
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' $($C ps -q) | awk '{ print "proof: memory " $1 " " $2 }'

echo "proof: 7. the walk through $ORIGIN"
walk() {
  (cd "$ROOT" && STG_ORIGIN=$ORIGIN STG_EMAIL=admin@example.com STG_PASSWORD=$ADMIN_PASSWORD node docs/usecases/lib/stg_click_walk.mjs) >"$WORK/walk.txt" 2>&1 || true
  cat "$WORK/walk.txt"
  ok=$(grep -c '^OK' "$WORK/walk.txt" || true)
  bad=$(grep -vc '^OK' "$WORK/walk.txt" || true)
  [ "$ok" -gt 0 ] && [ "$bad" -eq 0 ] || fail "walk: $ok pages OK, $bad lines not OK"
  echo "proof: walk: $ok pages OK, 0 failed"
}
(cd "$ROOT" && OPS_SMOKE_EMAIL=admin@example.com OPS_SMOKE_PASSWORD=$ADMIN_PASSWORD node deploy/fly/smoke.mjs "$ORIGIN")
walk

echo "proof: 8. least privilege"
probe() {
  out=$(PGPASSWORD="$(pw "$1")" psql "$(db "$1" "${PROBE_DB:-ops}")" -q -c "$2" 2>&1) && fail "$1 ran: $2"
  echo "$out" | grep -qE 'permission denied|must be owner' || fail "$1 failed for another reason: $2 -> $out"
  echo "proof: $1 refused in ${PROBE_DB:-ops}: $2 -> $(echo "$out" | head -1)"
}
probe ops_agents_runtime "CREATE TABLE ddl_probe (id int)"
probe ops_agents_runtime "DROP TABLE graph_threads"
probe ops_platform_runtime "ALTER TABLE api_keys ADD COLUMN ddl_probe int"
probe ops_models_runtime "SELECT count(*) FROM api_keys"
docker exec $PG psql -q -U postgres -d ops -At -c "SELECT DISTINCT usename || ' superuser=' || usesuper FROM pg_stat_activity JOIN pg_user USING (usename) WHERE datname = 'ops' AND pid <> pg_backend_pid() ORDER BY 1" | sed 's/^/proof: connected: /'
PGPASSWORD="$ADMIN_PW" psql -v ON_ERROR_STOP=1 "$ADMIN" -q -c "CREATE DATABASE ops_empty OWNER ops_migrator"
out=$($C run --rm -T --no-deps -e OPS_DATABASE_URL="$(dsn ops_models_runtime ops_empty)" models 2>&1) && fail "models-service started on a database without its schema"
echo "proof: models-service refused a database without its schema: $(echo "$out" | grep -i 'schema' | tail -1 | cut -c1-200)"

# The schema tool adds one line naming the commit ("-- At <sha> (<short>)."), which the golden files leave out.
echo "proof: 9. db/azure-sql against the golden files at $COMMIT, without the line naming the commit"
for f in 01-agents.sql 02-tools.sql 03-models.sql 04-kb.sql 05-platform.sql 06-files.sql 07-documents.sql roles.sql grants.sql; do
  grep -q "^-- At $COMMIT (" "db/azure-sql/$f" || fail "db/azure-sql/$f does not name $COMMIT"
  ours=$(grep -v "^-- At $COMMIT (" "db/azure-sql/$f" | shasum -a 256 | cut -c1-64)
  golden=$(git -C "$ROOT" show "$COMMIT:deploy/database/golden/mssql/$f" | shasum -a 256 | cut -c1-64)
  [ "$ours" = "$golden" ] || fail "db/azure-sql/$f differs from the golden file"
  echo "proof: db/azure-sql/$f = golden $golden"
done
grep -q 'never applied to a SQL' db/azure-sql/README.md || fail "db/azure-sql/README.md does not state the status"

echo "proof: 10. back up, restore into a new database, walk again"
mkdir "$WORK/backup"
docker run --rm -e PGPASSWORD="$ADMIN_PW" -v "$WORK/backup:/backup" postgres:17 \
  pg_dump -Fc -f /backup/ops.dump "host=host.docker.internal port=$PG_PORT user=opsadmin dbname=ops sslmode=require"
for v in files-data kb-data; do
  docker run --rm -v "${PROJECT}_$v:/data" -v "$WORK/backup:/out" alpine tar czf "/out/$v.tgz" -C /data .
done
ls -l "$WORK/backup" | awk 'NR > 1 { print "proof: backup " $NF " " $5 " bytes" }'
$C stop
PGPASSWORD="$ADMIN_PW" psql -v ON_ERROR_STOP=1 "$ADMIN" -q -c "CREATE DATABASE ops_restored OWNER ops_migrator"
docker run --rm -e PGPASSWORD="$ADMIN_PW" -v "$WORK/backup:/backup" postgres:17 \
  pg_restore --exit-on-error -d "host=host.docker.internal port=$PG_PORT user=opsadmin dbname=ops_restored sslmode=require" /backup/ops.dump
for v in files-data kb-data; do
  docker run --rm -v "${PROJECT}_$v:/data" -v "$WORK/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/$v.tgz -C /data"
done
usedb ops_restored
$C up -d --wait --wait-timeout 600
PROBE_DB=ops_restored probe ops_agents_runtime "CREATE TABLE ddl_probe (id int)"
walk
echo "proof: PASS $NAME"
