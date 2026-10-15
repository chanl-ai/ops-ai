#!/usr/bin/env bash
# Local stack process manager: platform service, agents service, tools service and the console with chat on the
# agents service.
# Each runs in the background with its log in $OPS_LOG_DIR/<svc>.log and its pid in $OPS_RUN_DIR/<svc>.pid. Ports and
# directories come from make/env.mk (ISOLATED=1 shifts them); run through make, under your secrets manager.
# Usage: scripts/stack.sh up|down|restart|health|start <svc>|stop <svc>|logs <svc>|stop-stale|check-fresh|stop-for-reset
set -euo pipefail
# Job control puts each background service in its own process group, so `down` stops its children (uv, node) too.
set -m
cd "$(dirname "$0")/.."

SERVICES=(platform agents tools console)
# The Python services do not reload code; the console does (next dev), so only these can run code older than HEAD.
PY_SERVICES=(platform agents tools)
LOG_DIR=${OPS_LOG_DIR:-.logs}
RUN_DIR=${OPS_RUN_DIR:-.run}
AGENTS_PORT=${OPS_AGENTS_PORT:-8700}
TOOLS_PORT=${OPS_TOOLS_PORT:-8720}
PLATFORM_PORT=${OPS_PLATFORM_PORT:-8710}
CONSOLE_PORT=${OPS_CONSOLE_PORT:-3016}
OPA_PORT=${OPS_OPA_PORT:-8181}
PG_PORT=${OPS_PG_PORT:-5477}
STACK=${OPS_STACK:-shared}
AUTH=${OPS_STACK_AUTH:-dev}
PLATFORM_INTERNAL_PORT=${OPS_PLATFORM_INTERNAL_PORT:-8711}
mkdir -p "$LOG_DIR" "$RUN_DIR"

port_of() { case "$1" in platform) echo "$PLATFORM_PORT" ;; agents) echo "$AGENTS_PORT" ;; tools) echo "$TOOLS_PORT" ;; console) echo "$CONSOLE_PORT" ;; esac; }

url_of() {
  case "$1" in
    platform) echo "http://127.0.0.1:$PLATFORM_PORT/v1/health" ;;
    agents) echo "http://127.0.0.1:$AGENTS_PORT/health" ;;
    tools) echo "http://127.0.0.1:$TOOLS_PORT/health" ;;
    console) echo "http://127.0.0.1:$CONSOLE_PORT/" ;;
  esac
}

# AUTH=platform: the services verify platform-service tokens; the console signs in through platform-service.
auth_env() { [[ "$AUTH" == platform ]] && echo "env OPS_AUTH_MODE=platform OPS_PLATFORM_URL=http://127.0.0.1:$PLATFORM_PORT OPS_PLATFORM_INTERNAL_PORT=$PLATFORM_INTERNAL_PORT " || true; }
console_auth() { [[ "$AUTH" == platform ]] && echo "NEXT_PUBLIC_AUTH_PROVIDER=platform NEXT_PUBLIC_OPS_PLATFORM_API_URL=http://localhost:$PLATFORM_PORT " || true; }

cmd_of() {
  case "$1" in
    # Dev mode seeds team_ops (Priya Shah admin, James Richardson builder, Maya Okafor approver) on start.
    platform) echo "uv run --directory services/platform-service python -m ops_platform" ;;
    # Agents call tools through tools-service's gateway and are seeded with agents granted its operations (c-048).
    agents) echo "$(auth_env)env OPS_GATEWAY_URL=http://127.0.0.1:$TOOLS_PORT OPS_AGENTS_SEED_FILE=seed/chat_agents.json uv run --directory services/agents-service python -m ops_agents.api" ;;
    tools) echo "$(auth_env)uv run --directory services/tools-service python -m ops_tools" ;;
    # A second Next dev server in the same folder needs its own build directory: Next locks the one it uses.
    console)
      local dist=.next
      [[ "$STACK" == isolated ]] && dist=.next-isolated
      echo "env $(console_auth)NEXT_PUBLIC_OPS_CHAT_API_URL=http://localhost:$AGENTS_PORT NEXT_PUBLIC_OPS_CASES_API_URL=http://localhost:$AGENTS_PORT NEXT_PUBLIC_OPS_REGISTRY_API_URL=http://localhost:$AGENTS_PORT NEXT_PUBLIC_OPS_TOOLS_API_URL=http://localhost:$TOOLS_PORT OPS_CONSOLE_DIST_DIR=$dist pnpm --filter @ops-ai/console exec next dev -p $CONSOLE_PORT"
      ;;
  esac
}

known() { [[ " ${SERVICES[*]} " == *" ${1:-} "* ]] || { echo "unknown service '${1:-}'; one of: ${SERVICES[*]}" >&2; exit 2; }; }
pidfile() { echo "$RUN_DIR/$1.pid"; }
alive() { [[ -f "$(pidfile "$1")" ]] && kill -0 "$(cat "$(pidfile "$1")")" 2>/dev/null; }
# The auth mode a running service was started with. A file missing from before modes were recorded means dev.
authfile() { echo "$RUN_DIR/$1.auth"; }
started_auth() { cat "$(authfile "$1")" 2>/dev/null || echo dev; }
listener() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

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
  # A port held by a process this script did not start belongs to someone else; it is reported, never killed.
  if pid=$(listener "$port") && [[ -n "$pid" ]]; then echo "$port already served by pid $pid, skipping $svc"; return; fi
  nohup $(cmd_of "$svc") >"$LOG_DIR/$svc.log" 2>&1 &
  echo $! >"$(pidfile "$svc")"
  echo "$AUTH" >"$(authfile "$svc")"
  echo "$svc: started on :$port (pid $!, log ${LOG_DIR#"$PWD"/}/$svc.log)"
}

stop() {
  local svc=$1 pid
  if alive "$svc"; then
    pid=$(cat "$(pidfile "$svc")")
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    echo "$svc: stopped (pid $pid)"
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
code_dirs() { case "$1" in platform) echo services/platform-service packages ;; agents) echo services/agents-service packages ;; tools) echo services/tools-service packages ;; esac; }
# shellcheck disable=SC2046 # code_dirs prints space-separated paths on purpose
code_commit() { git log -1 --format="$2" -- $(code_dirs "$1"); }

# A service is stale when its process started before the last commit to its code: it runs older code, and that
# commit's migrations can change the tables under it (forced RLS on the run tables broke chat this way).
stale() {
  local pid age
  pid=$(serving_pid "$1") || return 1
  [[ -n "$pid" ]] || return 1
  age=$(age_of "$pid") || return 1
  (($(date +%s) - age < $(code_commit "$1" %ct)))
}

stop_stale() {
  for svc in "${PY_SERVICES[@]}"; do
    stale "$svc" || continue
    if alive "$svc"; then
      echo "$svc: started before $(code_commit "$svc" %h) changed its code; restarting"
      stop "$svc"
    else
      echo "$svc: :$(port_of "$svc") is served by pid $(serving_pid "$svc"), older than $(code_commit "$svc" %h) and not started by make up; stop it" >&2
    fi
  done
}

check_fresh() {
  local failed=0
  for svc in "${PY_SERVICES[@]}"; do
    if stale "$svc"; then
      echo "$svc (pid $(serving_pid "$svc"), :$(port_of "$svc")) runs code older than $(code_commit "$svc" %h)" >&2
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

health() {
  local failed=0 only=${1:-} code
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
  if [[ -z "$only" ]]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$OPA_PORT/health" || true)
    if [[ "$code" == 2* ]]; then row opa "$OPA_PORT" "http://127.0.0.1:$OPA_PORT/health" "ok ($code)" compose; else row opa "$OPA_PORT" "http://127.0.0.1:$OPA_PORT/health" DOWN compose; failed=1; fi
    if nc -z 127.0.0.1 "$PG_PORT" 2>/dev/null; then row postgres "$PG_PORT" "tcp://127.0.0.1:$PG_PORT" "ok (tcp)" compose; else row postgres "$PG_PORT" "tcp://127.0.0.1:$PG_PORT" DOWN compose; failed=1; fi
  fi
  return "$failed"
}

logs() {
  known "${1:-}"
  [[ -f "$LOG_DIR/$1.log" ]] || { echo "no log yet: ${LOG_DIR#"$PWD"/}/$1.log (start it with make up)" >&2; exit 1; }
  if [[ "${OPS_LOGS_FOLLOW:-1}" == 1 ]]; then tail -n 50 -f "$LOG_DIR/$1.log"; else tail -n "${OPS_LOGS_LINES:-50}" "$LOG_DIR/$1.log"; fi
}

case "${1:-}" in
  up) for svc in "${SERVICES[@]}"; do start "$svc"; done; wait_ready ;;
  down) for svc in "${SERVICES[@]}"; do stop "$svc"; done ;;
  restart)
    if [[ -n "${2:-}" ]]; then known "$2"; stop "$2"; start "$2"; else for svc in "${SERVICES[@]}"; do stop "$svc"; done; for svc in "${SERVICES[@]}"; do start "$svc"; done; fi
    wait_ready
    ;;
  start) known "${2:-}"; start "$2"; wait_ready ;;
  stop) known "${2:-}"; stop "$2" ;;
  health) [[ -n "${2:-}" ]] && known "$2"; health "${2:-}" ;;
  logs) logs "${2:-}" ;;
  stop-stale) stop_stale ;;
  check-fresh) check_fresh ;;
  stop-for-reset) stop_for_reset ;;
  *) echo "usage: scripts/stack.sh up|down|restart [svc]|health [svc]|start <svc>|stop <svc>|logs <svc>" >&2; exit 2 ;;
esac
