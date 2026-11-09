#!/usr/bin/env bash
# Runs inside a cloud box (a Fly Sprite, no Docker): gets the checkout, installs, runs the side services as plain
# programs the box keeps running, seeds the demo data and brings the stack up behind one public address.
# Safe to run again: it wakes what is stopped and updates what is behind.
#
#   BRANCH=main            the branch to check out (a branch that is not on origin is refused)
#   BOX_RESET=1            wipe the database to the seeded state (make reset-db) before the stack starts
#   OPS_DATABASE_URL=...   use this database and start no local PostgreSQL (the setting that moves it outside the box)
#   OPS_PUBLIC_ORIGIN=...  the box's https address; read from the box itself when not given
#
# Called by scripts/box.sh, which copies it into the box. Progress is one line per step with its seconds.
set -euo pipefail

BRANCH=${BRANCH:-main}
REPO=${OPS_BOX_REPO:-$HOME/ops-ai}
BOX=$HOME/box
BIN=$BOX/bin
SVC=$BOX/svc
mkdir -p "$BIN" "$SVC" "$BOX/pg-run"

OPA_VERSION=1.21.1
MAILPIT_VERSION=1.27.0
GREENMAIL_VERSION=2.1.3
CADDY_VERSION=2.10.2

step() { STEP_AT=$SECONDS; printf '[box] %s\n' "$*"; }
done_step() { printf '[box]   %ss\n' "$((SECONDS - STEP_AT))"; }
die() { printf '[box] %s\n' "$*" >&2; exit 1; }

export UV_PYTHON=3.12
export PATH="$BIN:/usr/lib/postgresql/18/bin:$PATH"
export CI=true

if [ -z "${OPS_PUBLIC_ORIGIN:-}" ]; then
  OPS_PUBLIC_ORIGIN=$(sprite-env info 2>/dev/null | grep -o 'https://[^ ]*' | head -1 | sed 's:/*$::')
fi
[ -n "$OPS_PUBLIC_ORIGIN" ] || die "no public address: pass OPS_PUBLIC_ORIGIN"
export OPS_PUBLIC_ORIGIN
EXTERNAL_DB=0
[ -n "${OPS_DATABASE_URL:-}" ] && EXTERNAL_DB=1

# ---- packages and the four stand-ins ---------------------------------------------------------------------------
step "system packages"
need=()
for p in postgresql netcat-openbsd; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
if [ "${#need[@]}" -gt 0 ]; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null
  # The package starts its own cluster on 5432; the box runs its own below.
  sudo systemctl disable --now postgresql >/dev/null 2>&1 || true
  sudo pkill -x postgres >/dev/null 2>&1 || true
fi
done_step

step "side service programs"
fetch() { [ -s "$2" ] || { curl -fsSL "$1" -o "$2.part" && mv "$2.part" "$2"; }; }
fetch "https://github.com/open-policy-agent/opa/releases/download/v$OPA_VERSION/opa_linux_amd64_static" "$BIN/opa"
fetch "https://repo1.maven.org/maven2/com/icegreen/greenmail-standalone/$GREENMAIL_VERSION/greenmail-standalone-$GREENMAIL_VERSION.jar" "$BIN/greenmail.jar"
if [ ! -x "$BIN/mailpit" ]; then
  curl -fsSL "https://github.com/axllent/mailpit/releases/download/v$MAILPIT_VERSION/mailpit-linux-amd64.tar.gz" | tar -xz -C "$BIN" mailpit
fi
if [ ! -x "$BIN/caddy" ]; then
  curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v$CADDY_VERSION/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" | tar -xz -C "$BIN" caddy
fi
chmod +x "$BIN/opa"
done_step

# ---- the checkout ----------------------------------------------------------------------------------------------
step "checkout $BRANCH"
if [ ! -d "$REPO/.git" ]; then
  git clone -q https://github.com/chanl-ai/ops-ai.git "$REPO"
fi
cd "$REPO"
git fetch -q origin "$BRANCH"
# The stack runs old code until it is stopped, so a branch change stops it first.
if [ "$(git rev-parse HEAD 2>/dev/null)" != "$(git rev-parse FETCH_HEAD)" ] && [ -x scripts/stack.sh ]; then
  OPS_INFRA=external make -s down KEEP_DB=1 >/dev/null 2>&1 || true
fi
git checkout -q -f -B "$BRANCH" FETCH_HEAD
git clean -fdq -e node_modules -e .venv -e .run -e .logs -e .data -e .next
done_step

step "install"
# pnpm comes from the version package.json pins; the shim goes beside the other box programs, since the box's global npm
# directory is not on a login shell's PATH.
corepack enable --install-directory "$BIN"
uv python install -q 3.12
make -s install >"$BOX/install.log" 2>&1 || { tail -15 "$BOX/install.log" >&2; die "install failed (log $BOX/install.log)"; }
done_step

# ---- side services, kept by the box so they come back after a sleep -------------------------------------------
BOX_IP=$(hostname -I | awk '{print $1}')
[ -n "$BOX_IP" ] || die "the box has no address"
step "host names (box address $BOX_IP)"
# dev_egress.py refuses loopback, so the mail stand-ins and the fake bank answer at the box's own address.
sudo sed -i '/# ops-ai-box$/d' /etc/hosts
{
  echo "127.0.0.1 postgres opa # ops-ai-box"
  echo "$BOX_IP mailpit greenmail api.bank.test # ops-ai-box"
} | sudo tee -a /etc/hosts >/dev/null
done_step

# A service is a small script the box runs and restarts: sprite-env keeps it across a sleep.
SERVICES_CHANGED=0
define_service() { # name, script body
  local name=$1 file=$SVC/$1.sh next
  next=$(mktemp)
  printf '#!/usr/bin/env bash\nset -e\nexport PATH="%s"\n%s\n' "$PATH" "$2" >"$next"
  chmod +x "$next"
  if sprite-env services get "$name" 2>/dev/null | grep -q '"status":"running"' && cmp -s "$next" "$file"; then
    rm -f "$next"
    return 0
  fi
  mv "$next" "$file"
  # A restarted side service drops the stack's open connections to it, so the stack starts again below.
  SERVICES_CHANGED=1
  if sprite-env services get "$name" >/dev/null 2>&1; then
    sprite-env services restart "$name" >/dev/null 2>&1 || sprite-env services start "$name" >/dev/null 2>&1 || true
  else
    sprite-env services create "$name" --cmd bash --args "$file" --no-stream ${SERVICE_ARGS:-} >/dev/null 2>&1
  fi
}
wait_port() { # host port seconds
  local i
  for ((i = 0; i < $3; i++)); do (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null && return 0; sleep 1; done
  die "$1:$2 did not answer within $3s"
}

step "side services"
if [ "$EXTERNAL_DB" = 0 ]; then
  if [ ! -f "$BOX/pg/PG_VERSION" ]; then
    printf 'ops' >"$BOX/pg.pw"
    initdb -D "$BOX/pg" -U ops --pwfile="$BOX/pg.pw" --auth=scram-sha-256 >/dev/null
  fi
  define_service postgres "exec postgres -D $BOX/pg -k $BOX/pg-run -c listen_addresses=127.0.0.1 -c port=5432 -c max_connections=300"
  for _ in $(seq 40); do pg_isready -q -h 127.0.0.1 -p 5432 && break; sleep 1; done
  pg_isready -q -h 127.0.0.1 -p 5432 || die "postgres did not become ready"
  PGPASSWORD=ops psql -h 127.0.0.1 -U ops -d postgres -tAc "select 1 from pg_database where datname='ops_runtime'" | grep -q 1 \
    || PGPASSWORD=ops createdb -h 127.0.0.1 -U ops ops_runtime
fi
define_service opa "exec opa run --server --watch --addr 0.0.0.0:8181 --log-level error $REPO/services/tools-service/policy"
define_service mailpit "export MP_SMTP_AUTH_ACCEPT_ANY=1 MP_SMTP_AUTH_ALLOW_INSECURE=1
exec mailpit"
define_service greenmail "exec java -Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled -jar $BIN/greenmail.jar"
# The fake bank runs from the repo's Python (the box's own lacks uvicorn) and writes the certificate tools-service trusts.
mkdir -p "$REPO/.run/fake-bank"
define_service fakebank "cd $REPO/services/tools-service/scripts
export FAKE_BANK_BIND=0.0.0.0 FAKE_BANK_PORT=8745 FAKE_BANK_KEY=dev-bank-key FAKE_BANK_WEBHOOK_SECRET=dev-webhook-secret
exec $REPO/.venv/bin/python -m fake_bank $REPO/.run/fake-bank"
# The routing Caddy (deploy/fly/Caddyfile) listens on 8082. The box's public address is open to anyone with the link, and
# Fly's own sign-in would replace the app's Authorization header on every call, so a second Caddy on 8081 (--http-port)
# is the gate: it admits only browsers holding the ops_box cookie, which /__box?key= sets. The key stays in $BOX/key.
define_service console-proxy "export OPS_PUBLIC_PORT=8082
exec caddy run --config $REPO/deploy/fly/Caddyfile --adapter caddyfile"
cat >"$BOX/Caddyfile" <<'GATE'
{
	admin off
	auto_https off
	servers {
		trusted_proxies static private_ranges
	}
}

:8081 {
	@enter {
		path /__box
		query key={env.BOX_KEY}
	}
	handle @enter {
		header Set-Cookie "ops_box={env.BOX_KEY}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax"
		redir * /login 302
	}
	@member header Cookie *ops_box={env.BOX_KEY}*
	handle @member {
		reverse_proxy 127.0.0.1:8082 {
			flush_interval -1
		}
	}
	handle {
		respond "Open this box from its link" 403
	}
}
GATE
# The key is made once per box and kept; `make box-url` prints the link that carries it.
if [ ! -s "$BOX/key" ]; then (umask 077; openssl rand -hex 24 >"$BOX/key"); fi
chmod 600 "$BOX/key"
SERVICE_ARGS="--http-port 8081" # The checksum line makes a changed gate file restart the service; define_service compares only the script.
define_service proxy "# $(cksum <"$BOX/Caddyfile")
export BOX_KEY=\$(cat $BOX/key)
exec caddy run --config $BOX/Caddyfile --adapter caddyfile"
for p in 8181 1025 3025 8745 8082 8081; do wait_port 127.0.0.1 "$p" 60 || wait_port "$BOX_IP" "$p" 5; done
done_step

# ---- the stack -------------------------------------------------------------------------------------------------
step "stack${BOX_RESET:+ (database reset)}"
export OPS_INFRA=external
# The console runs from a production build: the dev server's HMR websocket fails behind the box's proxy and the page
# reloads in a loop. The build runs on first start of a checkout (scripts/console-prod.sh); a reset forces a new one.
export OPS_CONSOLE_MODE=prod OPS_READY_TIMEOUT=900
cd "$REPO"
# make/env.mk includes .env on every make run, so a later `make restart`, `make up` or health check on the box uses the
# production console too. Only these two lines are managed; anything else in the file stays.
touch .env
sed -i '/^OPS_CONSOLE_MODE=/d;/^OPS_READY_TIMEOUT=/d' .env
printf 'OPS_CONSOLE_MODE=prod\nOPS_READY_TIMEOUT=900\n' >>.env
[ "${BOX_RESET:-}" = 1 ] && rm -f apps/console/.next/.ops-built
if [ "${BOX_RESET:-}" = 1 ] || [ "$SERVICES_CHANGED" = 1 ]; then
  make -s down KEEP_DB=1 >/dev/null 2>&1 || true
fi
if [ "${BOX_RESET:-}" = 1 ]; then
  make -s reset-db CONFIRM=yes >"$BOX/reset.log" 2>&1 || { tail -10 "$BOX/reset.log" >&2; die "reset-db failed"; }
fi
make -s up AUTH=platform DEMO_MODEL=fake >"$BOX/up.log" 2>&1 || { tail -25 "$BOX/up.log" >&2; die "make up failed (log $BOX/up.log)"; }
done_step

step "demo data"
# The first run right after a start can meet a token issued before the install's roles settled (401 permissions_changed);
# a second run finds what the first made and finishes.
make -s sample-team DEMO_MODEL=fake >"$BOX/sample-team.log" 2>&1 \
  || { sleep 3; make -s sample-team DEMO_MODEL=fake >"$BOX/sample-team.log" 2>&1; } \
  || { tail -10 "$BOX/sample-team.log" >&2; die "sample-team failed"; }
done_step

make -s health 2>&1 | tail -20
printf '[box] ready %s on %s\n' "$OPS_PUBLIC_ORIGIN" "$(git rev-parse --abbrev-ref HEAD)@$(git rev-parse --short HEAD)"
