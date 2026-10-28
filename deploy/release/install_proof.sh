#!/usr/bin/env bash
# Proves ./install.sh the way a client team runs it (docs/deploy/install.md): a fresh clone in a temp folder, images
# pulled anonymously from GHCR, an unattended install from an answers file on its own project and port, every console
# page walked headless (docs/usecases/lib/stg_click_walk.mjs), then a rerun that changes nothing, upgrade to the same
# version, backup, restore (shown to undo a change made after the backup) and status. Then DBA mode once, against a
# separate PostgreSQL 17 with TLS and an admin that is not a superuser: this script plays the DBA and runs the three
# psql commands the installer prints, and the model is an OpenAI-compatible endpoint whose key goes through Secrets
# (the fake model, so no real model is called). It tears down only what it started and never prints a secret.
#   bash deploy/release/install_proof.sh [<git source> [<ref>]]   source default: this repo; ref default: HEAD
#   PORT (19890), DBA_PORT (19891), PG_PORT (15611), FAKE_PORT (18757), KEEP=1 leaves everything running
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SOURCE=${1:-$ROOT}
REF=${2:-HEAD}
PORT=${PORT:-19890}
DBA_PORT=${DBA_PORT:-19891}
PG_PORT=${PG_PORT:-15611}
FAKE_PORT=${FAKE_PORT:-18757}
PROJECT=ops-install-proof
DBA_PROJECT=ops-install-dba
PG=ops-install-dba-pg
FAKE=ops-install-dba-fakeai
WORK=$(mktemp -d "${TMPDIR:-/tmp}/ops-install-proof.XXXXXX")
CLONE=$WORK/ops-ai
CLONE_DBA=$WORK/ops-ai-dba
LOG=$WORK/log
mkdir -p "$LOG"
secret() { od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; }
fail() { echo "proof: FAIL $*"; exit 1; }
say() { echo "proof: $*"; }

# Anonymous pulls: a Docker config of its own on the same engine and plugins. An empty config is not enough: the CLI
# falls back to the platform's credential helper (osxkeychain, desktop) when none is named, so this one names a helper
# that never has credentials.
# SIGNED_IN=1 keeps this machine's registry login, for a run before the packages are public; the evidence says so.
export DOCKER_HOST=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
[ "${SIGNED_IN:-0}" = 1 ] || {
mkdir -p "$WORK/docker" "$WORK/bin"
printf '#!/bin/sh\n[ "$1" = get ] && { echo "credentials not found in native keychain"; exit 1; }\n[ "$1" = list ] && echo "{}"\nexit 0\n' \
  >"$WORK/bin/docker-credential-anonymous"
chmod +x "$WORK/bin/docker-credential-anonymous"
export PATH=$WORK/bin:$PATH
echo '{"credsStore":"anonymous"}' >"$WORK/docker/config.json"
[ -d "$HOME/.docker/cli-plugins" ] && ln -s "$HOME/.docker/cli-plugins" "$WORK/docker/cli-plugins"
export DOCKER_CONFIG=$WORK/docker
}

cleanup() {
  if [ "${KEEP:-0}" = 1 ]; then say "left running: $PROJECT on :$PORT, $DBA_PROJECT on :$DBA_PORT (folder $WORK)"; return; fi
  [ -f "$CLONE/ops-ai.env" ] && (cd "$CLONE" && ./install.sh uninstall --yes --delete-data >/dev/null 2>&1) || true
  [ -f "$CLONE_DBA/ops-ai.env" ] && (cd "$CLONE_DBA" && ./install.sh uninstall --yes --delete-data >/dev/null 2>&1) || true
  docker rm -fv $PG $FAKE >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

walk() { # origin email password
  # The walk is the clone's own script; node_modules come from this checkout.
  ln -sfn "$ROOT/node_modules" "$CLONE/node_modules"
  ln -sfn "$ROOT/packages/usecase-runner/node_modules" "$CLONE/packages/usecase-runner/node_modules"
  (cd "$CLONE" && STG_ORIGIN=$1 STG_EMAIL=$2 STG_PASSWORD=$3 node docs/usecases/lib/stg_click_walk.mjs) >"$LOG/walk.txt" 2>&1 || true
  cat "$LOG/walk.txt"
  local ok bad
  ok=$(grep -c '^OK' "$LOG/walk.txt" || true)
  bad=$(grep -vc '^OK' "$LOG/walk.txt" || true)
  [ "$ok" -gt 0 ] && [ "$bad" -eq 0 ] || fail "walk on $1: $ok pages OK, $bad lines not OK"
  say "walk on $1: $ok pages OK, 0 failed"
}

say "1. a fresh clone of $SOURCE at $REF in a temp folder"
T0=$(date +%s)
git clone -q "$SOURCE" "$CLONE"
git -C "$CLONE" checkout -q "$REF"
SHA=$(git -C "$CLONE" rev-parse HEAD)
VERSION=$(tr -d ' \n' <"$CLONE/deploy/release/version")
say "clone at $SHA; deploy/release/version says $VERSION"

say "2. no local copy of ghcr.io/chanl-ai/ops-ai/*:$VERSION$([ "${SIGNED_IN:-0}" = 1 ] && echo ', pulled with this machine'"'"'s registry login (SIGNED_IN=1)' || echo ' and no registry login')"
for t in platform agents tools models kb files documents runner opa proxy console db-scripts; do
  docker image rm "ghcr.io/chanl-ai/ops-ai/$t:$VERSION" >/dev/null 2>&1 || true
done
[ -z "$(docker images -q --filter "reference=ghcr.io/chanl-ai/ops-ai/*:$VERSION")" ] || fail "an image for $VERSION is still here"
if [ "${SIGNED_IN:-0}" != 1 ]; then
grep -q ghcr "$DOCKER_CONFIG/config.json" && fail "the proof's Docker config holds a login"
say "docker config: $(cat "$DOCKER_CONFIG/config.json") (a helper that never has credentials)"
tok=$(curl -s "https://ghcr.io/token?scope=repository:chanl-ai/ops-ai/platform:pull" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $tok" -H 'Accept: application/vnd.oci.image.index.v1+json' \
  "https://ghcr.io/v2/chanl-ai/ops-ai/platform/manifests/$VERSION")
say "anonymous GET of ghcr.io/chanl-ai/ops-ai/platform:$VERSION's manifest: $code"
[ "$code" = 200 ] || fail "the images are not public yet (anonymous manifest answered $code)"
fi

say "3. ./install.sh unattended from an answers file (project $PROJECT, port $PORT, built-in PostgreSQL, test model)"
ADMIN_PW="proof admin $(secret)"
cat >"$WORK/answers.txt" <<EOF
PORT=$PORT
PROJECT=$PROJECT
ORG_NAME=Install proof
ADMIN_EMAIL=admin@example.com
ADMIN_NAME=Proof Admin
ADMIN_PASSWORD=$ADMIN_PW
DATABASE=builtin
MODEL=test
EOF
(cd "$CLONE" && ./install.sh --answers "$WORK/answers.txt" --yes) | tee "$LOG/install.txt" | grep -v '^ \(Container\|Volume\|Network\|Image\)\b' || fail "that step exited non-zero"
T1=$(date +%s)
grep -q '^Ops AI .* is running' "$LOG/install.txt" || fail "install did not finish"
say "clone to signed in: $((T1 - T0))s"
stat -f '%Lp %N' "$CLONE/ops-ai.env" 2>/dev/null || stat -c '%a %n' "$CLONE/ops-ai.env"
docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Image}}' | sort -u | while read -r image; do
  case $image in
    ghcr.io/chanl-ai/ops-ai/*:"$VERSION") echo "proof: running $image  $(docker image inspect --format '{{index .RepoDigests 0}} {{.Os}}/{{.Architecture}}' "$image")" ;;
    postgres:17-alpine) echo "proof: running $image (the built-in trial database)" ;;
    *) fail "a container runs $image, from outside ghcr.io/chanl-ai/ops-ai/*:$VERSION" ;;
  esac
done

say "4. every console page, headless"
walk "http://localhost:$PORT" admin@example.com "$ADMIN_PW"

say "5. ./install.sh again on the working install"
before=$(shasum -a 256 "$CLONE/ops-ai.env" | cut -c1-64)
ids=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | sort | tr '\n' ' ')
(cd "$CLONE" && ./install.sh --yes) | tee "$LOG/rerun.txt" || fail "that step exited non-zero"
grep -q 'nothing changed' "$LOG/rerun.txt" || fail "the rerun did not say it changed nothing"
[ "$before" = "$(shasum -a 256 "$CLONE/ops-ai.env" | cut -c1-64)" ] || fail "the rerun rewrote ops-ai.env"
[ "$ids" = "$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | sort | tr '\n' ' ')" ] || fail "the rerun replaced containers"
say "rerun: ops-ai.env unchanged (sha256 $before), same containers"

say "6. ./install.sh upgrade to the same version"
(cd "$CLONE" && ./install.sh upgrade) | tee "$LOG/upgrade.txt" || fail "that step exited non-zero"
grep -q "Already at version $VERSION; nothing changed" "$LOG/upgrade.txt" || fail "upgrade to the same version changed something"
[ "$before" = "$(shasum -a 256 "$CLONE/ops-ai.env" | cut -c1-64)" ] || fail "upgrade rewrote ops-ai.env"
[ -z "$(find "$CLONE/backups" -name "*.tar.gz" 2>/dev/null)" ] || fail "a same-version upgrade made a backup"

say "7. backup, a change after it, restore"
(cd "$CLONE" && ./install.sh backup) | tee "$LOG/backup.txt" || fail "that step exited non-zero"
BACKUP=$(ls -t "$CLONE"/backups/*.tar.gz | head -n 1)
tar tzf "$BACKUP" | sed 's/^/proof: backup holds /'
DC="docker compose -p $PROJECT"
$DC exec -T postgres psql -q -U ops -d ops -c 'CREATE TABLE install_proof_marker (id int)'
docker run --rm -v "${PROJECT}_files-data:/data" alpine sh -c 'echo after-backup > /data/install-proof-marker'
$DC exec -T postgres psql -At -U ops -d ops -c "SELECT 'marker table present: ' || count(*) FROM pg_tables WHERE tablename = 'install_proof_marker'"
(cd "$CLONE" && ./install.sh restore "$BACKUP") | tee "$LOG/restore.txt" || fail "that step exited non-zero"
grep -q '^Restored from' "$LOG/restore.txt" || fail "restore did not finish"
n=$($DC exec -T postgres psql -At -U ops -d ops -c "SELECT count(*) FROM pg_tables WHERE tablename = 'install_proof_marker'")
[ "$n" = 0 ] || fail "the table made after the backup is still there"
docker run --rm -v "${PROJECT}_files-data:/data" alpine test ! -e /data/install-proof-marker || fail "the file made after the backup is still there"
say "restore: the table and the file made after the backup are gone; the check passed"
walk "http://localhost:$PORT" admin@example.com "$ADMIN_PW"

say "8. ./install.sh status"
(cd "$CLONE" && ./install.sh status) | tee "$LOG/status.txt" || fail "that step exited non-zero"

say "8b. an upgrade whose check fails rolls back: version $VERSION-broken, every image the same but a console that exits"
BROKEN=$VERSION-broken
for t in platform agents tools models kb files documents runner opa proxy; do
  docker tag "ghcr.io/chanl-ai/ops-ai/$t:$VERSION" "ghcr.io/chanl-ai/ops-ai/$t:$BROKEN"
done
printf 'FROM ghcr.io/chanl-ai/ops-ai/console:%s\nCMD ["sh", "-c", "echo broken console; exit 3"]\n' "$VERSION" >"$WORK/Dockerfile.broken"
docker build -q -t "ghcr.io/chanl-ai/ops-ai/console:$BROKEN" -f "$WORK/Dockerfile.broken" "$WORK" >/dev/null
# shellcheck disable=SC2046
docker save -o "$WORK/broken-images.tar" $(for t in platform agents tools models kb files documents runner opa proxy console; do echo "ghcr.io/chanl-ai/ops-ai/$t:$BROKEN"; done)
set +e
(cd "$CLONE" && ./install.sh upgrade --offline "$WORK/broken-images.tar") >"$LOG/rollback.txt" 2>&1
code=$?
set -e
grep -v '^ \(Container\|Volume\|Network\|Image\)\b' "$LOG/rollback.txt"
for t in platform agents tools models kb files documents runner opa proxy console; do docker image rm "ghcr.io/chanl-ai/ops-ai/$t:$BROKEN" >/dev/null; done
rm -f "$WORK/broken-images.tar"
[ "$code" = 1 ] || fail "the broken upgrade exited $code, want 1"
grep -q "rolled back to $VERSION" "$LOG/rollback.txt" || fail "the broken upgrade did not roll back"
[ "$(sed -n 's/^OPS_IMAGE_TAG=//p' "$CLONE/ops-ai.env")" = "$VERSION" ] || fail "ops-ai.env does not name $VERSION after the rollback"
(cd "$CLONE" && ./install.sh status) >"$LOG/status-after-rollback.txt" || { cat "$LOG/status-after-rollback.txt"; fail "status after the rollback"; }
say "rollback: exit 1, back on $VERSION from the backup it took, and status passes"

say "9. DBA mode against a separate PostgreSQL 17 (TLS, admin without superuser), model through Secrets"
# The first install stops first: two stacks on one laptop's Docker share its memory, and health checks time out.
(cd "$CLONE" && ./install.sh uninstall --yes --delete-data) || fail "uninstall"
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ] || fail "uninstall left containers"
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ] || fail "uninstall left volumes"
say "uninstall: no container or volume of $PROJECT is left"
DBA_ADMIN_PW=$(secret)
docker rm -fv $PG $FAKE >/dev/null 2>&1 || true
docker run -d --name $PG -e POSTGRES_PASSWORD="$(secret)" -p 127.0.0.1:$PG_PORT:5432 postgres:17 \
  -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key >/dev/null
until docker exec $PG pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec $PG psql -q -U postgres -c "CREATE ROLE opsadmin LOGIN NOSUPERUSER CREATEDB CREATEROLE BYPASSRLS PASSWORD '$DBA_ADMIN_PW'"
# An OpenAI-compatible endpoint on the host: the fake model from the published models image. It never calls a provider.
docker run -d --name $FAKE -p 127.0.0.1:$FAKE_PORT:8746 -e FAKE_OPENAI_HOST=0.0.0.0 -e FAKE_OPENAI_PORT=8746 \
  -w /app/services/models-service/scripts --entrypoint python "ghcr.io/chanl-ai/ops-ai/models:$VERSION" \
  -m fake_openai /app/services/models-service/seed/demo-fake-openai >/dev/null
git clone -q "$CLONE" "$CLONE_DBA"
DBA_ADMIN2_PW="proof dba admin $(secret)"
cat >"$WORK/answers-dba.txt" <<EOF
PORT=$DBA_PORT
PROJECT=$DBA_PROJECT
ORG_NAME=Install proof DBA
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=$DBA_ADMIN2_PW
DATABASE=postgresql://opsadmin@host.docker.internal:$PG_PORT/ops?sslmode=require
DB_MODE=dba
MODEL=http://host.docker.internal:$FAKE_PORT/v1
MODEL_NAME=fake-chat
MODEL_API_KEY=proof-provider-key-$(secret)
EOF
(cd "$CLONE_DBA" && ./install.sh --answers "$WORK/answers-dba.txt" --yes --dba-timeout 900) >"$LOG/install-dba.txt" 2>&1 &
INSTALL_PID=$!
until grep -q '^  3\. psql' "$LOG/install-dba.txt" 2>/dev/null; do
  kill -0 $INSTALL_PID 2>/dev/null || { cat "$LOG/install-dba.txt"; fail "the DBA-mode install stopped before printing the commands"; }
  sleep 3
done
say "the DBA runs the three printed commands, as opsadmin, from the clone's folder"
for n in 1 2 3; do
  cmd=$(sed -n "s/^  $n\. //p" "$LOG/install-dba.txt")
  echo "proof: DBA $n: $cmd"
  docker run --rm -e PGPASSWORD="$DBA_ADMIN_PW" -v "$CLONE_DBA:/w" -w /w postgres:17 sh -c "$cmd" >"$LOG/dba-$n.txt" 2>&1 ||
    { cat "$LOG/dba-$n.txt"; fail "DBA command $n"; }
done
wait $INSTALL_PID || { cat "$LOG/install-dba.txt"; fail "the DBA-mode install"; }
grep -v '^ \(Container\|Volume\|Network\|Image\)\b' "$LOG/install-dba.txt"
grep -q "model provider key stored in Secrets as MODEL_PROVIDER_KEY" "$LOG/install-dba.txt" || fail "the provider key was not stored through Secrets"
grep -q MODEL_PROVIDER_KEY "$CLONE_DBA/ops-ai.env" && fail "the provider key name reached ops-ai.env"
grep -q "proof-provider-key" "$CLONE_DBA/ops-ai.env" && fail "the provider key reached ops-ai.env"
docker exec $PG psql -At -U postgres -d ops -c "SELECT DISTINCT 'connected: ' || usename || ' superuser=' || usesuper FROM pg_stat_activity JOIN pg_user USING (usename) WHERE datname = 'ops' ORDER BY 1" |
  sed 's/^/proof: /'
docker exec $PG psql -At -U postgres -d ops -c "SELECT 'schema owner of graph_threads: ' || tableowner FROM pg_tables WHERE tablename = 'graph_threads'" | sed 's/^/proof: /'
walk "http://localhost:$DBA_PORT" admin@example.com "$DBA_ADMIN2_PW"
(cd "$CLONE_DBA" && ./install.sh upgrade) | tee "$LOG/upgrade-dba.txt" || fail "that step exited non-zero"
grep -q "nothing changed" "$LOG/upgrade-dba.txt" || fail "DBA-mode upgrade to the same version changed something"
printf 'postgresql://opsadmin:%s@host.docker.internal:%s/ops?sslmode=require\n' "$DBA_ADMIN_PW" "$PG_PORT" >"$WORK/admin-url"
(cd "$CLONE_DBA" && ./install.sh backup --admin-url-file "$WORK/admin-url") | tee "$LOG/backup-dba.txt" || fail "that step exited non-zero"
BACKUP_DBA=$(ls -t "$CLONE_DBA"/backups/*.tar.gz | head -n 1)
(cd "$CLONE_DBA" && ./install.sh restore "$BACKUP_DBA" --admin-url-file "$WORK/admin-url") >"$LOG/restore-dba.txt" 2>&1 ||
  { cat "$LOG/restore-dba.txt"; fail "DBA-mode restore"; }
grep '^PASS\|^FAIL\|^Restored' "$LOG/restore-dba.txt"

say "10. no secret in this output"
# Every value in the two settings files whose name says it is secret (keys, passwords, connection strings), the admin
# passwords, the DBA admin's and the provider key; by name, so a printed project name or URL is not counted.
: >"$WORK/secrets.txt"
for f in "$CLONE/ops-ai.env" "$CLONE_DBA/ops-ai.env"; do
  grep -E '^OPS_[A-Z_]*(KEY|KEYS|PASSWORD|DATABASE_URL)[A-Z_]*=.' "$f" | grep -v '^OPS_SERVICE_PUBLIC_KEYS=' >>"$WORK/secrets.txt" || true
done
printf 'ADMIN=%s\nDBA_ADMIN=%s\nDBA_SERVER_ADMIN=%s\n' "$ADMIN_PW" "$DBA_ADMIN2_PW" "$DBA_ADMIN_PW" >>"$WORK/secrets.txt"
grep '^MODEL_API_KEY=' "$WORK/answers-dba.txt" >>"$WORK/secrets.txt"
leaks=""
while IFS= read -r line; do
  if grep -rqF -- "${line#*=}" "$LOG"; then leaks="$leaks ${line%%=*}"; fi
done <"$WORK/secrets.txt"
[ -z "$leaks" ] || fail "secret values appear in the logs:$leaks"
say "$(wc -l <"$WORK/secrets.txt" | tr -d ' ') secret values (keys, passwords, connection strings) checked against every log: none printed"
say "PASS install proof at $SHA, version $VERSION; clone to signed in $((T1 - T0))s"
