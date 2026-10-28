#!/bin/sh
# One release package for a team that installs Ops AI on its own Linux machines with Docker (docs/deploy/release-package.md):
#   OUT/ops-ai-<version>/                the package: compose files, env template, db/postgres, db/azure-sql, INSTALL.md,
#                                        images.txt, release.txt, SHA256SUMS
#   OUT/ops-ai-<version>.tar.gz          the package as one file
#   OUT/ops-ai-<version>-images.tar.gz   every image for linux/amd64, as `docker save` writes them, for docker load
#   OUT/ops-ai-<version>.SHA256SUMS      the two tarballs' checksums
# Everything comes from `git archive REF`, so uncommitted files never reach a package. The version is REF when it is a
# tag, else its short sha. Images are named <IMAGE_PREFIX>/<service>:<version>, built by images.sh and pushed nowhere.
#   sh deploy/release/package.sh <ref>    IMAGE_PREFIX (default ghcr.io/chanl-ai/ops-ai), OUT (default dist),
#                                         SERVER=<throwaway PostgreSQL admin URL> (else one is started and removed),
#                                         BUILD=0 reuses images already built from the same commit
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
REF=${1:?usage: package.sh <ref>}
PREFIX=${IMAGE_PREFIX:-ghcr.io/chanl-ai/ops-ai}
OUT=$(mkdir -p "${OUT:-$ROOT/dist}" && cd "${OUT:-$ROOT/dist}" && pwd)
TARGETS="platform agents tools models kb files documents runner opa proxy console db-scripts"
PLATFORM=linux/amd64
SHA=$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")
if git -C "$ROOT" show-ref --verify --quiet "refs/tags/$REF"; then VERSION=$REF; else VERSION=$(git -C "$ROOT" rev-parse --short=8 "$SHA"); fi
NAME=ops-ai-$VERSION
PKG=$OUT/$NAME
PG=ops-release-ddl-pg
WORK=$(mktemp -d)
cleanup() {
  [ -n "${SERVER_STARTED:-}" ] && docker rm -fv $PG >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "package: $NAME from $SHA"
mkdir "$WORK/src"
git -C "$ROOT" archive "$SHA" | tar -x -C "$WORK/src"
test -f "$WORK/src/docs/deploy/install-guide.md" || { echo "package: $REF has no docs/deploy/install-guide.md"; exit 1; }

if [ "${BUILD:-1}" = 1 ]; then
  TARGETS="$TARGETS" IMAGE_PREFIX="$PREFIX" sh "$ROOT/deploy/release/images.sh" "$SHA" "$VERSION" --platforms $PLATFORM
fi
for t in $TARGETS; do
  image=$PREFIX/$t:$VERSION
  built=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}} {{.Os}}/{{.Architecture}}' "$image")
  [ "$built" = "$SHA $PLATFORM" ] || { echo "package: $image is '$built', want '$SHA $PLATFORM'"; exit 1; }
done

rm -rf "$PKG" "$OUT/$NAME.tar.gz" "$OUT/$NAME-images.tar.gz" "$OUT/$NAME.SHA256SUMS"
mkdir -p "$PKG/compose" "$PKG/db"
cp "$WORK/src/deploy/compose/app.yaml" "$WORK/src/deploy/compose/dba.yaml" "$WORK/src/deploy/compose/try.yaml" "$PKG/compose/"
sed -e "s|^OPS_IMAGE_PREFIX=.*|OPS_IMAGE_PREFIX=$PREFIX|" -e "s|^OPS_IMAGE_TAG=.*|OPS_IMAGE_TAG=$VERSION|" \
  "$WORK/src/deploy/compose/app.env.example" >"$PKG/ops-ai.env.example"
cp "$WORK/src/docs/deploy/install-guide.md" "$PKG/INSTALL.md"

if [ -z "${SERVER:-}" ]; then
  # The schema tool makes scratch databases and the chains' roles on this server; roles are server-wide, so it is a
  # throwaway of its own, never the shared dev cluster.
  docker rm -fv $PG >/dev/null 2>&1 || true
  docker run -d --name $PG -e POSTGRES_PASSWORD=release -p 127.0.0.1:15599:5432 postgres:17-alpine >/dev/null
  SERVER_STARTED=1
  until docker exec $PG pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do sleep 1; done
  SERVER=postgresql://postgres:release@localhost:15599/postgres
fi
SCHEMA="uv run --quiet --project $ROOT python $ROOT/deploy/database/schema.py"
echo "package: db/postgres"
$SCHEMA ddl --server "$SERVER" --out "$PKG/db/postgres" --ref "$SHA" >/dev/null
echo "package: db/azure-sql"
$SCHEMA --dialect mssql ddl --out "$PKG/db/azure-sql" --ref "$SHA" >/dev/null

cat >"$PKG/db/postgres/README.md" <<EOF
# PostgreSQL scripts for Ops AI $VERSION

Runs today on PostgreSQL 15 or newer, including Azure Database for PostgreSQL Flexible Server. Apply with psql, in
this order (INSTALL.md, "Database"):

| Step | Connect as | Script |
|---|---|---|
| 1 | the server admin, in database postgres | roles.sql, then one ALTER ROLE ... PASSWORD per login |
| 2 | the server admin | CREATE DATABASE <name> OWNER ops_migrator |
| 3 | ops_migrator, in the new database | bundle.sql |
| 4 | ops_migrator, in the new database | grants.sql |

01-agents.sql to 07-documents.sql hold each service's part of bundle.sql for review; apply bundle.sql, not them.
manifest.json names each chain's revision; \`shasum -a 256 -c SHA256SUMS\` checks the files.

Upgrades: each later release ships upgrade-from-<your version>/upgrade.sql (and upgrade-roles.sql when a release adds
a role). Run it as ops_migrator, then that release's grants.sql, then start the new images. Every service refuses to
start on a schema older than its build.
EOF

cat >"$PKG/db/azure-sql/README.md" <<EOF
# Azure SQL and SQL Server scripts for Ops AI $VERSION: for review, not yet runnable

Status: generated from the services' store models and reviewed against golden files, but never applied to a SQL
Server or Azure SQL database, and the services do not run on SQL Server yet. Install on PostgreSQL (db/postgres).
These scripts are here so your DBA can review the schema, roles and row-level security now.

| File | What it holds |
|---|---|
| roles.sql | In master: one SQL login per service plus ops_migrator, passwords as sqlcmd variables; the database with collation Latin1_General_100_BIN2_UTF8 and READ_COMMITTED_SNAPSHOT ON |
| 01-agents.sql to 07-documents.sql | Each service's tables, indexes, keys and defaults, its tenant security policies, and its version table |
| bundle.sql | All of the above in order, with checks on collation, snapshot isolation and compatibility level 160 |
| grants.sql | One database user per service login, with SELECT, INSERT, UPDATE and DELETE on its own tables only |
| manifest.json, SHA256SUMS | Each chain's revision and every file's checksum |

Still to come before Ops AI runs on Azure SQL: applying these scripts to a server and comparing the result with the
models; kb's full-text search column; the checkpointer's three tables; platform's pre-tenant lookups; the workflow
worker's queue claim under the tenant write predicate; and every service's tests on SQL Server.
EOF

echo "package: images.txt"
{
  echo "# image	id	platform	size_bytes"
  for t in $TARGETS; do
    docker image inspect --format "$PREFIX/$t:$VERSION	{{.Id}}	{{.Os}}/{{.Architecture}}	{{.Size}}" "$PREFIX/$t:$VERSION"
  done
} >"$PKG/images.txt"
cat >"$PKG/release.txt" <<EOF
product: Ops AI by Chanl AI (https://chanl.ai)
version: $VERSION
commit: $SHA
platform: $PLATFORM
images: $NAME-images.tar.gz (docker load -i)
EOF
(cd "$PKG" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | xargs shasum -a 256 >SHA256SUMS)

echo "package: $NAME.tar.gz"
tar -czf "$OUT/$NAME.tar.gz" -C "$OUT" "$NAME"
echo "package: $NAME-images.tar.gz"
images=""
for t in $TARGETS; do images="$images $PREFIX/$t:$VERSION"; done
# shellcheck disable=SC2086
docker save $images | gzip >"$OUT/$NAME-images.tar.gz"
(cd "$OUT" && shasum -a 256 "$NAME.tar.gz" "$NAME-images.tar.gz" >"$NAME.SHA256SUMS")
ls -l "$OUT/$NAME.tar.gz" "$OUT/$NAME-images.tar.gz" | awk '{print "package: " $NF " " $5 " bytes"}'
