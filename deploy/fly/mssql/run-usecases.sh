#!/usr/bin/env bash
# The SQL Server use cases (uc-565, uc-566) on the SQL Server test machine, run from a runner machine beside it in the same Fly
# app, so each statement crosses Fly's private network instead of a laptop's proxy (about 1 s per save that way).
# Builds the bundles and the test image at HEAD, starts the SQL Server machine, runs the runner, prints its output, and
# on any exit destroys the runner and stops the SQL Server machine. Prints when the SQL Server machine is up and down.
#
#   make uc-sql-server        FLY_MSSQL_APP (<your-app>-mssql), SQL_SERVER_REF (HEAD; an older commit shows what
#                             that code did), SQL_SERVER_BASE_REF (a release to upgrade from; unset, the fresh install only)
#
# SQL Server upgrades start from the first release whose bundle installs, so there is no default base yet: no SQL
# Server install of an earlier release exists to upgrade.
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
APP=${FLY_MSSQL_APP:-<your-app>-mssql}
BASE=${SQL_SERVER_BASE_REF:-}
REF=${SQL_SERVER_REF:-HEAD}
SHA=$(git -C "$ROOT" rev-parse --short "$REF")
OUT="$ROOT/dist/sql-server-run"
SCRATCH=$(mktemp -d)
DB_MACHINE=""
RUNNER=""
NAME="uc-runner-$SHA-$$"

finish() {
  status=$?
  [ -n "$RUNNER" ] || RUNNER=$(fly machine list -a "$APP" --json 2>/dev/null | jq -r --arg n "$NAME" '.[] | select(.name == $n) | .id')
  [ -n "$RUNNER" ] && fly machine destroy "$RUNNER" -a "$APP" --force >/dev/null 2>&1 || true
  if [ -n "$DB_MACHINE" ]; then
    fly machine stop "$DB_MACHINE" -a "$APP" >/dev/null && echo "sql-server: machine $DB_MACHINE is DOWN"
  fi
  for tree in "$SCRATCH"/head "$SCRATCH"/base; do
    [ -d "$tree" ] && git -C "$ROOT" worktree remove --force "$tree"
  done
  rm -rf "$SCRATCH"
  exit "$status"
}
trap finish EXIT

# Each bundle comes from its own release's generator: today's generator cannot compile an older ref's models.
rm -rf "$OUT" && mkdir -p "$OUT"
git -C "$ROOT" worktree add -q --detach "$SCRATCH/head" "$REF"
make -s -C "$SCRATCH/head" ISOLATED=1 db-ddl DIALECT=mssql REF=HEAD OUT="$OUT/head"
BUNDLES=(dist/sql-server-run/head)
if [ -n "$BASE" ]; then
  git -C "$ROOT" worktree add -q --detach "$SCRATCH/base" "$BASE"
  make -s -C "$SCRATCH/base" ISOLATED=1 db-ddl DIALECT=mssql REF=HEAD OUT="$OUT/base"
  make -s -C "$SCRATCH/head" ISOLATED=1 db-upgrade-sql DIALECT=mssql FROM="$BASE" TO=HEAD OUT="$OUT/upgrade"
  BUNDLES+=(dist/sql-server-run/base dist/sql-server-run/upgrade)
fi
# No macOS extended attributes: GNU tar on the runner warns about each one.
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$OUT/run.tgz" -C "$ROOT" "${BUNDLES[@]}" \
  docs/usecases/lib/usecase_harness.py docs/usecases/agents-service/scripts/test-uc-565-api.py \
  docs/usecases/agents-service/scripts/test-uc-566-api.py

# The test image from a clean checkout of REF, so nobody's uncommitted files go into it.
IMAGE="registry.fly.io/$APP:runner-$SHA"
fly deploy "$SCRATCH/head" -a "$APP" -c "$SCRATCH/head/deploy/fly/mssql/runner.toml" \
  --ignorefile "$SCRATCH/head/deploy/fly/mssql/runner.dockerignore" --build-only --push --remote-only \
  --image-label "runner-$SHA"

DB_MACHINE=$(fly machine list -a "$APP" --json | jq -r '[.[] | select(.config.mounts != null and (.config.mounts | length) > 0)][0].id')
fly machine start "$DB_MACHINE" -a "$APP" >/dev/null
echo "sql-server: machine $DB_MACHINE is UP"
for _ in $(seq 1 60); do
  passing=$(fly machine list -a "$APP" --json | jq -r --arg id "$DB_MACHINE" \
    '.[] | select(.id == $id) | [.checks[]? | select(.status == "passing")] | length')
  [ "${passing:-0}" -ge 1 ] && break
  sleep 10
done
[ "${passing:-0}" -ge 1 ] || { echo "sql-server: no passing health check after 10 minutes"; exit 1; }

# The machine's own address: the app's name also resolves to the runner. The runner gets MSSQL_SA_PASSWORD as the
# app's secret, in its environment.
SERVER="$DB_MACHINE.vm.$APP.internal,1433"
# Each script runs whatever the other's result, and stops after 10 minutes; the runner fails when either fails.
RUN="cd /app && tar -xzf run.tgz && export OPS_MSSQL_SERVER=$SERVER PYTHONPATH=docs/usecases/lib UV_FROZEN=1 \
OPS_LOG_DIR=/tmp/usecase-logs && failed=0 && \
{ timeout 600 uv run python docs/usecases/agents-service/scripts/test-uc-565-api.py ${BUNDLES[*]} || failed=1; } && \
{ timeout 600 uv run python docs/usecases/agents-service/scripts/test-uc-566-api.py dist/sql-server-run/head || failed=1; } && \
exit \$failed"
# flyctl reports a machine that has already finished, with no restart, as one that failed to start, so its answer is
# not the result: the runner is found by name and read once it has stopped.
fly machine run "$IMAGE" -a "$APP" --region ewr --vm-memory 2048 --restart no --name "$NAME" \
  --file-local "/app/run.tgz=$OUT/run.tgz" --entrypoint sh -- -c "$RUN" || true
RUNNER=$(fly machine list -a "$APP" --json | jq -r --arg n "$NAME" '.[] | select(.name == $n) | .id')
[ -n "$RUNNER" ] || { echo "sql-server: the runner was not created"; exit 1; }
# Its logs are read even when it outlives the wait, so a hang shows where it stopped.
fly machine wait "$RUNNER" -a "$APP" --state stopped --wait-timeout 25m || echo "sql-server: the runner did not stop in 25 minutes"
fly logs -a "$APP" -m "$RUNNER" --no-tail | grep -E '^.*app\[' | sed -E 's/^.*app\[[0-9a-f]+\] [a-z]+ \[info\]//'
code=$(fly machine status "$RUNNER" -a "$APP" | grep -oE 'exit_code=[0-9]+' | head -1 | cut -d= -f2)
echo "sql-server use cases: runner exit ${code:-unknown}"
exit "${code:-1}"
