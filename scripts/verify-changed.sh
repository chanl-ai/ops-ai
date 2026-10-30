#!/usr/bin/env bash
# Runs only the checks the changes since BASE can affect: the suites of changed services, the packages that changed and
# every service or package that depends on them, the console and docs gates when their files changed, and the fast
# generated-file checks always. A change to uv.lock, pyproject.toml or the Makefiles runs the full `make verify`.
# The member suites run side by side, each on its own test database (<db>_<member>), and print in a fixed order.
# VERIFY_CHANGED_DEPTH=direct stops at the members that depend on a changed package themselves: the push check
# (.githooks/pre-push) runs that, and the full suite on each new HEAD covers the rest.
set -euo pipefail
# Takes a base sha, or a file listing the changed paths (verify-head passes one, since its export has no history).
arg=${1:?usage: verify-changed.sh <base-sha | file of changed paths>}
if [ -f "$arg" ]; then base="(list)"; mapfile -t changed < "$arg"; else base=$arg; mapfile -t changed < <(git diff --name-only "$base" HEAD); fi
[ "${#changed[@]}" -eq 0 ] && { echo "verify-changed: nothing changed since $base"; exit 0; }
# VERIFY_CHANGED_PLAN=1 prints what would run and stops (scripts/tests/test_dependants.py).
plan=${VERIFY_CHANGED_PLAN:-}
full() { echo "verify-changed: $1, running the full suite"; [ -n "$plan" ] && { echo "plan: full"; exit 0; }; exec make -s verify; }
# Assigned empty: under set -u, bash reads a declared but unassigned array as unbound.
declare -A pkgs=() svcs=(); console=0; docs=0
for f in "${changed[@]}"; do
  case "$f" in
    uv.lock|pyproject.toml|Makefile|make/*) full "$f changed" ;;
    packages/usecase-runner/*) ;;
    packages/*/*) p=${f#packages/}; pkgs[packages/${p%%/*}]=1 ;;
    services/*/*) s=${f#services/}; svcs[${s%%/*}]=1 ;;
    apps/console/*) console=1 ;;
    *.md) docs=1 ;;
  esac
done
# A changed package runs itself and every member that depends on it, directly or through another package, read
# from the workspace's pyproject.toml files (scripts/dependants.py, c-566); a directory that is no member runs everything.
if [ "${#pkgs[@]}" -gt 0 ]; then
  declare -A reached=()
  depth=(); [ "${VERIFY_CHANGED_DEPTH:-}" = direct ] && depth=(--direct)
  while read -r kind dir; do
    case "$kind" in
      unknown) full "package $dir is no workspace member" ;;
      package) reached[$dir]=1 ;;
      service) svcs[${dir#services/}]=1 ;;
    esac
  done < <(uv run --quiet python scripts/dependants.py "${depth[@]}" "${!pkgs[@]}")
  for d in "${!reached[@]}"; do pkgs[$d]=1; done
fi
echo "verify-changed since $base: packages [${!pkgs[*]}] services [${!svcs[*]}] console=$console docs=$docs"
# What runs, in the order it starts: each service's verify, sorted, so agents-service (the longest) starts first, then
# each reached package's tests. Arrays, not a command substitution: a substitution that fails starts nothing and the run
# still ended green. VERIFY_CHANGED_PLAN=1 prints the plan, =jobs the jobs (scripts/tests/test_dependants.py).
mapfile -t services < <(printf '%s\n' "${!svcs[@]}" | grep . | sort || true)
mapfile -t packages < <(printf '%s\n' "${!pkgs[@]}" | grep . | sort || true)
mapfile -t tested < <(for p in "${packages[@]}"; do [ -d "$p/tests" ] && echo "$p"; done || true)
[ "$plan" = jobs ] && { echo "jobs: $(printf '%s\n' "${services[@]}" "${tested[@]##*/}" | grep . | xargs)"; exit 0; }
[ -n "$plan" ] && { echo "plan: packages [${packages[*]}] services [${services[*]}]"; exit 0; }
mapfile -t py < <(printf '%s\n' "${changed[@]}" | grep -E '\.py$' | while read -r f; do [ -f "$f" ] && echo "$f"; done)
if [ "${#py[@]}" -gt 0 ]; then uv run ruff format --check "${py[@]}"; uv run ruff check "${py[@]}"; fi
[ "${#pkgs[@]}" -gt 0 ] && uv run pyright "${!pkgs[@]}"
# One background job per member, each writing its own log; VERIFY_JOBS (default 4) run at once.
db=${OPS_TEST_DATABASE_URL:-}
logs=$(mktemp -d "${TMPDIR:-/tmp}/ops-verify-changed.XXXXXX")
trap 'rm -rf "$logs"' EXIT
jobs_order=()
job() {
  local name=$1; shift
  while [ "$(jobs -rp | wc -l)" -ge "${VERIFY_JOBS:-4}" ]; do wait -n || true; done
  # In an if, so set -e neither ends the job early nor skips writing its exit code.
  ( if "$@" > "$logs/$name.log" 2>&1; then echo 0; else echo $?; fi > "$logs/$name.rc" ) &
  jobs_order+=("$name")
}
package_tests() {
  local p=$1 pdb=${db:+${db}_$(basename "$1")}
  # Chained: set -e does not apply inside a function run as an if condition.
  { [ -z "$pdb" ] || uv run --quiet python scripts/test_db.py "$pdb"; } && cd "$p" && OPS_DATABASE_URL=$pdb uv run pytest -q
}
service_verify() {
  local s=$1 sdb=${db:+${db}_${1%-service}}
  if [ "$s" = agents-service ]; then
    env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY OPS_TEST_DATABASE_URL="$sdb" make -s -C "services/$s" verify
  else OPS_TEST_DATABASE_URL="$sdb" make -s -C "services/$s" verify; fi
}
for s in "${services[@]}"; do job "$s" service_verify "$s"; done
for p in "${tested[@]}"; do job "$(basename "$p")" package_tests "$p"; done
wait
failed=()
for name in "${jobs_order[@]}"; do
  echo "== $name"; cat "$logs/$name.log"
  [ "$(cat "$logs/$name.rc")" = 0 ] || failed+=("$name")
done
[ "${#failed[@]}" -eq 0 ] || { echo "verify-changed: failed: ${failed[*]}"; exit 1; }
want=$(( ${#services[@]} + ${#tested[@]} ))
[ "${#jobs_order[@]}" -eq "$want" ] || { echo "verify-changed: started ${#jobs_order[@]} of $want suites"; exit 1; }
[ "$console" = 1 ] && make -s console-verify
[ "$docs" = 1 ] && make -s docs-verify
uv run python scripts/store_inventory.py --check
uv run python scripts/roles_matrix.py --check
uv run python deploy/k8s/generate.py --check
uv run lint-imports --no-logo
uv run python scripts/check_portable_store.py --strict
echo "verify-changed: green"
