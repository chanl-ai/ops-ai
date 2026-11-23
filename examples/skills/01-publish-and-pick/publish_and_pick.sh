#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

SKILL=$(opsai skills apply "$HERE/resources/skill.yaml" --note "First version" --json | jq -r .id)
opsai skills publish "$SKILL" --note "First version"

AGENT=$(opsai agents --json apply "$HERE/resources/agent.yaml" | jq -r .id)
opsai agents add-reference "$AGENT" skill "$SKILL"
opsai agents publish "$AGENT" --note "Uses the return checklist"

opsai chat say --agent "$AGENT" --skill "$SKILL" --input order_number=1182 \
  -m "I want to return my boots."
