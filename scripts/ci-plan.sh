#!/usr/bin/env bash
# Prints what ci.yml runs for the changes since <base sha>, as key=value lines; the suites come from verify-changed.sh's
# plan so CI and a local run pick the same ones. Keys: full, services, packages (JSON lists), console, docs, scripts, code, mssql,
# service_jobs (the service matrix: one job per service, or per test shard and its checks for the long suites), release.
# A push to release/* or hotfix/* (GITHUB_REF) is always a full plan with release=true: the impact plan once skipped
# jobs on such a push and let a failure reach develop untested. ci.yml then also runs `checks` and release-proof.
# heavy=false on a pull request (unless CI_FULL=true): the slow jobs (repo, store-mssql, release-proof, the script
# tests) then wait for the merge queue and develop pushes, which run them before anything reaches develop.
# repo_jobs is the repo job's matrix: one entry per suite of the full plan outside the services, plus the check list,
# the script tests and the SDK/changelog checks, so they run side by side.
# A full plan runs what `make verify` runs, spread over jobs: every service of its suite list (make/python.mk,
# VERIFY_POOL) in the service matrix, and the rest of python-verify, sdk-verify and changelog-verify in one job.
set -euo pipefail
base=${1:?usage: ci-plan.sh <base sha | file of changed paths>}
cd "$(git rev-parse --show-toplevel)"
# A file of changed paths instead of a sha, as verify-changed.sh takes, for scripts/tests/test_ci_plan.py.
if [ -f "$base" ]; then changed=$(cat "$base"); else changed=$(git diff --name-only "$base" HEAD); fi
flag() { if grep -qE "$1" <<<"$changed"; then echo true; else echo false; fi; }
json() { if [ "$#" -eq 0 ]; then echo '[]'; else printf '"%s",' "$@" | sed 's/,$//; s/^/[/; s/$/]/'; fi; }

release=false
case "${GITHUB_REF:-}" in refs/heads/release/* | refs/heads/hotfix/*) release=true ;; esac
# CI_FULL=true (ci.yml sets it for a pull request titled with [ci full] or labelled ci:full) runs every job.
if [ "$release" = true ] || [ "${CI_FULL:-}" = true ]; then plan="plan: full"; else
  plan=$(VERIFY_CHANGED_PLAN=jobs scripts/verify-changed.sh "$base")
fi
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
declare -A SHARDS=([agents-service]=6 [tools-service]=5)
jobs_json=()
for svc in ${services[@]+"${services[@]}"}; do
  n=${SHARDS[$svc]:-0}
  if [ "$n" -eq 0 ]; then jobs_json+=("{\"service\":\"$svc\",\"part\":\"verify\"}"); continue; fi
  jobs_json+=("{\"service\":\"$svc\",\"part\":\"checks\"}")
  for i in $(seq 1 "$n"); do jobs_json+=("{\"service\":\"$svc\",\"part\":\"test $i/$n\"}"); done
done
echo "full=$full"
if [ "${GITHUB_EVENT_NAME:-}" = pull_request ] && [ "${CI_FULL:-}" != true ]; then echo "heavy=false"; else echo "heavy=true"; fi
repo_json=()
if [ "$full" = true ]; then
  for p in ${rest[@]+"${rest[@]}"} checks scripts sdk; do repo_json+=("{\"part\":\"$p\"}"); done
fi
if [ "${#repo_json[@]}" -eq 0 ]; then echo "repo_jobs=[]"; else echo "repo_jobs=[$(IFS=,; echo "${repo_json[*]}")]"; fi
echo "release=$release"
# The suites of make verify that are not a service's, which a full plan's repo job runs through python-verify.
echo "repo_pool=${rest[*]+${rest[*]}}"
echo "services=$(json ${services[@]+"${services[@]}"})"
echo "packages=$(json ${packages[@]+"${packages[@]}"})"
# make verify runs the console and docs gates whatever changed, so a full plan does too.
if [ "$full" = true ]; then echo "console=true"; echo "docs=true"; else
  # The console builds on the generated SDK, so an SDK change runs it too; the use-case runner is TypeScript every UI
  # use case imports, so the console job type-checks it.
  echo "console=$(flag '^(apps/|sdk/|packages/usecase-runner/)')"
  echo "docs=$(flag '(\.md$|^docs/)')"
fi
echo "scripts=$(flag '^scripts/')"
# code=false for a change of documents only (markdown or docs/): the checks job then has nothing to check, and the
# leak scan and docs job still run. A use-case script or the harness under docs/usecases is code: the checks job lints
# it and runs make checks' usecase-outputs rule, which the docs job does not.
if [ "$full" = true ] || grep -vqE '(\.md$|^docs/)' <<<"$changed" \
  || grep -qE '^docs/usecases/.*\.(py|mjs|js|ts|sh)$' <<<"$changed"; then echo "code=true"; else echo "code=false"; fi
# The SQL Server job runs the store, kit and identity suites and, per service, route tests that reach the database too
# (platform-service's policies and reply pins among them), so any service, package or database script change runs it;
# documents, the console, the SDK and scripts alone do not.
if [ "$full" = true ]; then echo "mssql=true"; else
  echo "mssql=$(flag '^(services/|packages/|deploy/database/)')"
fi
if [ "${#jobs_json[@]}" -eq 0 ]; then echo "service_jobs=[]"; else echo "service_jobs=[$(IFS=,; echo "${jobs_json[*]}")]"; fi
