#!/usr/bin/env bash
# Prints `true` when the JSON of the Actions API's workflow runs list on stdin holds a successful run of <sha> (ci.yml asks
# for the merge_group runs of that head sha), else `false`. An error body, `null`, empty or unreadable output all print
# `false`, so a failed lookup runs the tests instead of skipping them. ci.yml sets CI_TESTED from it for a push to develop.
set -uo pipefail
sha=${1:?usage: ci-tested.sh <sha> < runs.json}
n=$(jq -r --arg sha "$sha" '[.workflow_runs[]? | select(.head_sha == $sha and .conclusion == "success")] | length' 2>/dev/null) || n=0
if [ "${n:-0}" -gt 0 ] 2>/dev/null; then echo true; else echo false; fi
