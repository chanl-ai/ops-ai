#!/usr/bin/env bash
# What a pull request's CI runs (.github/workflows/ci.yml), as key=value lines for $GITHUB_OUTPUT. The suites come from
# scripts/verify-changed.sh's own plan, so CI and a local `scripts/verify-changed.sh <base>` pick the same members:
#
#   full=true|false     uv.lock, pyproject.toml or the Makefiles changed: run the whole `make verify` instead
#   services=[...]      service folders whose `make -C services/<name> verify` runs, as JSON
#   packages=[...]      package folders whose tests run, as JSON
#   console=true|false  apps/ changed: `pnpm verify`
#   docs=true|false     a Markdown file or docs/ changed: `make docs-verify`
#   scripts=true|false  scripts/ changed: their tests
#
#   scripts/ci-plan.sh <base sha>
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
      # A planned service's Makefile answers every verb with "not started"; there is nothing to run.
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
