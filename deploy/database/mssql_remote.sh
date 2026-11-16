#!/usr/bin/env bash
# A shared SQL Server 2025 on Fly for the both-database tests, for Macs, where no SQL Server 2022 or later image runs
# and the local Azure SQL Edge (engine 15) refuses the golden schema. CI's store-mssql job stays the gate.
#
#   deploy/database/mssql_remote.sh up                        create the app on first use, else start its machine;
#                                                             waits until the server answers through the proxy
#   deploy/database/mssql_remote.sh proxy                     fly proxy to a local port in the background; prints it
#   deploy/database/mssql_remote.sh test <member> [pytest args]   e.g. test services/kb-service -q tests/test_x.py
#   deploy/database/mssql_remote.sh status                    the machine's state and the proxy's port
#   deploy/database/mssql_remote.sh sweep [hours]             drops databases older than hours (default 2)
#   deploy/database/mssql_remote.sh down                      stops the proxy and the machine (only the volume bills)
#
# Settings (environment, else $OPS_STAGING_CONFIG/staging.env, default ~/.config/ops-ai/staging.env):
#   OPS_MSSQL_REMOTE_APP            the Fly app (default <STG_APP_PREFIX>-test-mssql)
#   OPS_MSSQL_REMOTE_ORG            the Fly organisation, needed only to create the app (default STG_FLY_ORG)
#   OPS_MSSQL_REMOTE_PASSWORD_FILE  the SA password, mode 600 (default <config dir>/test-mssql-sa.txt); made on create
#   OPS_MSSQL_REMOTE_PORT           the local proxy port (default 14340)
#
# Several builders share the server: each test makes its own uniquely named database and drops it
# (ops_store.conformance.sql_server_database), so runs never meet; `sweep` removes what a killed run left behind.
# The machine has no service, so Fly cannot stop it when idle: `down` stops it.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
CONF=${OPS_STAGING_CONFIG:-$HOME/.config/ops-ai}
conf_value() { [ -f "$CONF/staging.env" ] && sed -n "s/^$1=//p" "$CONF/staging.env" | tail -1; }
PREFIX=${STG_APP_PREFIX:-$(conf_value STG_APP_PREFIX)}
APP=${OPS_MSSQL_REMOTE_APP:-${PREFIX:+$PREFIX-test-mssql}}
ORG=${OPS_MSSQL_REMOTE_ORG:-${STG_FLY_ORG:-$(conf_value STG_FLY_ORG)}}
PWFILE=${OPS_MSSQL_REMOTE_PASSWORD_FILE:-$CONF/test-mssql-sa.txt}
PORT=${OPS_MSSQL_REMOTE_PORT:-14340}
PIDFILE=$CONF/test-mssql-proxy.pid
LOG=$CONF/test-mssql-proxy.log
CLIENT=ops-mssql-client:2
[ -n "$APP" ] || { echo "mssql-remote: set OPS_MSSQL_REMOTE_APP, or STG_APP_PREFIX in $CONF/staging.env" >&2; exit 2; }

machine() { fly machine list -a "$APP" --json | jq -r '.[0].id // empty'; }
proxy_alive() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null && nc -z 127.0.0.1 "$PORT" 2>/dev/null; }

# sqlcmd in the test client image, as the client container reaches the proxy. The password goes in by name only.
sql() {
  "$HERE/mssql_local.sh" client
  SQLCMDPASSWORD=$(cat "$PWFILE") docker run --rm -i -e SQLCMDPASSWORD "$CLIENT" \
    /opt/mssql-tools18/bin/sqlcmd -C -b -h -1 -W -S "host.docker.internal,$PORT" -U sa "$@"
}

create() {
  [ -n "$ORG" ] || { echo "mssql-remote: set OPS_MSSQL_REMOTE_ORG, or STG_FLY_ORG in $CONF/staging.env, to create $APP" >&2; exit 2; }
  fly apps create "$APP" --org "$ORG" >/dev/null
  if [ ! -s "$PWFILE" ]; then
    # Letters and digits only, so the password cannot hide behind URL encoding in a traceback.
    (umask 077; python3 -c 'import secrets,string;p=[secrets.choice(s) for s in (string.ascii_uppercase,string.ascii_lowercase,string.digits) for _ in range(8)];secrets.SystemRandom().shuffle(p);print("".join(p))' >"$PWFILE")
  fi
  printf 'MSSQL_SA_PASSWORD=%s\n' "$(cat "$PWFILE")" | fly secrets import -a "$APP" --stage >/dev/null
  fly deploy -c "$ROOT/deploy/fly/mssql/remote.toml" -a "$APP" --ha=false --yes --wait-timeout 10m
}

start_proxy() {
  if proxy_alive; then echo "$PORT"; return; fi
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && { echo "mssql-remote: port $PORT is taken; set OPS_MSSQL_REMOTE_PORT" >&2; exit 2; }
  nohup fly proxy "$PORT:1433" -a "$APP" >"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 30); do nc -z 127.0.0.1 "$PORT" 2>/dev/null && { echo "$PORT"; return; }; sleep 1; done
  echo "mssql-remote: the proxy did not open port $PORT; see $LOG" >&2; exit 1
}

case "${1:-}" in
  up)
    if ! fly status -a "$APP" >/dev/null 2>&1; then create; fi
    [ -s "$PWFILE" ] || { echo "mssql-remote: $PWFILE is missing; it holds the app's MSSQL_SA_PASSWORD secret" >&2; exit 2; }
    id=$(machine)
    fly machine start "$id" -a "$APP" >/dev/null 2>&1 || true
    start_proxy >/dev/null
    for _ in $(seq 60); do
      if sql -Q "SET NOCOUNT ON; SELECT 1" >/dev/null 2>&1; then echo "$APP: answering on 127.0.0.1:$PORT"; exit 0; fi
      sleep 5
    done
    echo "$APP: no answer after 5 minutes (fly logs -a $APP)" >&2; exit 1
    ;;
  proxy) start_proxy ;;
  test)
    shift
    port=$(start_proxy)
    OPS_MSSQL_ADDR="host.docker.internal,$port" OPS_MSSQL_PASSWORD_FILE="$PWFILE" exec "$HERE/mssql_local.sh" test "$@"
    ;;
  status)
    fly machine list -a "$APP" --json | jq -r '.[] | "\(.id) \(.state) \(.config.guest.cpu_kind)-\(.config.guest.cpus)x \(.config.guest.memory_mb)MB \(.region)"'
    if proxy_alive; then echo "proxy: 127.0.0.1:$PORT (pid $(cat "$PIDFILE"))"; else echo "proxy: not running"; fi
    ;;
  sweep)
    hours=${2:-2}
    case "$hours" in '' | *[!0-9]*) echo "mssql-remote: sweep takes whole hours" >&2; exit 2 ;; esac
    start_proxy >/dev/null
    # The server holds nothing but test databases; one older than the cutoff belongs to a run that is over.
    sql -Q "SET NOCOUNT ON; DECLARE @n sysname, @s nvarchar(max), @c int = 0;
      DECLARE d CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM sys.databases
        WHERE database_id > 4 AND create_date < DATEADD(hour, -$hours, GETDATE());
      OPEN d; FETCH NEXT FROM d INTO @n;
      WHILE @@FETCH_STATUS = 0 BEGIN
        SET @s = N'ALTER DATABASE ' + QUOTENAME(@n) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' + QUOTENAME(@n);
        EXEC (@s); SET @c += 1; FETCH NEXT FROM d INTO @n;
      END;
      SELECT CONCAT('dropped ', @c, ' databases older than $hours hours; ', (SELECT COUNT(*) FROM sys.databases WHERE database_id > 4), ' left');"
    ;;
  down)
    if [ -f "$PIDFILE" ]; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; fi
    id=$(machine)
    [ -n "$id" ] && fly machine stop "$id" -a "$APP" >/dev/null && echo "$APP: machine $id stopped"
    ;;
  *) sed -n 2,21p "$0"; exit 2 ;;
esac
