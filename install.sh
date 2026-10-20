#!/usr/bin/env bash
# Installs, upgrades, backs up, restores and checks Ops AI on one machine with Docker, from a clone of this repo.
# Guide: docs/deploy/install.md. Every question has a default and a flag, and an answers file can hold them all, so a
# run can be unattended (CI). Python steps run inside the Ops AI images; the host needs Docker, Compose, curl and tar.
#
#   ./install.sh [install] [options]   install, or check an existing install and change nothing
#   ./install.sh upgrade [--version V] back up, move to version V (default: this checkout's), check, roll back on failure
#   ./install.sh backup [--out DIR]    database, files, knowledge and the settings file, as one .tar.gz
#   ./install.sh restore <file>        put a backup back and check
#   ./install.sh status                version, containers and the health check
#   ./install.sh logs [service]        the last 200 lines (followed on a terminal)
#   ./install.sh uninstall             stop and remove; asks before deleting data
#
# Never prints a secret. Keys are made once, into ops-ai.env (mode 600), and a rerun keeps them.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_DIR=$ROOT/deploy/compose
REGISTRY=ghcr.io/chanl-ai/ops-ai
SECRET_NAME=MODEL_PROVIDER_KEY
SERVICES="platform tools models kb files documents agents"
MIN_DOCKER=24.0
MIN_COMPOSE=2.22
MIN_MEMORY_GB=4
MIN_DISK_GB=15

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }
upper() { printf '%s' "$1" | tr '[:lower:]' '[:upper:]'; }

usage() {
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options (install; each is also an answers-file key, shown in brackets):
  --answers FILE            KEY=VALUE lines; flags win over it
  --yes                     take the default for every question not answered (also when there is no terminal)
  --public-url URL          [PUBLIC_URL] where people open it (default http://localhost:<port>)
  --port N                  [PORT] host port the proxy publishes (default 8890)
  --project NAME            [PROJECT] Compose project name (default ops-ai)
  --org NAME                [ORG_NAME] organisation name
  --admin-email EMAIL       [ADMIN_EMAIL] first admin (default admin@example.com)
  --admin-name NAME         [ADMIN_NAME]
  --admin-password-file F   [ADMIN_PASSWORD] at least 12 characters (default: generated, kept in ops-ai.env)
  --database builtin|URL    [DATABASE] built-in PostgreSQL for a trial, or postgresql://user:pass@host:5432/db
  --db-mode auto|dba        [DB_MODE] auto: the migrate job applies the schema; dba: scripts in ./dba/ for your DBA
  --dba-timeout SECONDS     how long an unattended run waits for the DBA (default 3600)
  --model test|URL          [MODEL] the test model, or an OpenAI-compatible base URL ending in /v1
  --model-name ID           [MODEL_NAME] the provider's model id
  --model-key-file F        [MODEL_API_KEY] the provider key; stored in Secrets through the API, never in ops-ai.env
  --model-input-price N     [MODEL_INPUT_PRICE] per million input tokens (default 0)
  --model-output-price N    [MODEL_OUTPUT_PRICE] per million output tokens (default 0)
  --model-budget N          [MODEL_BUDGET] each model key's spending cap (default 100)
  --version V               [VERSION] image version (default: this checkout's tag, else deploy/release/version)
  --build                   build the images from this checkout instead of pulling them
  --offline FILE            load the images from an offline images.tar.gz instead of pulling them
  --env-file F              settings file (default ./ops-ai.env)
  --admin-url-file F        backup, restore and upgrade in dba mode: a file holding an admin connection string
                            (postgresql://admin:password@host:5432/db) that may dump and restore
EOF
}

# --- arguments ----------------------------------------------------------------------------------------------------------

CMD=install
case ${1:-} in
  install|upgrade|backup|restore|status|logs|uninstall) CMD=$1; shift ;;
  -h|--help|help) usage; exit 0 ;;
esac
ARG=""
YES=0
DELETE_DATA=0
ANSWERS=""
ENV_FILE=$ROOT/ops-ai.env
OUT_DIR=$ROOT/backups
DBA_TIMEOUT=3600
ADMIN_URL=""
A_PUBLIC_URL="" A_PORT="" A_PROJECT="" A_ORG_NAME="" A_ADMIN_EMAIL="" A_ADMIN_NAME="" A_ADMIN_PASSWORD=""
A_DATABASE="" A_DB_MODE="" A_MODEL="" A_MODEL_NAME="" A_MODEL_API_KEY="" A_VERSION="" A_IMAGES="" A_OFFLINE=""
A_MODEL_INPUT_PRICE="" A_MODEL_OUTPUT_PRICE="" A_MODEL_BUDGET=""
F_SET=" "
flag() { eval "A_$1=\$2"; F_SET="$F_SET$1 "; }
need() { [ $# -ge 2 ] || die "$1 needs a value"; }
readfile() { [ -r "$1" ] || die "cannot read $1"; head -n 1 "$1" | tr -d '\r\n'; }
while [ $# -gt 0 ]; do
  case $1 in
    --answers) need "$@"; ANSWERS=$2; shift ;;
    --yes|-y|--non-interactive) YES=1 ;;
    --public-url) need "$@"; flag PUBLIC_URL "$2"; shift ;;
    --port) need "$@"; flag PORT "$2"; shift ;;
    --project) need "$@"; flag PROJECT "$2"; shift ;;
    --org) need "$@"; flag ORG_NAME "$2"; shift ;;
    --admin-email) need "$@"; flag ADMIN_EMAIL "$2"; shift ;;
    --admin-name) need "$@"; flag ADMIN_NAME "$2"; shift ;;
    --admin-password-file) need "$@"; flag ADMIN_PASSWORD "$(readfile "$2")"; shift ;;
    --database) need "$@"; flag DATABASE "$2"; shift ;;
    --db-mode) need "$@"; flag DB_MODE "$2"; shift ;;
    --dba-timeout) need "$@"; DBA_TIMEOUT=$2; shift ;;
    --model) need "$@"; flag MODEL "$2"; shift ;;
    --model-name) need "$@"; flag MODEL_NAME "$2"; shift ;;
    --model-key-file) need "$@"; flag MODEL_API_KEY "$(readfile "$2")"; shift ;;
    --model-input-price) need "$@"; flag MODEL_INPUT_PRICE "$2"; shift ;;
    --model-output-price) need "$@"; flag MODEL_OUTPUT_PRICE "$2"; shift ;;
    --model-budget) need "$@"; flag MODEL_BUDGET "$2"; shift ;;
    --version) need "$@"; flag VERSION "$2"; shift ;;
    --build) flag IMAGES build ;;
    --offline) need "$@"; flag IMAGES offline; A_OFFLINE=$2; shift ;;
    --env-file) need "$@"; ENV_FILE=$2; shift ;;
    --out) need "$@"; OUT_DIR=$2; shift ;;
    --admin-url-file) need "$@"; ADMIN_URL=$(readfile "$2"); shift ;;
    --delete-data) DELETE_DATA=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option $1 (./install.sh --help)" ;;
    *) [ -z "$ARG" ] || die "unexpected argument $1"; ARG=$1 ;;
  esac
  shift
done
[ -t 0 ] || YES=1
case $ENV_FILE in /*) ;; *) ENV_FILE=$PWD/$ENV_FILE ;; esac

if [ -n "$ANSWERS" ]; then
  [ -r "$ANSWERS" ] || die "cannot read answers file $ANSWERS"
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case $line in ''|'#'*) continue ;; esac
    key=${line%%=*}
    value=${line#*=}  # read by the eval below
    case $key in
      PUBLIC_URL|PORT|PROJECT|ORG_NAME|ADMIN_EMAIL|ADMIN_NAME|ADMIN_PASSWORD|DATABASE|DB_MODE|MODEL|MODEL_NAME|MODEL_API_KEY|\
      MODEL_INPUT_PRICE|MODEL_OUTPUT_PRICE|MODEL_BUDGET|VERSION|IMAGES|OFFLINE)
        case $F_SET in *" $key "*) ;; *) eval "A_$key=\$value" ;; esac ;;
      *) die "answers file: unknown key $key" ;;
    esac
  done <"$ANSWERS"
  [ "$A_IMAGES" != offline ] || [ -n "$A_OFFLINE" ] || die "answers file: IMAGES=offline needs OFFLINE=<images.tar.gz>"
fi

# --- the settings file --------------------------------------------------------------------------------------------------

getenv() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 || true; }
setenv() {
  # Values go through the environment, never argv, so a secret is not visible in the process list.
  local tmp
  tmp=$(mktemp "$ENV_FILE.XXXXXX")
  if grep -q "^$1=" "$ENV_FILE"; then
    K=$1 V=$2 awk 'BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"] } index($0, k "=") == 1 { print k "=" v; next } { print }' \
      "$ENV_FILE" >"$tmp"
  else
    cat "$ENV_FILE" >"$tmp"
    printf '%s=%s\n' "$1" "$2" >>"$tmp"
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

load() {
  [ -f "$ENV_FILE" ] || die "no install here: $ENV_FILE does not exist (run ./install.sh first, or pass --env-file)"
  PROJECT=$(getenv OPS_INSTALL_PROJECT)
  PORT=$(getenv OPS_PUBLIC_PORT)
  ORIGIN=$(getenv OPS_PUBLIC_ORIGIN)
  DB_KIND=$(getenv OPS_INSTALL_DATABASE)
  DB_MODE=$(getenv OPS_INSTALL_DB_MODE)
  MODEL_KIND=$(getenv OPS_INSTALL_MODEL)
  IMAGES=$(getenv OPS_INSTALL_IMAGES)
  PREFIX=$(getenv OPS_IMAGE_PREFIX)
  TAG=$(getenv OPS_IMAGE_TAG)
  [ -n "$PROJECT" ] && [ -n "$TAG" ] || die "$ENV_FILE was not written by install.sh (no OPS_INSTALL_PROJECT or OPS_IMAGE_TAG)"
}

compose() {
  local files=(-f "$COMPOSE_DIR/app.yaml")
  [ "$DB_MODE" = dba ] && files+=(-f "$COMPOSE_DIR/dba.yaml")
  if [ "$DB_KIND" = builtin ] || [ "$MODEL_KIND" = test ]; then files+=(-f "$COMPOSE_DIR/try.yaml"); fi
  [ "$DB_KIND" = builtin ] && files+=(--profile postgres)
  [ "$MODEL_KIND" = test ] && files+=(--profile fake-model)
  docker compose -p "$PROJECT" "${files[@]}" --env-file "$ENV_FILE" "$@"
}

# --- small helpers ------------------------------------------------------------------------------------------------------

random_hex() { od -An -N"${1:-16}" -tx1 /dev/urandom | tr -d ' \n'; }
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n 1)" = "$2" ]; }
json_escape() { local s=$1; s=${s//\\/\\\\}; s=${s//\"/\\\"}; printf '%s' "$s"; }

ask() { # ask VAR "question" default [secret]
  local var=$1 question=$2 default=$3 secret=${4:-} current reply
  eval "current=\${A_$var}"
  if [ -n "$current" ]; then return; fi
  if [ "$YES" = 1 ]; then eval "A_$var=\$default"; return; fi
  if [ -n "$secret" ]; then
    read -r -s -p "$question [$( [ -n "$default" ] && echo 'Enter to generate' || echo 'required')]: " reply; echo
  else
    read -r -p "$question [$default]: " reply
  fi
  eval "A_$var=\${reply:-\$default}"
}

# A connection string, as postgresql://user:pass@host:port/db?params, into its parts (password %-decoded).
parse_url() {
  local re='^postgres(ql)?(\+[a-z]+)?://(([^:@/]*)(:([^@]*))?@)?([^:/?]+)(:([0-9]+))?/([^?]+)(\?(.*))?$'
  [[ $1 =~ $re ]] || die "not a PostgreSQL connection string: postgresql://user:password@host:5432/database"
  DB_USER=${BASH_REMATCH[4]}
  DB_PASS=$(printf '%b' "${BASH_REMATCH[6]//%/\\x}")
  DB_HOST=${BASH_REMATCH[7]}
  DB_PORT=${BASH_REMATCH[9]:-5432}
  DB_NAME=${BASH_REMATCH[10]}
  DB_SSL=$(printf '%s' "${BASH_REMATCH[12]}" | tr '&' '\n' | sed -n -e 's/^sslmode=//p' -e 's/^ssl=//p' | head -n 1)
}
# The services' DSN from the connection string as given (asyncpg's driver name, and ssl= for libpq's sslmode=).
service_url() { printf '%s' "$1" | sed -e 's|^postgres\(ql\)\{0,1\}\(+[a-z]*\)\{0,1\}://|postgresql+asyncpg://|' -e 's/\([?&]\)sslmode=/\1ssl=/'; }
asyncpg_url() { # user password -> the services' DSN for the parsed server
  local q=""
  [ -n "$DB_SSL" ] && q="?ssl=$DB_SSL"
  printf 'postgresql+asyncpg://%s:%s@%s:%s/%s%s' "$1" "$2" "$DB_HOST" "$DB_PORT" "$DB_NAME" "$q"
}
libpq() { # dbname [user] -> a psql connection string with no password
  local s="host=$DB_HOST port=$DB_PORT dbname=$1"
  [ -n "${2:-}" ] && s="$s user=$2"
  [ -n "$DB_SSL" ] && s="$s sslmode=$DB_SSL"
  printf '%s' "$s"
}

# The Python steps (deploy/install/install_api.py) inside the platform image on the install's network, as this user so
# it may write into ./dba.
api() {
  local env_args=() name
  mkdir -p "$ROOT/dba"
  for name in OPS_INSTALL_ADMIN_EMAIL OPS_INSTALL_ADMIN_PASSWORD OPS_INSTALL_SECRET_NAME OPS_INSTALL_SECRET_VALUE OPS_DATABASE_URL; do
    env_args+=(-e "$name")
  done
  for name in $SERVICES; do env_args+=(-e "OPS_DATABASE_URL_$(upper "$name")"); done
  compose run --rm -T --no-deps --user "$(id -u):$(id -g)" -v "$ROOT/deploy/install:/install:ro" -v "$ROOT/dba:/dba" \
    "${env_args[@]}" --entrypoint python platform /install/install_api.py "$@"
}
export_dsns() {
  export OPS_DATABASE_URL
  OPS_DATABASE_URL=$(getenv OPS_DATABASE_URL)
  local s
  for s in $SERVICES; do export "OPS_DATABASE_URL_$(upper "$s")=$(getenv "OPS_DATABASE_URL_$(upper "$s")")"; done
}

# --- preflight ----------------------------------------------------------------------------------------------------------

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

preflight() {
  step "Preflight"
  local missing=0 v mem disk root ours
  command -v docker >/dev/null || { say "MISSING Docker 24 or newer: https://docs.docker.com/engine/install/"; exit 1; }
  v=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || { say "MISSING a running Docker daemon you may use (is it started? is this user in the docker group?)"; exit 1; }
  if version_ge "$v" "$MIN_DOCKER"; then say "ok   Docker $v"; else say "MISSING Docker $MIN_DOCKER or newer (found $v)"; missing=1; fi
  v=$(docker compose version --short 2>/dev/null | sed 's/^v//') || v=""
  if [ -n "$v" ] && version_ge "$v" "$MIN_COMPOSE"; then say "ok   Compose $v"; else say "MISSING Docker Compose $MIN_COMPOSE or newer (found ${v:-none})"; missing=1; fi
  for v in curl tar; do
    if command -v $v >/dev/null; then say "ok   $v"; else say "MISSING $v"; missing=1; fi
  done
  if [ "${A_IMAGES:-$IMAGES}" = build ]; then
    if command -v git >/dev/null && git -C "$ROOT" rev-parse HEAD >/dev/null 2>&1; then say "ok   git checkout (for --build)"; else say "MISSING a git checkout (--build builds from git HEAD)"; missing=1; fi
  fi
  mem=$(( $(docker info --format '{{.MemTotal}}') / 1024 / 1024 / 1024 ))
  if [ "$mem" -ge "$MIN_MEMORY_GB" ]; then say "ok   memory for containers: ${mem} GB"; else say "MISSING memory: Docker has ${mem} GB, needs $MIN_MEMORY_GB GB (6 GB or more is better)"; missing=1; fi
  root=$(docker info --format '{{.DockerRootDir}}')
  [ -d "$root" ] || root=$ROOT
  disk=$(( $(df -Pk "$root" | awk 'NR == 2 { print $4 }') / 1024 / 1024 ))
  if [ "$disk" -ge "$MIN_DISK_GB" ]; then say "ok   free disk: ${disk} GB"; else say "MISSING free disk: ${disk} GB where Docker keeps images, needs $MIN_DISK_GB GB"; missing=1; fi
  ours=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=proxy" -q)
  if [ -n "$ours" ]; then say "ok   port $PORT (this install's proxy)";
  elif port_busy "$PORT"; then say "MISSING a free port: $PORT is in use (choose another with --port)"; missing=1;
  else say "ok   port $PORT is free"; fi
  [ "$missing" = 0 ] || die "fix the lines marked MISSING, then run ./install.sh again"
}

# --- images -------------------------------------------------------------------------------------------------------------

checkout_version() {
  local t
  if t=$(git -C "$ROOT" describe --tags --exact-match HEAD 2>/dev/null); then printf '%s' "${t#v}"; return; fi
  tr -d ' \n' <"$ROOT/deploy/release/version"
}

# Pull, build or load the images for $PREFIX/$TAG.
get_images() {
  local targets="" s out
  case $IMAGES in
    pull)
      step "Images: pulling $PREFIX/*:$TAG"
      compose pull --quiet || die "pulling $PREFIX/*:$TAG failed (is version $TAG published? try --version, --build or --offline)"
      [ "$DB_MODE" = dba ] && { docker pull -q "$PREFIX/db-scripts:$TAG" >/dev/null || die "pulling $PREFIX/db-scripts:$TAG failed"; }
      ;;
    build)
      step "Images: building $PREFIX/*:$TAG from this checkout's HEAD"
      for s in platform agents tools models kb files documents opa proxy console; do targets="$targets $s"; done
      [ "$DB_MODE" = dba ] && targets="$targets db-scripts"
      TARGETS=$targets IMAGE_PREFIX=$PREFIX sh "$ROOT/deploy/release/images.sh" HEAD "$TAG"
      if [ "$DB_KIND" = builtin ]; then docker pull -q postgres:17-alpine >/dev/null; fi
      ;;
    offline)
      step "Images: loading $A_OFFLINE"
      out=$(docker load -i "$A_OFFLINE") || die "docker load -i $A_OFFLINE failed"
      s=$(printf '%s\n' "$out" | sed -n 's|^Loaded image: \(.*\)/platform:\(.*\)$|\1 \2|p' | head -n 1)
      [ -n "$s" ] || die "$A_OFFLINE holds no Ops AI platform image"
      PREFIX=${s% *}
      TAG=${s#* }
      say "loaded $PREFIX/*:$TAG"
      if [ "$DB_KIND" = builtin ]; then docker pull -q postgres:17-alpine >/dev/null; fi
      ;;
  esac
}

# --- the check ----------------------------------------------------------------------------------------------------------

# Health through the published port, the console's sign-in page, then a sign-in as the first admin and one read from
# every service through the proxy. Exit 1 on any failure.
check() {
  step "Check"
  local base="http://127.0.0.1:$PORT" failed=0 pw email body token team code path hdr
  pass() { say "PASS $*"; }
  fail() { say "FAIL $*"; failed=1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$base/api/platform/v1/health") || code=000
  [ "$code" = 200 ] && pass "platform health ($base/api/platform/v1/health)" || fail "platform health answered $code"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$base/login") || code=000
  [ "$code" = 200 ] && pass "console sign-in page" || fail "console /login answered $code"
  email=$(getenv OPS_BOOTSTRAP_ADMIN_EMAIL)
  pw=${A_ADMIN_PASSWORD:-$(getenv OPS_BOOTSTRAP_ADMIN_PASSWORD)}
  if [ -z "$pw" ]; then
    say "SKIP sign-in: the first admin's password is no longer in $(basename "$ENV_FILE") (pass --admin-password-file to check it)"
  else
    body=$(printf '{"email":"%s","password":"%s"}' "$(json_escape "$email")" "$(json_escape "$pw")")
    body=$(printf '%s' "$body" | curl -s --max-time 20 -H 'Content-Type: application/json' --data-binary @- \
      "$base/api/platform/v1/auth/sign-in") || body=""
    token=$(printf '%s' "$body" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
    team=$(printf '%s' "$body" | sed -n 's/.*"teamId":"\([^"]*\)".*/\1/p')
    if [ -n "$token" ] && [ -n "$team" ]; then
      pass "the first admin ($email) signs in"
      hdr=$(mktemp)
      printf 'Authorization: Bearer %s\nX-Team-Id: %s\n' "$token" "$team" >"$hdr"
      for path in platform/v1/me agents/v1/agents agents/v1/model-aliases tools/v1/secrets kb/v1/knowledge-bases \
        files/v1/files documents/v1/document-types; do
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H @"$hdr" "$base/api/$path") || code=000
        [ "$code" = 200 ] && pass "GET /api/$path" || fail "GET /api/$path answered $code"
      done
      rm -f "$hdr"
    else
      fail "sign-in as $email did not return a session"
    fi
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$base/api/agents/health") || code=000
  [ "$code" = 200 ] && pass "agents health (a model is connected)" || fail "agents health answered $code (is a model connected?)"
  return $failed
}

running_ok() { # every service of the install up, healthy where it has a check, on $PREFIX/*:$TAG
  local want lines s line
  want="platform agents worker tools models kb files documents opa console proxy"
  [ "$DB_KIND" = builtin ] && want="$want postgres"
  [ "$MODEL_KIND" = test ] && want="$want fake-model"
  lines=$(compose ps --format '{{.Service}} {{.Image}} {{.State}} {{.Health}}' 2>/dev/null) || return 1
  for s in $want; do
    line=$(printf '%s\n' "$lines" | awk -v s="$s" '$1 == s')
    [ -n "$line" ] || return 1
    case $line in *" running "*|*" running") ;; *) return 1 ;; esac
    case $line in *unhealthy*|*starting*) return 1 ;; esac
    case $s in postgres) ;; *) case $line in "$s $PREFIX/"*":$TAG "*) ;; *) return 1 ;; esac ;; esac
  done
}

# --- database in dba mode -----------------------------------------------------------------------------------------------

dba_scripts() { # copy /db/postgres out of the db-scripts image into ./dba/postgres
  local id
  rm -rf "$ROOT/dba/postgres"
  mkdir -p "$ROOT/dba"
  id=$(docker create "$PREFIX/db-scripts:$TAG" none)
  docker cp "$id:/db/postgres" "$ROOT/dba/postgres" >/dev/null
  docker rm "$id" >/dev/null
  chmod -R go-rwx "$ROOT/dba"
}

wait_for_dba() { # $1: what the DBA was asked to do
  if [ "$YES" = 1 ]; then
    say "Waiting up to ${DBA_TIMEOUT}s for the database to reach this release's schema ($1)..."
    local waited=0
    until api schema >/dev/null 2>&1; do
      [ "$waited" -lt "$DBA_TIMEOUT" ] || { api schema || true; die "the schema is not current after ${DBA_TIMEOUT}s"; }
      sleep 10
      waited=$((waited + 10))
    done
  else
    read -r -p "Press Enter when the DBA has run them... " _
    until api schema; do
      read -r -p "The schema is not current yet. Press Enter to check again, or Ctrl-C to stop... " _
    done
  fi
  api schema
}

dba_install() {
  local admin s pw
  step "Database: scripts for your DBA in ./dba/"
  dba_scripts
  admin=$(getenv OPS_INSTALL_DB_ADMIN)
  admin=${admin:-<admin>}
  {
    printf '%s\n' "-- Ops AI $TAG: run once as the server admin, in database postgres. Holds the runtime logins' passwords:"
    printf '%s\n' "-- delete this file once it has run. Written by install.sh."
    printf '%s\n' '\set ON_ERROR_STOP 1' '\ir postgres/roles.sql'
    for s in $SERVICES; do
      pw=$(getenv "OPS_DATABASE_URL_$(upper "$s")" | sed -n 's|^[^:]*://[^:]*:\([^@]*\)@.*|\1|p')
      printf "ALTER ROLE ops_%s_runtime PASSWORD '%s';\n" "$s" "$pw"
    done
    printf '%s\n' 'GRANT ops_migrator TO CURRENT_USER;' "CREATE DATABASE \"$DB_NAME\" OWNER ops_migrator;"
  } >"$ROOT/dba/1-server.sql"
  chmod 600 "$ROOT/dba/1-server.sql"
  cat <<EOF

Ask your DBA to run these three commands from this folder ($ROOT), as the server admin ($admin):

  1. psql "$(libpq postgres "$admin")" -v ON_ERROR_STOP=1 -f dba/1-server.sql
  2. psql "$(libpq "$DB_NAME" "$admin")" -v ON_ERROR_STOP=1 -c "SET ROLE ops_migrator" -f dba/postgres/bundle.sql
  3. psql "$(libpq "$DB_NAME" "$admin")" -v ON_ERROR_STOP=1 -c "SET ROLE ops_migrator" -f dba/postgres/grants.sql

1 makes the roles, sets each service's login password and creates database $DB_NAME owned by ops_migrator; 2 applies
the schema as ops_migrator; 3 grants each service's login its own tables. The files are in dba/postgres for review
(manifest.json, SHA256SUMS). No container gets a login that may change the schema.
EOF
  wait_for_dba "the three commands above"
}

# --- install ------------------------------------------------------------------------------------------------------------

questions() {
  step "Questions"
  ask PORT "Port to publish on this machine" 8890
  ask PUBLIC_URL "Public URL people open" "http://localhost:$A_PORT"
  ask PROJECT "Compose project name" ops-ai
  ask ORG_NAME "Organisation name" "My organisation"
  ask ADMIN_EMAIL "First admin's email" admin@example.com
  ask ADMIN_NAME "First admin's name" "First Admin"
  ask ADMIN_PASSWORD "First admin's password (12+ characters)" "" secret
  if [ -z "$A_ADMIN_PASSWORD" ]; then A_ADMIN_PASSWORD="admin-$(random_hex 12)"; GENERATED_PASSWORD=1; fi
  [ ${#A_ADMIN_PASSWORD} -ge 12 ] || die "the first admin's password needs at least 12 characters"
  ask DATABASE "Database: 'builtin' for a trial PostgreSQL, or your connection string" builtin
  if [ "$A_DATABASE" = builtin ]; then A_DB_MODE=${A_DB_MODE:-auto}; else ask DB_MODE "Database mode: auto (migrate job) or dba (scripts for your DBA)" auto; fi
  case $A_DB_MODE in auto|dba) ;; *) die "database mode is auto or dba, not $A_DB_MODE" ;; esac
  [ "$A_DATABASE" != builtin ] || [ "$A_DB_MODE" = auto ] || die "dba mode needs your own PostgreSQL (--database <connection string>)"
  ask MODEL "Model: 'test' for the built-in test model, or an OpenAI-compatible base URL ending in /v1" test
  if [ "$A_MODEL" != test ]; then
    ask MODEL_NAME "The provider's model id" ""
    [ -n "$A_MODEL_NAME" ] || die "name the provider's model with --model-name"
    ask MODEL_API_KEY "The provider's API key (stored in Secrets, not in ops-ai.env)" "" secret
    [ -n "$A_MODEL_API_KEY" ] || die "the provider key is required for $A_MODEL (--model-key-file)"
  fi
}

write_env() {
  local keys s pw line
  step "Settings: $ENV_FILE (mode 600)"
  cp "$COMPOSE_DIR/app.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  setenv OPS_PUBLIC_ORIGIN "${A_PUBLIC_URL%/}"
  setenv OPS_PUBLIC_PORT "$A_PORT"
  setenv OPS_IMAGE_PREFIX "$PREFIX"
  setenv OPS_IMAGE_TAG "$TAG"
  setenv OPS_BOOTSTRAP_TENANT_NAME "$A_ORG_NAME"
  setenv OPS_BOOTSTRAP_ADMIN_EMAIL "$A_ADMIN_EMAIL"
  setenv OPS_BOOTSTRAP_ADMIN_NAME "$A_ADMIN_NAME"
  setenv OPS_BOOTSTRAP_ADMIN_PASSWORD "$A_ADMIN_PASSWORD"
  if [ "$DB_KIND" = builtin ]; then
    pw=$(random_hex 16)
    setenv OPS_TRY_POSTGRES_PASSWORD "$pw"
    setenv OPS_DATABASE_URL "postgresql+asyncpg://ops:$pw@postgres:5432/ops"
  elif [ "$DB_MODE" = auto ]; then
    setenv OPS_DATABASE_URL "$(service_url "$A_DATABASE")"
  else
    for s in $SERVICES; do setenv "OPS_DATABASE_URL_$(upper "$s")" "$(asyncpg_url "ops_${s}_runtime" "$(random_hex 16)")"; done
  fi
  keys=$(docker run --rm --entrypoint python "$PREFIX/platform:$TAG" /app/deploy/fly/generate_keys.py) ||
    die "generating keys with $PREFIX/platform:$TAG failed"
  while IFS= read -r line; do setenv "${line%%=*}" "${line#*=}"; done <<<"$keys"
  {
    printf '\n# --- install.sh: how this install was made; ./install.sh reads these on every run ----------------------------\n'
    printf 'OPS_INSTALL_PROJECT=%s\nOPS_INSTALL_DATABASE=%s\nOPS_INSTALL_DB_MODE=%s\nOPS_INSTALL_MODEL=%s\nOPS_INSTALL_IMAGES=%s\n' \
      "$PROJECT" "$DB_KIND" "$DB_MODE" "$MODEL_KIND" "$IMAGES"
    if [ "$MODEL_KIND" = provider ]; then printf 'OPS_INSTALL_MODEL_URL=%s\nOPS_INSTALL_MODEL_NAME=%s\n' "$A_MODEL" "$A_MODEL_NAME"; fi
    if [ "$DB_MODE" = dba ]; then printf 'OPS_INSTALL_DB_ADMIN=%s\n' "${DB_USER:-}"; fi
  } >>"$ENV_FILE"
  say "keys generated: $(grep -c '^OPS_SVC_KEY_[A-Z]*=.' "$ENV_FILE") service keys, platform, review and secrets keys (not shown)"
}

connect_model() {
  local base model ref=() kid key prices
  [ -z "$(getenv OPS_MODELS_KEY_AGENTS)" ] || [ -z "$(getenv OPS_MODELS_KEY_DOCUMENTS)" ] || { say "model: already connected"; return; }
  step "Model"
  if [ "$MODEL_KIND" = test ]; then
    base=http://fake-model:8746/v1
    model=fake-chat
    prices=(--input-price 1 --output-price 1 --budget 5)
    say "model: the built-in test model (answers from fixed rules; not for production)"
  else
    base=$(getenv OPS_INSTALL_MODEL_URL)
    model=$(getenv OPS_INSTALL_MODEL_NAME)
    if [ -n "$A_MODEL_API_KEY" ]; then
      OPS_INSTALL_ADMIN_EMAIL=$(getenv OPS_BOOTSTRAP_ADMIN_EMAIL) OPS_INSTALL_ADMIN_PASSWORD=$A_ADMIN_PASSWORD \
        OPS_INSTALL_SECRET_NAME=$SECRET_NAME OPS_INSTALL_SECRET_VALUE=$A_MODEL_API_KEY api secret
    fi
    ref=(--key-ref "$SECRET_NAME")
    prices=(--input-price "${A_MODEL_INPUT_PRICE:-0}" --output-price "${A_MODEL_OUTPUT_PRICE:-0}" --budget "${A_MODEL_BUDGET:-100}")
    say "model: $model at $base, its key read from Secrets ($SECRET_NAME)"
  fi
  for kid in agents documents; do
    [ -z "$(getenv "OPS_MODELS_KEY_$(upper $kid)")" ] || continue
    key=$(compose run --rm -T --no-deps agents python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
      --base-url "$base" ${ref[@]+"${ref[@]}"} --alias default --model "$model" "${prices[@]}" --key-id "purpose:$kid" |
      sed -n 's/^OPS_MODELS_KEY=//p') || die "connecting the model for $kid failed"
    [ -n "$key" ] || die "models-service issued no key for purpose:$kid (it exists already: rotate it in the console, then set OPS_MODELS_KEY_$(upper $kid))"
    setenv "OPS_MODELS_KEY_$(upper $kid)" "$key"
    say "model: key for $kid-service issued and saved to $(basename "$ENV_FILE")"
  done
}

start() {
  local first="migrate platform tools models kb files opa"
  [ "$DB_KIND" = builtin ] && first="$first postgres"
  [ "$MODEL_KIND" = test ] && first="$first fake-model"
  step "Starting: database, migrations and services"
  # shellcheck disable=SC2086
  compose up -d --wait --wait-timeout 900 $first
  connect_model
  step "Starting: agents, worker, console and proxy"
  compose up -d --wait --wait-timeout 900
}

finish() {
  cat <<EOF

Ops AI $TAG is running.

  Open:      $(getenv OPS_PUBLIC_ORIGIN)   (on this machine: http://localhost:$PORT)
  Sign in:   $(getenv OPS_BOOTSTRAP_ADMIN_EMAIL)
  Password:  the one you gave$([ "${GENERATED_PASSWORD:-0}" = 1 ] && printf ', or the generated one: see OPS_BOOTSTRAP_ADMIN_PASSWORD in %s' "$(basename "$ENV_FILE")")

Change the password after the first sign-in, then delete the OPS_BOOTSTRAP_ADMIN_PASSWORD line from $(basename "$ENV_FILE").
Keep $(basename "$ENV_FILE") safe and with your backups: its keys unlock stored credentials.
Next: ./install.sh status | backup | upgrade | logs [service]
EOF
}

install() {
  local began
  began=$(date +%s)
  if [ -f "$ENV_FILE" ]; then
    load
    say "Found $(basename "$ENV_FILE"): install $PROJECT at version $TAG. Its keys and answers are kept."
    if running_ok; then
      check || die "the install is running but its check failed (./install.sh logs)"
      say ""
      say "Already installed at version $TAG and healthy; nothing changed."
      return
    fi
    preflight
    A_ADMIN_PASSWORD=${A_ADMIN_PASSWORD:-$(getenv OPS_BOOTSTRAP_ADMIN_PASSWORD)}
    get_images
    if [ "$DB_MODE" = dba ]; then
      export_dsns
      parse_url "$(getenv OPS_DATABASE_URL_PLATFORM)"
      api schema >/dev/null 2>&1 || dba_install
    fi
  else
    questions
    PROJECT=$A_PROJECT
    PORT=$A_PORT
    if [ "$A_DATABASE" = builtin ]; then DB_KIND=builtin; else DB_KIND=external; parse_url "$A_DATABASE"; fi
    DB_MODE=$A_DB_MODE
    if [ "$A_MODEL" = test ]; then MODEL_KIND="test"; else MODEL_KIND="provider"; fi
    IMAGES=${A_IMAGES:-pull}
    case $IMAGES in pull|build|offline) ;; *) die "images are pull, build or offline, not $IMAGES" ;; esac
    TAG=${A_VERSION:-$(checkout_version)}
    if [ "$IMAGES" = pull ]; then PREFIX=$REGISTRY; else PREFIX=ops-ai-local; fi
    preflight
    ENV_FILE_PENDING=1
    # compose reads the env file, so pulling waits for it: a first pull runs against a stub holding only the names.
    printf 'OPS_IMAGE_PREFIX=%s\nOPS_IMAGE_TAG=%s\nOPS_PUBLIC_ORIGIN=http://localhost\nOPS_SERVICE_PUBLIC_KEYS={}\n' "$PREFIX" "$TAG" >"$ENV_FILE"
    trap '[ "${ENV_FILE_PENDING:-0}" = 1 ] && rm -f "$ENV_FILE"' EXIT
    get_images_stub
    write_env
    ENV_FILE_PENDING=0
    trap - EXIT
    if [ "$DB_MODE" = dba ]; then export_dsns; dba_install; fi
  fi
  start
  check || die "installed, but the check failed (./install.sh logs)"
  finish
  say "Took $(( $(date +%s) - began ))s."
}

# The first pull, before the real env file exists: every ${VAR:?} in app.yaml must resolve, so the stub fills them.
get_images_stub() {
  local s
  for s in OPS_PLATFORM_SIGNING_KEY OPS_REVIEW_KEY OPS_SECRETS_KEY OPS_DATABASE_URL OPS_DATABASE_URL_PLATFORM; do printf '%s=stub\n' "$s" >>"$ENV_FILE"; done
  for s in $SERVICES; do printf 'OPS_SVC_KEY_%s=stub\n' "$(upper "$s")" >>"$ENV_FILE"; done
  get_images
}

# --- backup and restore -------------------------------------------------------------------------------------------------

db_admin() { # sets DB_* to a login that may dump and restore the whole database, or dies
  if [ "$DB_KIND" = builtin ]; then return; fi
  if [ -n "$ADMIN_URL" ]; then parse_url "$ADMIN_URL"; return; fi
  [ "$DB_MODE" = auto ] || die "dba mode: pass --admin-url-file <file holding postgresql://admin:password@host:5432/db> (pg_dump as a runtime login stops on row-level security), or ask the DBA to back up the database"
  parse_url "$(getenv OPS_DATABASE_URL | sed 's|+asyncpg||')"
}

pg() { # pg <tool> [args]: a postgres:17 client against the parsed server, password through the environment
  PGPASSWORD=$DB_PASS docker run --rm -i -e PGPASSWORD postgres:17-alpine "$@"
}

backup() {
  load
  db_admin
  local work stamp name v
  mkdir -p "$OUT_DIR"
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  name=$OUT_DIR/ops-ai-$PROJECT-$TAG-$stamp.tar.gz
  work=$(mktemp -d)
  step "Backup: $name"
  if [ "$DB_KIND" = builtin ]; then
    compose exec -T postgres pg_dump -U ops -Fc ops >"$work/db.dump"
  else
    pg pg_dump -Fc "$(libpq "$DB_NAME" "$DB_USER")" >"$work/db.dump"
  fi
  [ -s "$work/db.dump" ] || die "the database dump is empty"
  for v in files-data kb-data; do
    docker run --rm -v "${PROJECT}_$v:/data:ro" alpine tar czf - -C /data . >"$work/$v.tgz"
  done
  cp "$ENV_FILE" "$work/ops-ai.env"
  printf 'version=%s\nproject=%s\ndatabase=%s\ndb_mode=%s\ntaken=%s\n' "$TAG" "$PROJECT" "$DB_KIND" "$DB_MODE" "$stamp" >"$work/backup.txt"
  tar czf "$name" -C "$work" .
  rm -rf "$work"
  chmod 600 "$name"
  say "backup: $(du -h "$name" | cut -f1) $name (holds ops-ai.env and its keys; keep it as safe as the database)"
  LAST_BACKUP=$name
}

restore() {
  local file=${1:?usage: ./install.sh restore <backup.tar.gz>} work v
  [ -r "$file" ] || die "cannot read $file"
  work=$(mktemp -d)
  tar xzf "$file" -C "$work"
  [ -s "$work/db.dump" ] && [ -f "$work/ops-ai.env" ] || die "$file is not an install.sh backup"
  if [ ! -f "$ENV_FILE" ]; then
    cp "$work/ops-ai.env" "$ENV_FILE"
    say "restore: no settings here; using the backup's"
  elif [ "$(sed -n 's/^OPS_SECRETS_KEY=//p' "$work/ops-ai.env")" != "$(getenv OPS_SECRETS_KEY)" ]; then
    die "the backup was made with another OPS_SECRETS_KEY; its stored credentials would not open. Move $ENV_FILE aside to restore with the backup's settings"
  fi
  load
  db_admin
  step "Restore: $file (version $(sed -n 's/^version=//p' "$work/backup.txt"))"
  [ "$(sed -n 's/^version=//p' "$work/backup.txt")" = "$TAG" ] || say "note: the backup is from version $(sed -n 's/^version=//p' "$work/backup.txt"), the install runs $TAG"
  compose stop >/dev/null 2>&1 || true
  if [ "$DB_KIND" = builtin ]; then
    compose up -d --wait postgres >/dev/null
    compose exec -T postgres psql -q -U ops -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS ops WITH (FORCE)' -c 'CREATE DATABASE ops'
    compose exec -T postgres pg_restore -U ops -d ops --exit-on-error <"$work/db.dump"
  else
    pg psql -q -v ON_ERROR_STOP=1 "$(libpq postgres "$DB_USER")" -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE)" -c "CREATE DATABASE \"$DB_NAME\""
    [ "$DB_MODE" = dba ] && pg psql -q -v ON_ERROR_STOP=1 "$(libpq postgres "$DB_USER")" -c "ALTER DATABASE \"$DB_NAME\" OWNER TO ops_migrator"
    pg pg_restore -d "$(libpq "$DB_NAME" "$DB_USER")" --exit-on-error <"$work/db.dump"
  fi
  for v in files-data kb-data; do
    docker volume create "${PROJECT}_$v" >/dev/null
    docker run --rm -i -v "${PROJECT}_$v:/data" alpine sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null; tar xzf - -C /data' <"$work/$v.tgz"
  done
  rm -rf "$work"
  compose up -d --wait --wait-timeout 900
  PORT=$(getenv OPS_PUBLIC_PORT)
  check || die "restored, but the check failed (./install.sh logs)"
  say "Restored from $file."
}

# --- upgrade ------------------------------------------------------------------------------------------------------------

upgrade() {
  load
  local from=$TAG to from_prefix=$PREFIX
  to=${A_VERSION:-$(checkout_version)}
  [ -z "$A_IMAGES" ] || IMAGES=$A_IMAGES
  if [ "$to" = "$from" ] && [ "$IMAGES" != offline ] && running_ok; then
    say "Already at version $from; checking it."
    check || die "the check failed on version $from (./install.sh logs); nothing was changed"
    say ""
    say "Already at version $from; nothing changed."
    return
  fi
  preflight
  backup
  # backup reloaded the settings; this run's image source wins over the install's for the move.
  [ -z "$A_IMAGES" ] || IMAGES=$A_IMAGES
  TAG=$to
  get_images
  step "Upgrade: $from to $TAG"
  setenv OPS_IMAGE_PREFIX "$PREFIX"
  setenv OPS_IMAGE_TAG "$TAG"
  if [ "$DB_MODE" = dba ]; then
    export_dsns
    if ! api schema >/dev/null 2>&1; then
      local dir=dba/upgrade-$from-to-$TAG admin
      rm -rf "${ROOT:?}/$dir"
      dba_scripts
      api upgrade-sql "/$dir"
      admin=$(getenv OPS_INSTALL_DB_ADMIN)
      admin=${admin:-<admin>}
      parse_url "$(getenv OPS_DATABASE_URL_PLATFORM)"
      say ""
      say "Ask your DBA to run, as the server admin, each file in $dir in order of its number, then the grants:"
      for f in "$ROOT/$dir"/*.sql; do
        [ -e "$f" ] || continue
        say "  psql \"$(libpq "$DB_NAME" "$admin")\" -v ON_ERROR_STOP=1 -c \"SET ROLE ops_migrator\" -f $dir/$(basename "$f")"
      done
      say "  psql \"$(libpq "$DB_NAME" "$admin")\" -v ON_ERROR_STOP=1 -c \"SET ROLE ops_migrator\" -f dba/postgres/grants.sql"
      wait_for_dba "the upgrade files above"
    fi
  fi
  if compose up -d --wait --wait-timeout 900 && check; then
    say ""
    say "Upgraded from $from to $TAG. Backup from before: $LAST_BACKUP"
    return
  fi
  to=$TAG
  step "Rollback: the check failed on $to; back to $from"
  setenv OPS_IMAGE_PREFIX "$from_prefix"
  setenv OPS_IMAGE_TAG "$from"
  PREFIX=$from_prefix
  TAG=$from
  if [ "$DB_MODE" = dba ] && [ -z "$ADMIN_URL" ]; then
    compose up -d --wait --wait-timeout 900 || true
    die "rolled the images back to $from; ask the DBA to restore the database from before the upgrade, then ./install.sh status"
  fi
  restore "$LAST_BACKUP"
  die "the upgrade to $to failed its check; rolled back to $from from $LAST_BACKUP"
}

# --- status, logs, uninstall --------------------------------------------------------------------------------------------

status() {
  load
  say "Ops AI $TAG ($PREFIX), project $PROJECT, database $DB_KIND ($DB_MODE), model $MODEL_KIND"
  say "Open: $ORIGIN (on this machine: http://localhost:$PORT)"
  compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Image}}'
  check
}

logs() {
  load
  local follow=()
  [ -t 1 ] && follow=(--follow)
  # shellcheck disable=SC2086
  compose logs --tail 200 ${follow[@]+"${follow[@]}"} $ARG
}

uninstall() {
  load
  local reply
  if [ "$YES" != 1 ]; then
    read -r -p "Stop and remove Ops AI (project $PROJECT)? [y/N] " reply
    case $reply in y|Y|yes) ;; *) say "Nothing removed."; return ;; esac
    read -r -p "Also delete its data: the database, files and knowledge volumes? This cannot be undone. [y/N] " reply
    case $reply in y|Y|yes) DELETE_DATA=1 ;; esac
  fi
  if [ "$DELETE_DATA" = 1 ]; then
    compose down -v --remove-orphans
    say "Removed project $PROJECT and its volumes. $(basename "$ENV_FILE") is kept; delete it yourself when no backup needs it."
  else
    compose down --remove-orphans
    say "Removed project $PROJECT's containers; its volumes and $(basename "$ENV_FILE") are kept (./install.sh reinstalls on them)."
  fi
}

case $CMD in
  install) install ;;
  upgrade) upgrade ;;
  backup) backup ;;
  restore) restore "$ARG" ;;
  status) status ;;
  logs) logs ;;
  uninstall) uninstall ;;
esac
