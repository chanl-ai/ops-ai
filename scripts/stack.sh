#!/usr/bin/env bash
# Local stack process manager: platform service, agents service, tools service, kb service, files service and the
# console with chat on the agents service.
# Each runs in the background with its log in $OPS_LOG_DIR/<svc>.log and its pid in $OPS_RUN_DIR/<svc>.pid. Ports and
# directories come from make/env.mk (ISOLATED=1 shifts them); run through make, under your secrets manager.
# Usage: scripts/stack.sh up|down|restart|health|start <svc>|stop <svc>|logs <svc>|stop-stale|check-fresh|note-migrations|stop-for-reset
set -euo pipefail
# Job control puts each background service in its own process group, so `down` stops its children (uv, node) too.
set -m
cd "$(dirname "$0")/.."

STACK=${OPS_STACK:-shared}
# files before kb: kb-service stores uploads in files-service and its dev seed uploads on start.
SERVICES=(platform agents runner tools files documents kb console embed apidocs)
# The workflow runner's worker serves no port; v2 runs (POST /v1/runs) and every mailbox trigger wait until it runs.
WORKERS=(worker)
# What the demos need beside the services (c-212, c-223, the mailbox demo): models-service with the fake OpenAI behind
# it (the committed demo rules, so no turn reaches a real provider) and the fake bank the levy cases look customers up
# in. Ahead of the services: tools-service trusts the fake bank's certificate, which the bank writes on its first start.
FAKES=(fakeai models fakebank)
# The shared stack starts all of it, so `make up` after a reboot is enough for `make demo-mailbox` and `make seed-walk`.
# An isolated stack (use cases) brings its own fakes; it starts the worker only with OPS_STACK_WORKER=1.
if [[ "$STACK" == shared ]]; then
  UP_SERVICES=("${FAKES[@]}" "${SERVICES[@]}" worker)
elif [[ "${OPS_STACK_WORKER:-0}" == 1 ]]; then
  UP_SERVICES=("${SERVICES[@]}" worker)
else
  UP_SERVICES=("${SERVICES[@]}")
fi
# The Python services do not reload code; the console does (next dev), so only these can run code older than HEAD.
PY_SERVICES=(platform agents runner tools files documents kb models worker)
LOG_DIR=${OPS_LOG_DIR:-.logs}
RUN_DIR=${OPS_RUN_DIR:-.run}
AGENTS_PORT=${OPS_AGENTS_PORT:-8700}
TOOLS_PORT=${OPS_TOOLS_PORT:-8720}
KB_PORT=${OPS_KB_PORT:-8740}
FILES_PORT=${OPS_FILES_PORT:-8750}
DOCUMENTS_PORT=${OPS_DOCUMENTS_PORT:-8760}
RUNNER_PORT=${OPS_RUNNER_PORT:-8770}
PLATFORM_PORT=${OPS_PLATFORM_PORT:-8710}
CONSOLE_PORT=${OPS_CONSOLE_PORT:-3016}
EMBED_PORT=${OPS_EMBED_PORT:-3020}
# A long-lived next dev grew to 7.5 GB; the heap cap makes it restart on its own limit instead of starving the machine.
OPA_PORT=${OPS_OPA_PORT:-8181}
PG_PORT=${OPS_PG_PORT:-5477}
MODELS_PORT=${OPS_MODELS_PORT:-8730}
FAKE_OPENAI_PORT=${OPS_FAKE_OPENAI_PORT:-8746}
# Every service's API reference on one page (scripts/api_docs.py).
API_DOCS_PORT=${OPS_API_DOCS_PORT:-8799}
# Fixed in services/tools-service/scripts/fake_bank, which serves on this machine's private address, not loopback.
FAKE_BANK_PORT=8745
# A restart must start a service the way the stack is already running: the dev .env (model and provider settings) is
# loaded, and the sign-in mode defaults to the one recorded for the shared stack, not to dev.
if [ -f ".env" ]; then set -a; . ".env" >/dev/null 2>&1 || true; set +a; fi
if [ -f ".devcontainer/.env.local" ]; then set -a; . ".devcontainer/.env.local" >/dev/null 2>&1 || true; set +a; fi
# Side containers: a laptop .env names a CA file and resolve map that are not in this filesystem.
if [[ "${OPS_INFRA:-}" == external ]]; then
  [[ -n "${OPS_EGRESS_CA_FILE:-}" && -f "${OPS_EGRESS_CA_FILE}" ]] || unset OPS_EGRESS_CA_FILE
  unset OPS_EGRESS_RESOLVE
fi
AUTH=${OPS_STACK_AUTH:-$(cat ".run/stack.auth" 2>/dev/null || echo dev)}
# Dev-only exception until Govern > Models takes provider keys (c-177, owner 2026-10-18): models-service reads a
# connection's key from Secrets first and falls back to these settings in dev; outside dev it refuses them.
# `openai` is the credential name make demo-model binds openai-local to.
if [[ -n "${OPENAI_API_KEY:-}" && -z "${OPS_MODEL_PROVIDER_KEYS:-}" ]]; then
  OPS_MODEL_PROVIDER_KEYS=$(python3 -c 'import json,os; print(json.dumps({"openai": os.environ["OPENAI_API_KEY"]}))')
  export OPS_MODEL_PROVIDER_KEYS
fi
PLATFORM_INTERNAL_PORT=${OPS_PLATFORM_INTERNAL_PORT:-8711}
mkdir -p "$LOG_DIR" "$RUN_DIR"
RUN_ABS=$(cd "$RUN_DIR" && pwd)

port_of() { case "$1" in platform) echo "$PLATFORM_PORT" ;; agents) echo "$AGENTS_PORT" ;; tools) echo "$TOOLS_PORT" ;; kb) echo "$KB_PORT" ;; files) echo "$FILES_PORT" ;; documents) echo "$DOCUMENTS_PORT" ;; runner) echo "$RUNNER_PORT" ;; console) echo "$CONSOLE_PORT" ;; embed) echo "$EMBED_PORT" ;; models) echo "$MODELS_PORT" ;; fakeai) echo "$FAKE_OPENAI_PORT" ;; fakebank) echo "$FAKE_BANK_PORT" ;; apidocs) echo "$API_DOCS_PORT" ;; esac; }

url_of() {
  case "$1" in
    platform) echo "http://127.0.0.1:$PLATFORM_PORT/v1/health" ;;
    agents) echo "http://127.0.0.1:$AGENTS_PORT/health" ;;
    tools) echo "http://127.0.0.1:$TOOLS_PORT/health" ;;
    kb) echo "http://127.0.0.1:$KB_PORT/health" ;;
    files) echo "http://127.0.0.1:$FILES_PORT/health" ;;
    documents) echo "http://127.0.0.1:$DOCUMENTS_PORT/health" ;;
    runner) echo "http://127.0.0.1:$RUNNER_PORT/health" ;;
    console) echo "http://127.0.0.1:$CONSOLE_PORT/" ;;
    # The loader, which the embed app passes through to agents-service: up only when both are.
    embed) echo "http://127.0.0.1:$EMBED_PORT/embed/v1.js" ;;
    models) echo "http://127.0.0.1:$MODELS_PORT/health" ;;
    fakeai) echo "http://127.0.0.1:$FAKE_OPENAI_PORT/health" ;;
    apidocs) echo "http://127.0.0.1:$API_DOCS_PORT/health" ;;
    # The fake bank answers https on the private address under its own certificate; health checks that it runs.
    worker | fakebank) echo "" ;;
  esac
}

# AUTH=platform: the services verify platform-service tokens; the console signs in through platform-service.
auth_env() { [[ "$AUTH" == platform ]] && echo "env OPS_AUTH_MODE=platform OPS_PLATFORM_URL=http://127.0.0.1:$PLATFORM_PORT OPS_PLATFORM_INTERNAL_PORT=$PLATFORM_INTERNAL_PORT " || true; }
console_auth() { [[ "$AUTH" == platform ]] && echo "NEXT_PUBLIC_AUTH_PROVIDER=platform NEXT_PUBLIC_OPS_PLATFORM_API_URL=http://localhost:$PLATFORM_PORT " || true; }
# The Feedback button (c-504) shows only when this machine runs the ui-feedback collector at start.
ui_feedback() { curl -sf -m 1 http://127.0.0.1:4790/health >/dev/null && echo 1 || echo 0; }

# Dev mail (c-187, c-192, c-199, c-229). Team mailboxes are records connected on Channels > Email; the dev stack seeds
# two (services/agents-service/seed/mailboxes.json), levy@harborpine.example and intake@harborpine.test, both on
# GreenMail over IMAP and read by tools-service with the DEV_IMAP_PASSWORD secret. tools-service reaches GreenMail as any outside host: mail.harborpine.test is answered with this machine's
# private address (OPS_EGRESS_RESOLVE, dev only, merged into any mapping .env sets), and the host and that address are
# listed on the Egress page by whoever uses it (uc-192 does). Sent mail goes to Mailpit, and a mailbox's own reply
# sender at smtp.harborpine.test reaches Mailpit's SMTP the same way (uc-200).
GREENMAIL_IMAP=${OPS_GREENMAIL_IMAP_PORT:-3143}
MAILPIT_SMTP=${OPS_MAILPIT_SMTP_PORT:-1025}
SMTP_HOST=${OPS_SMTP_HOST:-127.0.0.1}
GREENMAIL_HOST=${OPS_GREENMAIL_HOST:-127.0.0.1}
MAILPIT_HOST=${OPS_MAILPIT_HOST:-127.0.0.1}
MAILBOX_ENV="OPS_MAILBOXES_SEED_FILE=seed/mailboxes.json"
# The services agents-service and its workflow worker both call, in one list: a worker missing one the API process has
# fails every workflow step that needs it (OPS_FILES_URL, then OPS_KB_URL, each went missing from the worker once).
# models-service is the default alias's only server; a clean clone has no .env naming it, so the dev runtime key it
# seeds is the default here.
# scripts/tests/test_stack_service_urls.py fails when the two commands' URLs differ.
# The embed app's origin is configuration (c-158): without it agents-service refuses every widget send from the console's
# Preview and the sample intranet page with 403 origin_not_allowed. JSON, no spaces, so the command's word split keeps it.
AGENTS_URLS="OPS_MODELS_URL=${OPS_MODELS_URL:-http://127.0.0.1:$MODELS_PORT} OPS_MODELS_KEY=${OPS_MODELS_KEY:-mk_dev_agents} OPS_GATEWAY_URL=http://127.0.0.1:$TOOLS_PORT OPS_KB_URL=http://127.0.0.1:$KB_PORT OPS_FILES_URL=http://127.0.0.1:$FILES_PORT OPS_DOCUMENTS_URL=http://127.0.0.1:$DOCUMENTS_PORT OPS_CONSOLE_URL=http://localhost:$CONSOLE_PORT OPS_EMBED_ORIGINS=[\"http://localhost:$EMBED_PORT\"]"
dev_egress_resolve() {
  IP=$(private_address) GM_HOST=$GREENMAIL_HOST MP_HOST=$MAILPIT_HOST python3 -c 'import json,os,socket
def host_ip(name, fallback):
    if name in ("127.0.0.1", "localhost", ""):
        return fallback
    try:
        return socket.getaddrinfo(name, None, socket.AF_INET)[0][4][0]
    except OSError:
        return fallback
ip=os.environ["IP"]
m=json.loads(os.environ.get("OPS_EGRESS_RESOLVE") or "{}"); m["mail.harborpine.test"]=host_ip(os.environ.get("GM_HOST",""), ip)+":"+os.environ["GM"]; m["smtp.harborpine.test"]=host_ip(os.environ.get("MP_HOST",""), ip)+":"+os.environ["MP"]
m["api.bank.test"]=ip+":"+os.environ["FB"]
print(json.dumps(m,separators=(",",":")))' 2>/dev/null
}
MAIL_OUT_ENV="OPS_MAIL_PROVIDER=smtp OPS_MAIL_FROM=ops@harborpine.example OPS_SMTP_HOST=$SMTP_HOST OPS_SMTP_PORT=$MAILPIT_SMTP OPS_SMTP_STARTTLS=false"


cmd_of() {
  case "$1" in
    # Dev mode seeds team_ops (Priya Shah admin, James Richardson builder, Maya Okafor approver) on start. Sign-in
    # (c-188): identity providers send people back to platform-service's public URL and on to the console; reset links
    # go out through Mailpit like every other mail the stack sends (read them at http://localhost:$OPS_MAILPIT_HTTP_PORT).
    platform) echo "env OPS_PLATFORM_PUBLIC_URL=http://localhost:$PLATFORM_PORT OPS_CONSOLE_URL=http://localhost:$CONSOLE_PORT $MAIL_OUT_ENV uv run --directory services/platform-service python -m ops_platform" ;;
    # Agents call tools through tools-service's gateway and are seeded with agents granted its operations (c-048).
    # services/agents-service/scripts/send_levy_email.py emails the levy notice to levy@ on GreenMail (c-229).
    agents) echo "$(auth_env)env $AGENTS_URLS $MAILBOX_ENV uv run --directory services/agents-service python -m ops_agents.api" ;;
    # The fake bank's certificate doubles as the CA tools-service trusts for api.bank.test.
    # Its own model key judges writes against a team's sending policy when the team has check before sending on (c-300).
    tools) echo "$(auth_env)env $MAIL_OUT_ENV OPS_MODELS_URL=http://127.0.0.1:$MODELS_PORT OPS_MODELS_KEY=mk_dev_tools_check OPS_EGRESS_CA_FILE=${OPS_EGRESS_CA_FILE:-$RUN_ABS/fake-bank/bank.crt} OPS_EGRESS_RESOLVE=$(GM=$GREENMAIL_IMAP MP=$MAILPIT_SMTP FB=$FAKE_BANK_PORT dev_egress_resolve) OPS_RUNNER_URL=http://127.0.0.1:$RUNNER_PORT uv run --directory services/tools-service python -m ops_tools" ;;
    # Code tools' functions (c-531): Python on WASM, calling back to tools-service. start fetches its Python build first.
    runner) echo "$(auth_env)env OPS_RUNNER_PORT=$RUNNER_PORT OPS_TOOLS_URL=http://127.0.0.1:$TOOLS_PORT uv run --directory services/runner-service python -m ops_runner" ;;
    # The worker also reads the workflows' mailboxes (Email received) and stores their attachments in files-service.
    worker) echo "$(auth_env)env $AGENTS_URLS $MAILBOX_ENV OPS_EMAIL_POLL_SECONDS=3 uv run --directory services/agents-service python -m ops_agents.api.worker" ;;
    # Seeds the openai-local connection at the fake on start; agents reach it with the dev runtime key it seeds.
    models) echo "env OPS_MODELS_PORT=$MODELS_PORT OPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:$FAKE_OPENAI_PORT/v1 uv run --directory services/models-service python -m ops_models" ;;
    fakeai) echo "env FAKE_OPENAI_PORT=$FAKE_OPENAI_PORT uv run --directory services/models-service/scripts --project .. python -m fake_openai $PWD/services/models-service/seed/demo-fake-openai" ;;
    fakebank) echo "uv run --directory services/tools-service/scripts --project .. python -m fake_bank $RUN_ABS/fake-bank" ;;
    apidocs) echo "env OPS_API_DOCS_PORT=$API_DOCS_PORT OPS_PLATFORM_PORT=$PLATFORM_PORT OPS_AGENTS_PORT=$AGENTS_PORT OPS_TOOLS_PORT=$TOOLS_PORT OPS_MODELS_PORT=$MODELS_PORT OPS_KB_PORT=$KB_PORT OPS_FILES_PORT=$FILES_PORT OPS_DOCUMENTS_PORT=$DOCUMENTS_PORT python3 scripts/api_docs.py" ;;
    # Uploads go to files-service (c-094); kb-service keeps no file store of its own on the stack.
    kb) echo "$(auth_env)env OPS_KB_PORT=$KB_PORT OPS_FILES_URL=http://127.0.0.1:$FILES_PORT uv run --directory services/kb-service python -m ops_kb" ;;
    # Local backend under .data/files, bytes through its proxy routes; scanning off marks files clean (dev only).
    # files-service delivers its service events (file.deleted, file.read_requested) to agents-service (c-250).
    files) echo "$(auth_env)env OPS_FILES_PORT=$FILES_PORT OPS_FILES_SCANNING=off OPS_AGENTS_URL=http://127.0.0.1:$AGENTS_PORT uv run --directory services/files-service python -m ops_files" ;;
    # documents-service extracts on its own models-service key (c-235, c-256), whatever key the root .env hands agents.
    documents) echo "$(auth_env)env OPS_DOCUMENTS_PORT=$DOCUMENTS_PORT OPS_FILES_URL=http://127.0.0.1:$FILES_PORT OPS_AGENTS_URL=http://127.0.0.1:$AGENTS_PORT OPS_MODELS_URL=http://127.0.0.1:$MODELS_PORT OPS_MODELS_KEY=mk_dev_extract uv run --directory services/documents-service python -m ops_documents" ;;
    # A second Next dev server in the same folder needs its own build directory: Next locks the one it uses.
    console)
      local dist=.next
      [[ "$STACK" == isolated ]] && dist=.next-isolated
      echo "env $(console_auth)NEXT_PUBLIC_UI_FEEDBACK=$(ui_feedback) NEXT_PUBLIC_OPS_CHAT_API_URL=http://localhost:$AGENTS_PORT NEXT_PUBLIC_OPS_CASES_API_URL=http://localhost:$AGENTS_PORT NEXT_PUBLIC_OPS_REGISTRY_API_URL=http://localhost:$AGENTS_PORT NEXT_PUBLIC_OPS_TOOLS_API_URL=http://localhost:$TOOLS_PORT NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL=http://localhost:$KB_PORT NEXT_PUBLIC_OPS_FILES_API_URL=http://localhost:$FILES_PORT NEXT_PUBLIC_OPS_DOCUMENTS_API_URL=http://localhost:$DOCUMENTS_PORT NEXT_PUBLIC_OPS_EMBED_URL=http://localhost:$EMBED_PORT OPS_CONSOLE_DIST_DIR=$dist NODE_OPTIONS=--max-old-space-size=${OPS_CONSOLE_HEAP_MB:-3072} pnpm --filter @ops-ai/console exec next dev -p $CONSOLE_PORT"
      ;;
    # The console's preview frame is the only page it allows to frame it besides a deployment's own sites.
    embed)
      local dist=.next
      [[ "$STACK" == isolated ]] && dist=.next-isolated
      echo "env OPS_EMBED_AGENTS_URL=http://127.0.0.1:$AGENTS_PORT OPS_CONSOLE_URL=http://localhost:$CONSOLE_PORT OPS_EMBED_DIST_DIR=$dist pnpm --filter @ops-ai/embed exec next dev -p $EMBED_PORT"
      ;;
  esac
}

known() { [[ " ${SERVICES[*]} ${WORKERS[*]} ${FAKES[*]} " == *" ${1:-} "* ]] || { echo "unknown service '${1:-}'; one of: ${SERVICES[*]} ${WORKERS[*]} ${FAKES[*]}" >&2; exit 2; }; }
pidfile() { echo "$RUN_DIR/$1.pid"; }
# Running, and the process this script started: a pid file outlives its process when that dies without `stop` (a
# crash, a killed session), and the system reuses the pid. A process that started after the file was written is
# someone else's, so it is never taken for the service and never signalled (stop kills the pid's whole group).
alive() {
  local file pid age
  file=$(pidfile "$1")
  [[ -f "$file" ]] || return 1
  pid=$(cat "$file")
  kill -0 "$pid" 2>/dev/null || return 1
  age=$(age_of "$pid") || return 1
  (($(date +%s) - age <= $(mtime_of "$file") + 5))
}
mtime_of() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }
# The auth mode a running service was started with. A file missing from before modes were recorded means dev.
authfile() { echo "$RUN_DIR/$1.auth"; }
started_auth() { cat "$(authfile "$1")" 2>/dev/null || echo dev; }
listener() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

# Env of a pid: Linux /proc, else ps eww (macOS). Used to tell this stack's leftovers from an isolated stack's.
pid_env() {
  local pid=$1
  if [[ -r "/proc/$pid/environ" ]]; then
    tr '\0' '\n' <"/proc/$pid/environ"
  else
    ps eww -p "$pid" 2>/dev/null
  fi
}

# Pids whose command matches $1 and whose env names this stack's files-service, so an isolated worker is left alone.
stack_cmd_pids() {
  local needle=$1 pid
  for pid in $(pgrep -f "$needle" || true); do
    pid_env "$pid" | grep -Fq "OPS_FILES_URL=http://127.0.0.1:$FILES_PORT" && echo "$pid"
  done
  return 0
}

stop_pids() {
  local pid
  for pid in "$@"; do
    [[ -n "$pid" ]] || continue
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
  done
}

# The python -m module a service runs, so a leftover on its port can be told from someone else's process.
# Matched as `-m <module>`: macOS Framework Python is `Python`, uv's is `python`.
module_of() {
  case "$1" in
    platform) echo "-m ops_platform" ;;
    agents) echo "-m ops_agents.api" ;;
    worker) echo "-m ops_agents.api.worker" ;;
    tools) echo "-m ops_tools" ;;
    kb) echo "-m ops_kb" ;;
    files) echo "-m ops_files" ;;
    documents) echo "-m ops_documents" ;;
    models) echo "-m ops_models" ;;
    runner) echo "-m ops_runner" ;;
    fakebank) echo "-m fake_bank" ;;
  esac
}

# Pid listening on this service's port that is this stack's leftover (same module), or empty.
ours_listener() {
  local svc=$1 pid cmd mod
  pid=$(listener "$(port_of "$svc")") || return 1
  [[ -n "$pid" ]] || return 1
  mod=$(module_of "$svc")
  [[ -n "$mod" ]] || return 1
  cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
  [[ "$cmd" == *"$mod"* ]] || return 1
  # The worker's module starts with the API's; a leftover worker does not listen on the API port.
  if [[ "$svc" == agents && "$cmd" == *"ops_agents.api.worker"* ]]; then
    return 1
  fi
  echo "$pid"
}

# The service folder whose migrations a service needs before it starts; the worker runs agents-service's code.
migrations_of() { case "$1" in platform | agents | tools | kb | files | documents | models) echo "services/$1-service" ;; worker) echo services/agents-service ;; esac; }

# New code started on an older schema fails at its first query (a 500 on sign-in once 0024 was committed but never
# applied), so each start applies the service's own migrations first and starts nothing when they fail.
migrate() {
  local dir out
  dir=$(migrations_of "$1")
  [[ -n "$dir" && -f "$dir/alembic.ini" ]] || return 0
  if ! out=$(uv run --directory "$dir" alembic upgrade head 2>&1); then
    echo "$1: migrations failed, not starting it:" >&2
    echo "$out" | tail -5 >&2
    return 1
  fi
}

start() {
  local svc=$1 port pid
  port=$(port_of "$svc")
  # A service started under the other auth mode would keep serving it while the target names this one, so a walk
  # that means to exercise platform tokens could run against dev headers.
  if alive "$svc" && [[ "$(started_auth "$svc")" != "$AUTH" ]]; then
    echo "$svc: running with auth $(started_auth "$svc"), asked for $AUTH; restarting"
    stop "$svc"
  fi
  if alive "$svc"; then echo "$svc: already running (pid $(cat "$(pidfile "$svc")"), auth $AUTH)"; return; fi
  # A worker whose pidfile was lost is still this stack's: record it instead of starting a second one (three leftovers
  # were still claiming work and the mail listener's lease after make up, c-532).
  if [[ "$svc" == worker ]]; then
    local leftover
    leftover=$(stack_cmd_pids "ops_agents.api.worker" | head -1)
    if [[ -n "$leftover" ]]; then
      echo "$leftover" >"$(pidfile "$svc")"
      echo "$AUTH" >"$(authfile "$svc")"
      echo "$svc: already running (pid $leftover, auth $AUTH)"
      return
    fi
  fi
  # A port held by a process this script did not start belongs to someone else; it is reported, never killed.
  if [[ -n "$port" ]] && pid=$(listener "$port") && [[ -n "$pid" ]]; then echo "$port already served by pid $pid, skipping $svc"; return; fi
  migrate "$svc" || return 1
  # The runner's pinned Python build (c-531): fetched into .data/runner once, checked by SHA-256 on every start. The
  # command line is word-split, not parsed by a shell, so this runs here rather than chained in cmd_of.
  if [[ "$svc" == runner ]] && ! uv run --directory services/runner-service python -m ops_runner.fetch >/dev/null; then
    echo "runner: its Python build could not be fetched or checked, not starting it" >&2
    return 1
  fi
  nohup $(cmd_of "$svc") >"$LOG_DIR/$svc.log" 2>&1 &
  echo $! >"$(pidfile "$svc")"
  echo "$AUTH" >"$(authfile "$svc")"
  # The address tools-service dials for the dev mail and bank hosts is fixed when it starts (OPS_EGRESS_RESOLVE);
  # health compares it with the address now, since a network change leaves it dialling one that no longer answers.
  [[ "$svc" == tools ]] && private_address >"$RUN_DIR/tools.pinned"
  echo "$svc: started${port:+ on :$port} (pid $!, log ${LOG_DIR#"$PWD"/}/$svc.log)"
}

stop() {
  local svc=$1 pid
  if alive "$svc"; then
    pid=$(cat "$(pidfile "$svc")")
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    echo "$svc: stopped (pid $pid)"
  fi
  # Leftovers from a start that did not kill the last process: same command, this stack's env or fake-bank dir.
  if [[ "$svc" == worker ]]; then
    stop_pids $(stack_cmd_pids "ops_agents.api.worker")
  elif [[ "$svc" == fakebank ]]; then
    stop_pids $(pgrep -f "fake_bank $RUN_ABS/fake-bank" || true)
  fi
  rm -f "$(pidfile "$svc")" "$(authfile "$svc")"
}

# The pid serving a service: the one this script started, else whoever listens on its port.
serving_pid() {
  if alive "$1"; then cat "$(pidfile "$1")"; else listener "$(port_of "$1")"; fi
}

# Seconds since a process started, from ps's etime ([[dd-]hh:]mm:ss), which macOS and Linux both print.
age_of() {
  local et days=0 h=0 m s
  et=$(ps -o etime= -p "$1" 2>/dev/null | tr -d ' ') || return 1
  [[ -n "$et" ]] || return 1
  if [[ "$et" == *-* ]]; then days=${et%%-*}; et=${et#*-}; fi
  IFS=: read -r -a parts <<<"$et"
  if ((${#parts[@]} == 3)); then h=${parts[0]}; m=${parts[1]}; s=${parts[2]}; else m=${parts[0]}; s=${parts[1]}; fi
  echo $((10#$days * 86400 + 10#$h * 3600 + 10#$m * 60 + 10#$s))
}

# The last commit that changed what a Python service runs: its own directory (code and migrations) or packages/.
code_dirs() { case "$1" in platform) echo services/platform-service packages ;; agents | worker) echo services/agents-service packages ;; models) echo services/models-service packages ;; tools) echo services/tools-service packages ;; kb) echo services/kb-service packages ;; files) echo services/files-service packages ;; documents) echo services/documents-service packages ;; runner) echo services/runner-service packages ;; esac; }
# shellcheck disable=SC2046 # code_dirs prints space-separated paths on purpose
code_commit() { git log -1 --format="$2" -- $(code_dirs "$1"); }

# A service is stale when its process started before the last commit to its code, or before the last migration
# landed on the database: it runs older code, or code that met the tables before they changed (forced RLS on the run
# tables broke chat this way, and a worker up since before the team policies failed a run's first event, fb-16aa519c).
stale() {
  local pid age started
  pid=$(serving_pid "$1") || return 1
  [[ -n "$pid" ]] || return 1
  age=$(age_of "$pid") || return 1
  started=$(($(date +%s) - age))
  ((started < $(code_commit "$1" %ct))) && return 0
  [[ -f "$RUN_DIR/migrated-at" ]] && ((started < $(mtime_of "$RUN_DIR/migrated-at")))
}

# Why a stale service is stale, for the messages below.
stale_why() {
  local pid age
  pid=$(serving_pid "$1") && age=$(age_of "$pid") || return 0
  if (($(date +%s) - age < $(code_commit "$1" %ct))); then
    echo "older than $(code_commit "$1" %h), which changed its code"
  else
    echo "older than the last migration (make migrate, $(date -r "$(mtime_of "$RUN_DIR/migrated-at")" +%H:%M 2>/dev/null || date -d "@$(mtime_of "$RUN_DIR/migrated-at")" +%H:%M))"
  fi
}

# Run after every migrate: each chain's recorded revision, kept in $RUN_DIR/db-heads. When any differs from the last
# record, migrations landed, and $RUN_DIR/migrated-at marks when; every process started before it is stale.
note_migrations() {
  local now was file="$RUN_DIR/db-heads"
  now=$(uv run --quiet python scripts/schema_sync.py "${OPS_DATABASE_URL:?}" --recorded 2>/dev/null) || {
    echo "note-migrations: could not read the chains' revisions; staleness by migration is not updated" >&2
    return 0
  }
  was=$(cat "$file" 2>/dev/null || true)
  if [[ -n "$was" && "$was" != "$now" ]]; then
    touch "$RUN_DIR/migrated-at"
    echo "migrations landed; every service started before now is stale and make up restarts it"
  fi
  printf '%s\n' "$now" >"$file"
}

# The dev mail and bank fakes are reached at this machine's private address, which changes with the network (a
# hotspot, another office). tools-service maps their names to the address it started with and the fake bank listens
# on it, so after a move both are stopped here and `up` starts them on the new one. The address in use is recorded.
private_address() {
  python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(("10.255.255.255",1)); print(s.getsockname()[0])' 2>/dev/null
}

stop_moved() {
  local now was pinned
  now=$(private_address) || return 0
  was=$(cat "$RUN_DIR/dev-address" 2>/dev/null || true)
  pinned=$(cat "$RUN_DIR/tools.pinned" 2>/dev/null || true)
  # The recorded address can match while fakebank still listens on an earlier one (the route flipped after make up
  # wrote the file; health then reports STALE). Restart whenever this address does not answer on the bank port.
  if [[ -n "$was" && "$was" != "$now" ]] || [[ -n "$pinned" && "$pinned" != "$now" ]] \
    || { ! nc -z -w 3 "$now" "$FAKE_BANK_PORT" 2>/dev/null && { alive fakebank || listener "$FAKE_BANK_PORT" >/dev/null; }; }; then
    echo "this machine's private address is $now (was ${was:-unknown}); restarting the dev fakes that bind it"
    stop fakebank
    stop tools
  fi
  echo "$now" >"$RUN_DIR/dev-address"
}

stop_stale() {
  local extras pid svc
  [[ "$STACK" == shared ]] && stop_moved
  # uv + its python child are two pids; more than that is a leftover worker still claiming work.
  if [[ "$STACK" == shared ]]; then
    extras=$(stack_cmd_pids "ops_agents.api.worker" | wc -l | tr -d ' ')
    if (( extras > 2 )); then
      echo "worker: $extras processes still running; stopping them so one worker remains"
      stop worker
    fi
  fi
  for svc in "${PY_SERVICES[@]}"; do
    stale "$svc" || continue
    if alive "$svc"; then
      echo "$svc: $(stale_why "$svc"); restarting"
      stop "$svc"
    elif pid=$(ours_listener "$svc"); then
      # Pidfile lost after a crash or a start that skipped; the process is still this stack's module on this port.
      echo "$svc: leftover pid $pid $(stale_why "$svc"); stopping it"
      stop_pids "$pid"
    else
      echo "$svc: :$(port_of "$svc") is served by pid $(serving_pid "$svc"), $(stale_why "$svc"), and not started by make up; stop it" >&2
    fi
  done
}

check_fresh() {
  local failed=0
  for svc in "${PY_SERVICES[@]}"; do
    if stale "$svc"; then
      echo "$svc (pid $(serving_pid "$svc"), :$(port_of "$svc")) is $(stale_why "$svc")" >&2
      failed=1
    fi
  done
  return "$failed"
}

# Before the database is rebuilt: every Python service of this stack stops, so none keeps a connection or runs
# against a schema it did not create. A listener this script did not start is reported and the rebuild refused.
stop_for_reset() {
  local failed=0 pid
  for svc in "${PY_SERVICES[@]}"; do stop "$svc"; done
  for svc in "${PY_SERVICES[@]}"; do
    if pid=$(listener "$(port_of "$svc")") && [[ -n "$pid" ]]; then
      echo "$svc: :$(port_of "$svc") is served by pid $pid, not started by make up; stop it before the schema is rebuilt" >&2
      failed=1
    fi
  done
  return "$failed"
}

# Waits until every service this script started answers, so `make up` ends on a health table that means something.
wait_ready() {
  local deadline=$((SECONDS + ${OPS_READY_TIMEOUT:-90}))
  for svc in "${SERVICES[@]}"; do
    alive "$svc" || continue
    [[ -n "$(url_of "$svc")" ]] || continue
    until curl -s -o /dev/null --max-time 3 "$(url_of "$svc")"; do
      if ! alive "$svc"; then echo "$svc: exited during start; see ${LOG_DIR#"$PWD"/}/$svc.log" >&2; break; fi
      if ((SECONDS > deadline)); then echo "$svc: not answering after ${OPS_READY_TIMEOUT:-90}s" >&2; break; fi
      sleep 1
    done
  done
}

row() {
  local name=$1 port=$2 url=$3 state=$4 owner=$5
  printf '  %-8s %-6s %-34s %-12s %s\n' "$name" "$port" "$url" "$state" "$owner"
}

owner_of() {
  local svc=$1 port=$2 pid
  if alive "$svc"; then echo "make up (pid $(cat "$(pidfile "$svc")"), auth $(started_auth "$svc"))"; return; fi
  pid=$(listener "$port") || true
  if [[ -n "$pid" ]]; then echo "other process (pid $pid)"; else echo "-"; fi
}

# The Docker VM's disk, seen from a container of an image the stack already has: when it fills, PostgreSQL goes into
# recovery and every service with it (2026-10-19). A warning only; OPS_DOCKER_DISK_WARN sets the percentage (80).
docker_disk() {
  command -v docker >/dev/null 2>&1 || return 0
  local used image=${OPS_DOCKER_DISK_IMAGE:-postgres:17-alpine}
  used=$(docker run --rm --entrypoint df "$image" -P / 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $5}') || true
  [[ -n "$used" ]] || return 0
  if (( used >= ${OPS_DOCKER_DISK_WARN:-80} )); then
    echo "  WARNING: the Docker disk is ${used}% full (warns from ${OPS_DOCKER_DISK_WARN:-80}%). make db-sweep drops finished runs' databases; docker system df shows the rest" >&2
  else
    echo "  docker disk: ${used}% used"
  fi
}

# The background processes each service reports at /health/background (c-516): one row per process, its state and how
# long since its last pass. Late or stopped fails the command, so a stuck worker or relay shows here as on Govern >
# Background; not reported (an event-run process that has had nothing to do yet) does not.
background_rows() {
  local svc body bad=0
  printf '  %-8s %-18s %-14s %s\n' PROCESS KEY STATE "LAST RUN"
  for svc in agents files documents tools; do
    [[ " ${SERVICES[*]} " == *" $svc "* ]] || continue
    body=$(curl -s --max-time 5 "http://127.0.0.1:$(port_of "$svc")/health/background" || true)
    python3 - "$svc" "$body" <<'PY' || bad=1
import json, sys, time
svc, body = sys.argv[1], sys.argv[2]
try:
    processes = json.loads(body)["processes"]
except (ValueError, KeyError, TypeError):
    print(f"  {svc:<8} {'-':<18} {'DOWN':<14} no /health/background answer")
    sys.exit(1)
failed = False
for p in processes:
    ago = f"{int(time.time() - p['lastRunAt'])} s ago" if p.get("lastRunAt") else "never"
    state = p["state"].replace("_", " ")
    print(f"  {svc:<8} {p['key']:<18} {state:<14} {ago}" + (f" ({p['lastError']})" if p.get("lastError") else ""))
    failed = failed or p["state"] in ("late", "stopped")
sys.exit(1 if failed else 0)
PY
  done
  return $bad
}

health() {
  local failed=0 only=${1:-} code state pid
  echo "  stack: $STACK"
  printf '  %-8s %-6s %-34s %-12s %s\n' SERVICE PORT URL STATE OWNER
  for svc in "${SERVICES[@]}"; do
    [[ -n "$only" && "$only" != "$svc" ]] && continue
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$(url_of "$svc")" || true)
    if [[ "$code" == 2* ]]; then
      row "$svc" "$(port_of "$svc")" "$(url_of "$svc")" "ok ($code)" "$(owner_of "$svc" "$(port_of "$svc")")"
    else
      row "$svc" "$(port_of "$svc")" "$(url_of "$svc")" "DOWN" "$(owner_of "$svc" "$(port_of "$svc")")"
      failed=1
    fi
  done
  if alive worker; then
    row worker - - "running" "$(owner_of worker "")"
    if [[ "$STACK" == shared && -z "$only" ]]; then
      local extras
      extras=$(stack_cmd_pids "ops_agents.api.worker" | wc -l | tr -d ' ')
      if (( extras > 2 )); then
        row worker - - STALE "$((extras / 2)) processes still claiming work; make restart SVC=worker"
        failed=1
      fi
    fi
  elif [[ "$STACK" == shared && -z "$only" ]]; then row worker - - DOWN -; failed=1; fi
  [[ -z "$only" ]] && { background_rows || failed=1; }
  if [[ "$STACK" == shared && -z "$only" ]]; then
    for svc in "${FAKES[@]}"; do
      if [[ -n "$(url_of "$svc")" ]]; then
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$(url_of "$svc")" || true)
        if [[ "$code" == 2* ]]; then state="ok ($code)"; else state=DOWN; failed=1; fi
        row "$svc" "$(port_of "$svc")" "$(url_of "$svc")" "$state" "$(owner_of "$svc" "$(port_of "$svc")")"
      elif nc -z -w 3 "$(private_address)" "$(port_of "$svc")" 2>/dev/null; then
        row "$svc" "$(port_of "$svc")" "https (private address)" "ok (tcp)" "$(owner_of "$svc" "$(port_of "$svc")")"
      elif pid=$(listener "$(port_of "$svc")") && [[ -n "$pid" ]]; then
        # Listening, but not at this machine's address now: started before the network changed.
        row "$svc" "$(port_of "$svc")" "https (private address)" "STALE" "pid $pid listens on an old address"
        failed=1
      else
        row "$svc" "$(port_of "$svc")" "https (private address)" DOWN -; failed=1
      fi
    done
  fi
  if [[ "$STACK" == shared && ( -z "$only" || "$only" == tools ) ]] && alive tools && [[ -f "$RUN_DIR/tools.pinned" ]]; then
    local pinned now
    pinned=$(cat "$RUN_DIR/tools.pinned") now=$(private_address)
    if [[ "$pinned" == "$now" ]]; then
      row mailpin - "dev mail and bank at $now" ok -
    else
      row mailpin - "dev mail and bank at $pinned" STALE "this machine is now $now: make restart SVC=tools"
      failed=1
    fi
  fi
  if [[ -z "$only" ]]; then
    if [[ "${OPS_INFRA:-}" == external ]]; then
      opa_health="${OPS_OPA_URL:-http://opa:8181}/health"
      opa_port=8181
      pg_host=postgres
      pg_port=5432
    else
      opa_health="http://127.0.0.1:$OPA_PORT/health"
      opa_port=$OPA_PORT
      pg_host=127.0.0.1
      pg_port=$PG_PORT
    fi
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$opa_health" || true)
    if [[ "$code" == 2* ]]; then row opa "$opa_port" "$opa_health" "ok ($code)" compose; else row opa "$opa_port" "$opa_health" DOWN compose; failed=1; fi
    if nc -z "$pg_host" "$pg_port" 2>/dev/null; then row postgres "$pg_port" "tcp://$pg_host:$pg_port" "ok (tcp)" compose; else row postgres "$pg_port" "tcp://$pg_host:$pg_port" DOWN compose; failed=1; fi
  fi
  [[ -z "$only" ]] && docker_disk
  return "$failed"
}

logs() {
  known "${1:-}"
  [[ -f "$LOG_DIR/$1.log" ]] || { echo "no log yet: ${LOG_DIR#"$PWD"/}/$1.log (start it with make up)" >&2; exit 1; }
  if [[ "${OPS_LOGS_FOLLOW:-1}" == 1 ]]; then tail -n 50 -f "$LOG_DIR/$1.log"; else tail -n "${OPS_LOGS_LINES:-50}" "$LOG_DIR/$1.log"; fi
}

case "${1:-}" in
  up)
    for svc in "${UP_SERVICES[@]}"; do
      start "$svc"
      # tools-service loads the fake bank's certificate when it starts, and the bank writes it on its first start.
      if [[ "$svc" == fakebank ]]; then
        for _ in $(seq 1 60); do [[ -s "$RUN_ABS/fake-bank/bank.crt" ]] && listener "$FAKE_BANK_PORT" >/dev/null && break; sleep 0.5; done
      fi
    done
    wait_ready
    ;;
  down) for svc in "${SERVICES[@]}" "${WORKERS[@]}" "${FAKES[@]}"; do stop "$svc"; done ;;
  restart)
    if [[ -n "${2:-}" ]]; then known "$2"; stop "$2"; start "$2"; else for svc in "${SERVICES[@]}"; do stop "$svc"; done; for svc in "${SERVICES[@]}"; do start "$svc"; done; fi
    wait_ready
    ;;
  start) known "${2:-}"; start "$2"; wait_ready ;;
  stop) known "${2:-}"; stop "$2" ;;
  health) [[ -n "${2:-}" ]] && known "$2"; health "${2:-}" ;;
  logs) logs "${2:-}" ;;
  # The command a service starts with, for checks such as scripts/tests/test_stack_service_urls.py.
  cmd) known "${2:-}"; cmd_of "$2" ;;
  stop-stale) stop_stale ;;
  note-migrations) note_migrations ;;
  check-fresh) check_fresh ;;
  stop-for-reset) stop_for_reset ;;
  *) echo "usage: scripts/stack.sh up|down|restart [svc]|health [svc]|start <svc>|stop <svc>|logs <svc>" >&2; exit 2 ;;
esac
