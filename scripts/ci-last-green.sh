#!/usr/bin/env bash
# Prints the newest commit, other than <current sha>, whose ci run on the branch finished green (ci-ok passed), from the
# JSON of the Actions API's workflow runs list on stdin. Prints nothing when none is in this clone's history; ci.yml then
# plans a full run. A push to develop is planned from that commit, so a merge whose own run never finished (superseded
# or failed) is still checked by the next one.
set -euo pipefail
cur=${1:?usage: ci-last-green.sh <current sha> < runs.json}
jq -r --arg cur "$cur" '[.workflow_runs[] | select(.conclusion == "success" and .head_sha != $cur)] | sort_by(.created_at) | reverse | .[].head_sha' |
  while read -r sha; do
    if git cat-file -e "$sha^{commit}" 2>/dev/null && git merge-base --is-ancestor "$sha" "$cur" 2>/dev/null; then echo "$sha"; break; fi
  done
