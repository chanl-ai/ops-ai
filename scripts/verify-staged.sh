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
for dep in node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules sdk/typescript/node_modules .venv; do
  if [ -e "$root/$dep" ] && [ -d "$(dirname "$tmp/$dep")" ]; then ln -s "$root/$dep" "$tmp/$dep"; fi
done
cd "$tmp"
# Each check below runs only when a staged path can change its result (c-566): a docs-only commit ran all the console's
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
# Access decided outside can() (a 403, a role name, a system lock, a closed policy default) fails unless the access
# register records it (access-exceptions-allowlist.txt). It reads service and package code and the console, so it runs
# when one of those or the allowlist is staged. GIT_DIR lets it read the allowlist at HEAD, so a line being added on a
# row with no decision fails here.
if touches '^(services|packages)/[^/]+/src/.*\.py$|^apps/(console|embed)/src/|^access-exceptions-allowlist\.txt$|^docs/architecture/roles-and-permissions\.md$'; then
  GIT_DIR="$git_dir" "$root/.venv/bin/python" scripts/check_access_exceptions.py
  # An exception line needs the owner's approval as a Standards-exception: trailer. A pre-commit hook cannot read the
  # message it is about to get, so this reads the commits already made, on the repository itself, not the export.
  "$root/.venv/bin/python" "$root/scripts/check_access_exceptions.py" --commits
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
# The reviewed SQL Server DDL is what the store models and migrations compile to (c-344), every revision renders
# offline for SQL Server installs, and the SQL Server system principal reads what PostgreSQL's system role reads;
# the last two reddened HEAD three times on 10-30 because only the full QA run checked them.
gate golden-ddl '(^|/)migrations/|/store/|^packages/ops_store/|^deploy/database/' \
  "the SQL Server golden DDL is not what the models compile to; review it, run make db-ddl-golden and stage it" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider deploy/database/tests/test_mssql_ddl.py \
    deploy/database/tests/test_offline.py deploy/database/tests/test_model_parity.py
# Every table is marked TENANT_SCOPED or system(reason); a migration that adds one unmarked turned HEAD red overnight.
gate isolation '(^|/)migrations/|/store/|^packages/ops_store/' \
  "a table is not marked TENANT_SCOPED or system(reason) (above); mark it in its store models" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider deploy/database/tests/test_isolation_markings.py \
  scripts/tests/test_team_boundary.py
# Test person tokens live an hour: a short one flakes under load (c81399fd). The scan is about 2 s.
gate token-lifetime '(^|/)tests/.*\.py$' \
  "a test mints a short-lived person token (above); mint it for an hour, or allowlist an expiry test with its reason" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider scripts/tests/test_test_token_lifetime.py
# ops_store is under every service; its own tests (about 11 s) run when it changes.
gate ops-store '^packages/ops_store/|^services/[^/]+/src/[^/]+/store/' \
  "an ops_store test fails (above); every service reads this package" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider packages/ops_store/tests
# The dependencies page is generated from the lock (make sbom).
gate sbom '(^|/)pyproject\.toml$|^uv\.lock$|^docs/architecture/dependencies\.md$' \
  "docs/architecture/dependencies.md does not match uv.lock; run make sbom and stage it" \
  "$root/.venv/bin/python" scripts/sbom.py --check
# deploy/k8s/base carries every shared setting, read from the compose file's x-settings (deploy/k8s/generate.py); a
# setting committed without regenerating it turned HEAD red at 12:52 on 10-30, and only QA caught it.
gate k8s '^deploy/compose/app\.yaml$|^deploy/k8s/|^(services|packages)/[^/]+/src/[^/]+/settings\.py$' \
  "deploy/k8s/base is not what deploy/k8s/generate.py writes; run uv run python deploy/k8s/generate.py and stage it" \
  "$root/.venv/bin/python" deploy/k8s/generate.py --check
# The SDKs' generated layer is what the committed OpenAPI documents say (sdk/generate.py); a route body change
# committed without `make sdk` turned HEAD red on 10-30, and only QA's full run checked it.
gate sdk '^services/[^/]+/openapi\.json$|^sdk/' \
  "the generated SDK does not match the services' OpenAPI documents; run make sdk and stage sdk/" \
  "$root/.venv/bin/python" sdk/generate.py --check
# No service imports another, outside a test conftest the allowlist names (c4957ea5 reddened QA this way).
gate cross-service '^services/[^/]+/(src|tests)/' \
  "a service imports another service; import it only in a tests/conftest.py the allowlist names" \
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider scripts/tests/test_no_cross_service_imports.py
# The repo's code rules (environment reads only in settings, and the rest of check_standards) run on any staged Python in
# a service or package: a rule-4 read in ops_service_kit passed the commit and turned HEAD red for every builder (3e8e5f71).
gate standards '^(services|packages)/.*\.py$' \
  "a code rule in services/agents-service/scripts/check_standards.py fails (above); fix the code" \
  bash -c 'cd services/agents-service && "$0" scripts/check_standards.py' "$root/.venv/bin/python"
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
  # changes the documents of the services that depend on it, directly or through another package (scripts/dependants.py).
  # No service file in the commit (a script only) is no services, not a failure: grep finds nothing and exits 1.
  svcs=$(printf '%s\n' "${py[@]}" "${docs[@]}" | grep -oE '^services/[^/]+' | sort -u || true)
  mapfile -t changed_pkgs < <(printf '%s\n' "${py[@]}" | grep -oE '^packages/[^/]+' | grep -v '^packages/usecase-runner$' | sort -u || true)
  if [ "${#changed_pkgs[@]}" -gt 0 ]; then
    svcs=$(printf '%s\n' $svcs; "$root/.venv/bin/python" scripts/dependants.py "${changed_pkgs[@]}" | awk '$1 == "service" { print $2 } $1 == "unknown" { print "ALL" }')
    if grep -qx ALL <<<"$svcs"; then svcs=$(ls -d services/*/ | sed 's#/$##'); fi
    svcs=$(printf '%s\n' $svcs | sort -u)
  fi
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
  # Strict pyright on the commit's own Python files, the ones a service or package type-checks, on this export. The
  # shared virtualenv's editable installs point at the working tree, where another builder's uncommitted edit made it
  # fail or pass a commit by accident, so a pyrightconfig.json written into the export puts the export's sources first
  # in every execution environment. Paths are physical: under macOS's /var -> /private/var link, sources named by the
  # logical path did not match the files pyright opened, and it reported one module as two types. Type errors in staged
  # tests reached HEAD three times in one hour on 10-30.
  mapfile -t typed < <(printf '%s\n' "${py[@]}" | grep -E '^(packages/[^/]+/|services/[^/]+/(src|tests|migrations|scripts|experiments)/)' || true)
  if [ "${#typed[@]}" -gt 0 ]; then
    here=$(pwd -P)
    "$root/.venv/bin/python" - "$here" <<'PY'
import json, sys, tomllib
from pathlib import Path

here = Path(sys.argv[1])
config = tomllib.loads((here / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pyright"]
sources = sorted(str(p) for p in [*here.glob("packages/*/src"), *here.glob("services/*/src")])
for env in config.get("executionEnvironments", []):
    env["extraPaths"] = sources + env.get("extraPaths", [])
(here / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")
PY
    "$root/.venv/bin/pyright" --project "$here/pyrightconfig.json" "${typed[@]/#/$here/}"
  fi
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
