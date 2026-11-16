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
# Every check a commit can break is a name on the one list (make/checks.mk): the migration downgrades, test token
# lifetimes, imports between services and the code rules of every service among them. They run on this export with the
# export's own sources first (the shared venv's editable installs read the working tree, where other builders'
# uncommitted files would decide the result), so a commit that breaks one cannot turn HEAD red for every builder.
export_path="$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')$PWD/deploy/database:$PWD"
# The one list of checks (make/checks.mk), each run when a staged path can change its result: access decided outside
# can(), the standards ratchets and their history, the files written from code, import directions, the SDK drift check.
# CI's checks job and `make verify` run the same list. They run on this export with the checkout's own tools; GIT_DIR
# lets the history checks read the commits already made, which the export does not have.
printf '%s\n' "${staged[@]}" > "$tmp/.staged"
# A service's typecheck target runs `uv run pyright`, which would build an environment in the export; this `uv` runs the
# command from the checkout's own environment instead. Any other uv command (the SBOM check's `uv export --frozen` on a
# lock change) goes to the real uv, which reads the export's lock and writes nothing.
real_uv="$(command -v uv || echo uv)"
mkdir -p "$tmp/.bin"
printf '#!/bin/sh\nif [ "$1" = run ]; then shift; exec "$@"; fi\nexec "%s" "$@"\n' "$real_uv" > "$tmp/.bin/uv"
chmod +x "$tmp/.bin/uv"
if ! PATH="$tmp/.bin:$root/.venv/bin:$PATH" GIT_DIR="$git_dir" PYTHONPATH="$export_path" make -s -C "$tmp" checks STAGED=1 STAGED_FILES="$tmp/.staged" \
  PY="$root/.venv/bin/python" PYRIGHT="$root/.venv/bin/pyright" LINT_IMPORTS="$root/.venv/bin/lint-imports --no-logo" >"$tmp/.checks.log" 2>&1; then
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
