#!/usr/bin/env bash
# Prints what ci.yml runs for the changes since <base sha>, as key=value lines; the suites come from verify-changed.sh's
# plan so CI and a local run pick the same ones. Keys: full, services, packages (JSON lists), console, docs, scripts.
set -euo pipefail
base=${1:?usage: ci-plan.sh <base sha>}
cd "$(git rev-parse --show-toplevel)"
changed=$(git diff --name-only "$base" HEAD)
flag() { if grep -qE "$1" <<<"$changed"; then echo true; else echo false; fi; }
json() { if [ "$#" -eq 0 ]; then echo '[]'; else printf '"%s",' "$@" | sed 's/,$//; s/^/[/; s/$/]/'; fi; }

plan=$(VERIFY_CHANGED_PLAN=jobs scripts/verify-changed.sh "$base")
if grep -qx 'plan: full' <<<"$plan"; then
  full=true; services=(); packages=()
else
  full=false
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
echo "full=$full"
echo "services=$(json ${services[@]+"${services[@]}"})"
echo "packages=$(json ${packages[@]+"${packages[@]}"})"
echo "console=$(flag '^apps/')"
echo "docs=$(flag '(\.md$|^docs/)')"
echo "scripts=$(flag '^scripts/')"
