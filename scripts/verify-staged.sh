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
for dep in node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules .venv; do
  if [ -e "$root/$dep" ] && [ -d "$(dirname "$tmp/$dep")" ]; then ln -s "$root/$dep" "$tmp/$dep"; fi
done
cd "$tmp"
GIT_DIR="$git_dir" GIT_WORK_TREE="$tmp" GIT_INDEX_FILE="$index" pnpm -s verify
# Access decided outside can() (a 403, a role name, a system lock, a closed policy default) fails unless the access
# register records it (access-exceptions-allowlist.txt). Every commit, not only Python ones: it reads the console too.
# GIT_DIR lets it read the allowlist at HEAD, so a line being added on a row with no decision fails here.
GIT_DIR="$git_dir" "$root/.venv/bin/python" scripts/check_access_exceptions.py
# An exception line needs the owner's approval as a Standards-exception: trailer. A pre-commit hook cannot read the
# message it is about to get, so this reads the commits already made, on the repository itself, not the export.
"$root/.venv/bin/python" "$root/scripts/check_access_exceptions.py" --commits
# Checks a commit needs by what it changes: one `gate` row each, naming the staged paths that call for it, how to fix a
# failure, and the command, run on this export with the export's own sources first (the shared venv's editable installs
# read the working tree, where other builders' uncommitted files would decide the result). Each ran only in verify-head
# before, so a commit that broke one turned HEAD red for every builder. A new check is one more row.
mapfile -t staged < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMRD || true)
export_path="$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')$PWD/deploy/database:$PWD"
gate() {
  local name=$1 paths=$2 fix=$3
  shift 3
  [ "${#staged[@]}" -gt 0 ] || return 0
  printf '%s\n' "${staged[@]}" | grep -qE "$paths" || return 0
  PYTHONPATH="$export_path" "$@" >"$tmp/.gate-$name.log" 2>&1 \
    || { tail -20 "$tmp/.gate-$name.log"; echo "verify-staged: $name: $fix"; exit 1; }
}
# The reviewed SQL Server DDL is what the store models and migrations compile to (c-344).
gate golden-ddl '(^|/)migrations/|/store/|^packages/ops_store/|^deploy/database/' \
  "the SQL Server golden DDL is not what the models compile to; review it, run make db-ddl-golden and stage it" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider deploy/database/tests/test_mssql_ddl.py
# The dependencies page is generated from the lock (make sbom).
gate sbom '(^|/)pyproject\.toml$|^uv\.lock$|^docs/architecture/dependencies\.md$' \
  "docs/architecture/dependencies.md does not match uv.lock; run make sbom and stage it" \
  "$root/.venv/bin/python" scripts/sbom.py --check
# No service imports another, outside a test conftest the allowlist names (c4957ea5 reddened QA this way).
gate cross-service '^services/[^/]+/(src|tests)/' \
  "a service imports another service; import it only in a tests/conftest.py the allowlist names" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider scripts/tests/test_no_cross_service_imports.py
# Python files in the commit get the same lint, format, type and inventory checks verify-head runs. They slipped past the
# console-only gate above and turned HEAD red for every builder until someone fixed them forward.
mapfile -t py < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMR -- '*.py' || true)
# Database code only in store packages, and the layers' import directions (.importlinter, c-346), on this export: the
# shared venv's editable installs point at the working tree, so the export's source goes first on PYTHONPATH.
if [ "${#py[@]}" -gt 0 ] || [ -n "$(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only -- .importlinter)" ]; then
  PYTHONPATH="$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')" "$root/.venv/bin/lint-imports" --no-logo --no-cache
fi
mapfile -t docs < <(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only --diff-filter=ACMRD -- 'services/*/openapi.json' || true)
if [ "${#py[@]}" -gt 0 ] || [ "${#docs[@]}" -gt 0 ]; then
  pp=$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')
  # Each service whose code or openapi.json is in the commit must still match its committed document, checked on this
  # export with its own source first (the shared venv's editables point at the tree): a route change committed without
  # openapi.json, or an openapi.json grafted onto an older HEAD, turned HEAD red three times on 10-18. A shared package
  # can change any service's document, so a commit touching one checks every service.
  # No service file in the commit (a script only) is no services, not a failure: grep finds nothing and exits 1.
  svcs=$(printf '%s\n' "${py[@]}" "${docs[@]}" | grep -oE '^services/[^/]+' | sort -u || true)
  if printf '%s\n' "${py[@]}" | grep -q '^packages/'; then svcs=$(ls -d services/*/ | sed 's#/$##'); fi
  for svc in $svcs; do
    [ -f "$svc/scripts/check_openapi.py" ] || continue
    (cd "$svc" && "$root/.venv/bin/python" -I -c "import runpy, sys; sys.path[:0] = '$pp'.split(':'); sys.argv = ['check_openapi.py']; runpy.run_path('scripts/check_openapi.py', run_name='__main__')") \
      || { echo "verify-staged: $svc/openapi.json does not match the committed app; run make -C $svc openapi and stage it"; exit 1; }
  done
fi
# Database-specific code outside ops_store (c-343), on this export with its own checker and baseline (an export whose
# checker predates the strict rule skips it); --commits reads the repository for a raised row without its trailer.
base_staged=$(GIT_INDEX_FILE="$index" git -C "$root" diff --cached --name-only -- portable-baseline.txt)
if grep -q -- '--commits' scripts/check_portable_store.py && { [ "${#py[@]}" -gt 0 ] || [ -n "$base_staged" ]; }; then
  PYTHONPATH="$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')" \
    "$root/.venv/bin/python" scripts/check_portable_store.py --strict
  "$root/.venv/bin/python" "$root/scripts/check_portable_store.py" --commits
fi
if [ "${#py[@]}" -gt 0 ]; then
  "$root/.venv/bin/ruff" check "${py[@]}"
  "$root/.venv/bin/ruff" format --check "${py[@]}"
  # No pyright here: the shared virtualenv resolves workspace packages from the working tree, so other builders'
  # uncommitted edits made it fail or pass this commit by accident. verify-head type-checks the committed tree.
  "$root/.venv/bin/python" scripts/store_inventory.py --check
  # Each changed service's app must import from the committed files alone: a swept hunk that imports a module someone
  # has not committed yet broke every import of ops_agents on HEAD. Source paths point at this export, not the tree.
  pp=$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src 2>/dev/null | tr '\n' ':')
  for svc in $(printf '%s\n' "${py[@]}" | grep -oE '^services/[^/]+' | sort -u); do
    for app in $(find "$svc/src" -name app.py 2>/dev/null | awk '{ print length, $0 }' | sort -n | head -1 | cut -d' ' -f2); do
      mod=$(echo "${app#$svc/src/}" | sed 's#/#.#g; s#\.py$##')
      PYTHONPATH="$pp" PYTHONSAFEPATH=1 "$root/.venv/bin/python" -I -c "import sys; sys.path[:0]='$pp'.split(':'); import $mod" \
        || { echo "verify-staged: $mod does not import from the committed files"; exit 1; }
    done
  done
fi
