#!/usr/bin/env bash
# make skills-proof (c-554): runs every developer skill's proof block (docs/guide/skills/*.md, the ```bash proof
# fence) in a fresh devcontainer, ops-run first, then the rest by name. A skill that needs the stack starts it in its
# own block (`make up`), and every skill's stack comes down (`make down`) before the next starts, so the skills that only
# run use cases (which bring their own stacks) never run beside a full one. One PASS or FAIL line per skill; the exit
# status is the number of FAIL lines. Each block runs on the fake model inside the workspace container, so a skill
# that changes state never touches the shared stack.
#
#   scripts/skills_proof.sh            build and start the devcontainer project ops-ai-skills-proof from empty volumes
#   KEEP=1 scripts/skills_proof.sh     leave it running afterwards (it is removed with its volumes otherwise)
#   SKILLS="ops-usecase ops-debug" ... run only these skills, in the same order
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT=${SKILLS_PROOF_PROJECT:-ops-ai-skills-proof}
LOG=${SKILLS_PROOF_LOG:-$ROOT/.logs/skills-proof}
compose() { docker compose -p "$PROJECT" -f "$ROOT/.devcontainer/compose.yaml" "$@"; }
inside() { docker exec -u vscode -w /workspaces/ops-ai -e OPS_INFRA=external "$PROJECT-workspace-1" bash -lc "$1"; }
mkdir -p "$LOG"

echo "== a fresh devcontainer ($PROJECT)"
compose down -v --remove-orphans >/dev/null 2>&1 || true
compose up -d --build >"$LOG/compose.log" 2>&1 || { echo "FAIL  devcontainer: compose up (log $LOG/compose.log)"; exit 1; }
inside 'bash .devcontainer/post-create.sh' >"$LOG/post-create.log" 2>&1 ||
  { echo "FAIL  devcontainer: post-create (log $LOG/post-create.log)"; exit 1; }

names=$(python3 - "$ROOT" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/scripts")
import agent_skills
names = [s.name for s in agent_skills.skills()]
print("\n".join(sorted(names, key=lambda n: (n != "ops-run", n))))
PY
)
[ -z "${SKILLS:-}" ] || names=$(printf '%s\n' $names | grep -xF -f <(printf '%s\n' $SKILLS))
failed=0
for name in $names; do
  block=$(python3 - "$ROOT" "$name" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/scripts")
import agent_skills
print(next(s.proof for s in agent_skills.skills() if s.name == sys.argv[2]))
PY
)
  start=$(date +%s)
  ok=0; inside "set -e; $block" >"$LOG/$name.log" 2>&1 || ok=$?
  inside 'make down >/dev/null 2>&1 || true'
  if [ "$ok" -eq 0 ]; then
    echo "PASS  $name ($(( $(date +%s) - start )) s)"
  else
    failed=$((failed + 1))
    echo "FAIL  $name ($(( $(date +%s) - start )) s): $(tail -1 "$LOG/$name.log" | cut -c1-160) (log $LOG/$name.log)"
  fi
done
[ "${KEEP:-0}" = 1 ] || compose down -v --remove-orphans >/dev/null 2>&1
echo "$failed failed"
exit "$failed"
