#!/usr/bin/env bash
# Prints what ci.yml runs for the changes since <base sha>, as key=value lines; the suites come from verify-changed.sh's
# plan so CI and a local run pick the same ones. Keys: full, services, packages (JSON lists), console, docs, scripts,
# service_jobs (the service matrix: one job per service, or per test shard and its checks for the long suites).
# A full plan runs what `make verify` runs, spread over jobs: every service of its suite list (make/python.mk,
# VERIFY_POOL) in the service matrix, and the rest of python-verify, sdk-verify and changelog-verify in one job.
set -euo pipefail
base=${1:?usage: ci-plan.sh <base sha | file of changed paths>}
cd "$(git rev-parse --show-toplevel)"
# A file of changed paths instead of a sha, as verify-changed.sh takes, for scripts/tests/test_ci_plan.py.
if [ -f "$base" ]; then changed=$(cat "$base"); else changed=$(git diff --name-only "$base" HEAD); fi
flag() { if grep -qE "$1" <<<"$changed"; then echo true; else echo false; fi; }
json() { if [ "$#" -eq 0 ]; then echo '[]'; else printf '"%s",' "$@" | sed 's/,$//; s/^/[/; s/$/]/'; fi; }

plan=$(VERIFY_CHANGED_PLAN=jobs scripts/verify-changed.sh "$base")
if grep -qx 'plan: full' <<<"$plan"; then
  full=true; packages=(); rest=()
  read -r -a pool <<<"$(make -s -f make/python.mk -f /dev/stdin <<<'print-pool: ; @echo $(VERIFY_POOL)' print-pool 2>/dev/null)"
  services=(); rest=()
  for p in "${pool[@]}"; do
    if [ -d "services/${p#pool-}-service" ]; then services+=("${p#pool-}-service"); else rest+=("$p"); fi
  done
else
  full=false; rest=()
  read -r -a jobs <<<"$(sed -n 's/^jobs: //p' <<<"$plan")"
  services=(); packages=()
  for j in ${jobs[@]+"${jobs[@]}"}; do
    if [ -d "services/$j" ]; then
      # A planned service has no verify target.
      grep -q '^verify:' "services/$j/Makefile" && services+=("$j")
    elif [ -d "packages/$j/tests" ]; then
      packages+=("$j")
    fi
  done
fi
# The long suites run as test shards (scripts/test_shard.py) beside one job for their lint, types and gates.
declare -A SHARDS=([agents-service]=4 [tools-service]=3)
jobs_json=()
for svc in ${services[@]+"${services[@]}"}; do
  n=${SHARDS[$svc]:-0}
  if [ "$n" -eq 0 ]; then jobs_json+=("{\"service\":\"$svc\",\"part\":\"verify\"}"); continue; fi
  jobs_json+=("{\"service\":\"$svc\",\"part\":\"checks\"}")
  for i in $(seq 1 "$n"); do jobs_json+=("{\"service\":\"$svc\",\"part\":\"test $i/$n\"}"); done
done
echo "full=$full"
# The suites of make verify that are not a service's, which a full plan's repo job runs through python-verify.
echo "repo_pool=${rest[*]+${rest[*]}}"
echo "services=$(json ${services[@]+"${services[@]}"})"
echo "packages=$(json ${packages[@]+"${packages[@]}"})"
# make verify runs the console and docs gates whatever changed, so a full plan does too.
if [ "$full" = true ]; then echo "console=true"; echo "docs=true"; else
  echo "console=$(flag '^apps/')"
  echo "docs=$(flag '(\.md$|^docs/)')"
fi
echo "scripts=$(flag '^scripts/')"
if [ "${#jobs_json[@]}" -eq 0 ]; then echo "service_jobs=[]"; else echo "service_jobs=[$(IFS=,; echo "${jobs_json[*]}")]"; fi
