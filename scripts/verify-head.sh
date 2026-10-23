#!/usr/bin/env bash
# Run `make verify` against HEAD, not the working tree. Card checks run while other sessions hold uncommitted edits in
# the shared tree, so a check on the tree measures their work, not the commit under test. The export gets its own
# node_modules (offline, from the store) and its own test database, dropped at exit, so two lanes checking at once
# never share one.
set -euo pipefail
# One runner on this machine runs the full suite (the planning repo scripts/ops-ai/qa-watch.sh sets QA_RUNNER=1). Several
# builders running it at once slowed every run and timed out database connects; ask the runner with scripts/qa.sh wait.
# QA_LOCAL=1 runs it here anyway, for a machine with no runner.
if [ -z "${QA_RUNNER:-}${QA_LOCAL:-}" ]; then
  echo "verify-head: ask the QA runner instead: scripts/qa.sh wait (QA_LOCAL=1 runs it here)" >&2
  exec "$(dirname "$0")/qa.sh" wait
fi
root="$(git rev-parse --show-toplevel)"
head="$(git -C "$root" rev-parse --short HEAD)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ops-ai-head.XXXXXX")"
db_name="ops_test_head_$$"
pg_port="${OPS_PG_PORT:-5477}"
cleanup() {
  (cd "$root" && uv run --quiet python -c "import asyncio, asyncpg
async def drop():
    c = await asyncpg.connect('postgresql://ops:ops@localhost:$pg_port/postgres')
    # Suites make sibling databases from the test database's name (_conformance, _tools_egress, ...).
    for (name,) in await c.fetch('SELECT datname FROM pg_database'):
        if name == '$db_name' or name.startswith('${db_name}_'):
            await c.execute(f'DROP DATABASE IF EXISTS \"{name}\" WITH (FORCE)')
    await c.close()
asyncio.run(drop())" >/dev/null 2>&1 || true)
  rm -rf "$tmp"
}
trap cleanup EXIT
git -C "$root" archive "$head" | tar -x -C "$tmp"
# check-docs lists files with git, so the export is a throwaway repo at HEAD's content
(cd "$tmp" && git init -q && git add -A >/dev/null && git -c user.name=verify -c user.email=verify@local commit -q -m head)
cp "$root/.env" "$tmp/.env" 2>/dev/null || true
cd "$tmp"
pnpm install --offline --silent >/dev/null 2>&1 || pnpm install --prefer-offline --silent >/dev/null
uv sync --frozen --quiet  # the export has no .venv; the lock as committed, as make install does
db="${OPS_TEST_DATABASE_URL_HEAD:-postgresql+asyncpg://ops:ops@localhost:$pg_port/$db_name}"
echo "verify-head: export of $head ready in ${SECONDS}s"
if [ -n "${VERIFY_RUN:-}" ]; then
  # Another check on the same export, such as the QA runner's nightly ui use cases (qa-watch.sh): its command as given.
  OPS_TEST_DATABASE_URL="$db" bash -c "$VERIFY_RUN"
elif [ -n "${VERIFY_SINCE:-}" ]; then
  # Per-cycle mode: only what the changes since VERIFY_SINCE can affect (scripts/verify-changed.sh).
  git -C "$root" diff --name-only "$VERIFY_SINCE" "$head" > "$tmp/.changed-paths"
  OPS_TEST_DATABASE_URL="$db" scripts/verify-changed.sh "$tmp/.changed-paths"
else
  OPS_TEST_DATABASE_URL="$db" make -s verify
fi
echo "verify-head: HEAD $head green"
