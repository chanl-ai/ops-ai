#!/usr/bin/env bash
# The pre-commit gate (`pnpm verify`) on what is being committed, not on the working tree. Builders share one tree, so a
# half-written file of someone else's would otherwise fail every commit. The commit's index (GIT_INDEX_FILE, which a
# pathspec commit points at its own temporary index) is exported to a temporary directory; dependencies are linked from
# the tree; the gates run there with git reading that same index, so check-docs lists the committed files only.
set -euo pipefail
# /usr/local/bin/git on this Mac is an Intel build, so a hook it starts runs under Rosetta and the universal Python
# picks its Intel half, which cannot load the arm64 extensions in .venv. Re-run the gate natively on Apple silicon.
if [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = x86_64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = 1 ] && [ -z "${OPS_GATE_NATIVE:-}" ]; then
  nb=/opt/homebrew/bin/bash; [ -x "$nb" ] || nb=$(command -v bash)
  OPS_GATE_NATIVE=1 exec arch -arm64 "$nb" "$0" "$@"
fi
root="$(git rev-parse --show-toplevel)"
git_dir="$(git -C "$root" rev-parse --absolute-git-dir)"
index="${GIT_INDEX_FILE:-$git_dir/index}"
case "$index" in /*) ;; *) index="$PWD/$index" ;; esac
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ops-ai-staged.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
GIT_INDEX_FILE="$index" git -C "$root" checkout-index -a --prefix="$tmp/"
# apps/embed/node_modules: console verify type-checks the embed app too, which draws the console's chat components.
# sdk/typescript/node_modules: the sdk gate runs openapi-typescript from there.
for dep in node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules sdk/typescript/node_modules; do
  if [ -e "$root/$dep" ] && [ -d "$(dirname "$tmp/$dep")" ]; then ln -s "$root/$dep" "$tmp/$dep"; fi
done
# The Python checks run on the checkout's own environment ($root/.venv/bin/...), which is never linked into the export:
# the export is a whole uv workspace, so a `uv run` inside it would reinstall every member into a linked .venv pointing
# at this temporary folder, and the checkout's imports would break once the folder is deleted. UV_NO_SYNC stops any uv
# call made from here from installing anything at all.
export UV_NO_SYNC=1
cd "$tmp"
# Each check below runs only when a staged path can change its result: a docs-only commit ran all the console's
# tests and read every tracked file. The thorough per-service tests run before a push (.githooks/pre-push), and the
# full suite on each new HEAD (the QA runner) and before a snapshot leaves (repo.sh).
mapfile -t staged < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMRD || true)
mapfile -t present < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR || true)
# A here-string, not a pipe: under pipefail, grep -q leaving early can fail a long printf with SIGPIPE.
touches() { [ "${#staged[@]}" -gt 0 ] && grep -qE "$1" <<<"$(printf '%s\n' "${staged[@]}")"; }
# The console's typecheck, standards and tests (apps/console/CLAUDE.md), and the embed app's typecheck, which draws the
# console's chat components.
if touches '^apps/(console|embed)/|^package\.json$|^pnpm-lock\.yaml$'; then
  GIT_DIR="$git_dir" GIT_WORK_TREE="$tmp" GIT_INDEX_FILE="$index" pnpm -s --filter @ops-ai/console verify
fi
# Where docs live, on the staged files; docs/README.md is always named, so the index's entries are checked even when the
# commit only deletes. The private-path scan reads the staged files only.
GIT_DIR="$git_dir" GIT_WORK_TREE="$tmp" GIT_INDEX_FILE="$index" node scripts/check-docs.mjs docs/README.md "${present[@]}"
if touches '^scripts/check-public-paths\.mjs$'; then node scripts/check-public-paths.mjs --self-test; fi
if [ "${#present[@]}" -gt 0 ]; then node scripts/check-public-paths.mjs "${present[@]}"; fi
if [ "${#present[@]}" -gt 0 ]; then
  "$root/.venv/bin/python" "$root/scripts/scrub_board_paths.py" --root "$PWD" --check "${present[@]}" \
    || { echo "verify-staged: a staged file names a home path or the machine login; run uv run python scripts/scrub_board_paths.py --apply"; exit 1; }
fi
# Checks a commit needs by what it changes: one `gate` row each, naming the staged paths that call for it, how to fix a
# failure, and the command, run on this export with the export's own sources first (the shared venv's editable installs
# read the working tree, where other builders' uncommitted files would decide the result). Each ran only in verify-head
# before, so a commit that broke one turned HEAD red for every builder. A new check is one more row.
export_path="$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')$PWD/deploy/database:$PWD"
gate() {
  local name=$1 paths=$2 fix=$3
  shift 3
  [ "${#staged[@]}" -gt 0 ] || return 0
  # A here-string, not a pipe: under pipefail `grep -q` stops reading at its first match, printf takes SIGPIPE on a
  # long staged list, and the pipeline's 141 read as no match and skipped the gate.
  grep -qE "$paths" <<<"$(printf '%s\n' "${staged[@]}")" || return 0
  PYTHONPATH="$export_path" "$@" >"$tmp/.gate-$name.log" 2>&1 \
    || { tail -20 "$tmp/.gate-$name.log"; echo "verify-staged: $name: $fix"; exit 1; }
}
# Every table is marked TENANT_SCOPED or system(reason); a migration that adds one unmarked turned HEAD red overnight.
# A migration's downgrade must undo its upgrade: the runtime-logins test migrates each chain down and back up, and
# three empty downgrades (tools 0048, 0049, 0050) each held QA red for about an hour on 10-31.
gate downgrades '/migrations/versions/.*\.py$' \
  "a staged migration's downgrade() does nothing; make it undo exactly what upgrade() did" \
  python3 "$root/scripts/check_downgrades.py" --root "$PWD" "${staged[@]}"
# Test person tokens live an hour: a short one flakes under load (c81399fd). The scan is about 2 s.
gate token-lifetime '(^|/)tests/.*\.py$' \
  "a test mints a short-lived person token (above); mint it for an hour, or allowlist an expiry test with its reason" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider scripts/tests/test_test_token_lifetime.py
# No service imports another, outside a test conftest the allowlist names (c4957ea5 reddened QA this way).
gate cross-service '^services/[^/]+/(src|tests)/' \
  "a service imports another service; import it only in a tests/conftest.py the allowlist names" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider scripts/tests/test_no_cross_service_imports.py
# The repo's code rules (environment reads only in settings, and the rest of check_standards) run on any staged Python in
# a service or package: a rule-4 read in ops_service_kit passed the commit and turned HEAD red for every builder (3e8e5f71).
gate standards '^(services|packages)/.*\.py$' \
  "a code rule in services/agents-service/scripts/check_standards.py fails (above); fix the code" \
  bash -c 'cd services/agents-service && "$0" scripts/check_standards.py' "$root/.venv/bin/python"
# The one list of checks (make/checks.mk), each run when a staged path can change its result: access decided outside
# can(), the standards ratchets and their history, the files written from code, import directions, the SDK drift check.
# CI's checks job and `make verify` run the same list. They run on this export with the checkout's own tools; GIT_DIR
# lets the history checks read the commits already made, which the export does not have.
printf '%s\n' "${staged[@]}" > "$tmp/.staged"
if ! GIT_DIR="$git_dir" PYTHONPATH="$export_path" make -s -C "$tmp" checks STAGED=1 STAGED_FILES="$tmp/.staged" \
  PY="$root/.venv/bin/python" LINT_IMPORTS="$root/.venv/bin/lint-imports --no-logo" >"$tmp/.checks.log" 2>&1; then
  tail -60 "$tmp/.checks.log"; echo "verify-staged: make checks failed (above); fix what it names"; exit 1
fi
# Python files in the commit are linted and format-checked; a second each.
mapfile -t py < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR -- '*.py' || true)
if [ "${#py[@]}" -gt 0 ]; then
  "$root/.venv/bin/ruff" check "${py[@]}"
  "$root/.venv/bin/ruff" format --check "${py[@]}"
fi
# Slower checks that build each service (OpenAPI documents, the generated SDKs, import directions, strict types, the
# SQL Server DDL and store tests) run in CI on every pull request and in `make verify`, not on each commit. After a route
# or DTO change, `make openapi` regenerates every service's document and the SDKs in one step.
