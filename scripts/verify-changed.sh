#!/usr/bin/env bash
# Runs only the checks the changes since BASE can affect: the suites of changed services, the packages that changed and
# every service or package that depends on them, the console and docs gates when their files changed, and the fast
# generated-file checks always. A change to uv.lock or to any package under packages/ runs the full `make verify`.
# The full suite still runs on a schedule and before a public push; this is for the per-commit cycle.
set -euo pipefail
# Takes a base sha, or a file listing the changed paths (verify-head passes one, since its export has no history).
arg=${1:?usage: verify-changed.sh <base-sha | file of changed paths>}
if [ -f "$arg" ]; then base="(list)"; mapfile -t changed < "$arg"; else base=$arg; mapfile -t changed < <(git diff --name-only "$base" HEAD); fi
[ "${#changed[@]}" -eq 0 ] && { echo "verify-changed: nothing changed since $base"; exit 0; }
full() { echo "verify-changed: $1, running the full suite"; exec make -s verify; }
declare -A pkgs svcs; console=0; docs=0
for f in "${changed[@]}"; do
  case "$f" in
    uv.lock|pyproject.toml|Makefile|make/*) full "$f changed" ;;
    packages/*) full "shared package ${f%%/src*} changed" ;;
    packages/usecase-runner/*) ;;
    packages/*/*) p=${f#packages/}; pkgs[${p%%/*}]=1 ;;
    services/*/*) s=${f#services/}; svcs[${s%%/*}]=1 ;;
    apps/console/*) console=1 ;;
    *.md) docs=1 ;;
  esac
done
# A changed package also runs every service whose pyproject depends on it.
for p in "${!pkgs[@]}"; do
  dep=$(echo "$p" | tr '_' '-')
  for py in services/*/pyproject.toml; do grep -q "\"$dep" "$py" && svcs[$(basename "$(dirname "$py")")]=1; done
done
echo "verify-changed since $base: packages [${!pkgs[*]}] services [${!svcs[*]}] console=$console docs=$docs"
mapfile -t py < <(printf '%s\n' "${changed[@]}" | grep -E '\.py$' | while read -r f; do [ -f "$f" ] && echo "$f"; done)
if [ "${#py[@]}" -gt 0 ]; then uv run ruff format --check "${py[@]}"; uv run ruff check "${py[@]}"; fi
for p in "${!pkgs[@]}"; do
  [ -d "packages/$p/tests" ] && (cd "packages/$p" && OPS_DATABASE_URL=${OPS_TEST_DATABASE_URL:-} uv run pytest -q)
done
for s in "${!svcs[@]}"; do
  if [ "$s" = agents-service ]; then env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY make -s -C "services/$s" verify
  else make -s -C "services/$s" verify; fi
done
[ "$console" = 1 ] && make -s console-verify
[ "$docs" = 1 ] && make -s docs-verify
uv run python scripts/store_inventory.py --check
uv run python scripts/roles_matrix.py --check
uv run python deploy/k8s/generate.py --check
uv run lint-imports --no-logo
uv run python scripts/check_portable_store.py --strict
echo "verify-changed: green"
