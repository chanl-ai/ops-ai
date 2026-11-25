#!/usr/bin/env bash
# `make merge-ready PR=N`: run the CI plan's jobs locally on the pull request's head (make ci-local BASE=origin/develop)
# and, when every job is green, hand the pull request to the merge queue (`gh pr merge N --merge`).
# While develop has no merge queue rule, that command would merge at once, so this stops after the green run and says so.
set -euo pipefail
pr=${1:?usage: merge-ready.sh <pull request number>}
cd "$(git rev-parse --show-toplevel)"
base=${BASE:-origin/develop}
git fetch -q origin develop "+refs/pull/$pr/head:refs/remotes/origin/pr/$pr"
dir="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir | sed 's|/\.git$||')")/ops-ai-worktrees/merge-ready-$pr"
[ ! -e "$dir" ] || { echo "merge-ready: $dir exists; a run for #$pr may be going"; exit 2; }
git worktree add -q --detach "$dir" "origin/pr/$pr"
trap 'git worktree remove --force "$dir" >/dev/null 2>&1 || true' EXIT
echo "merge-ready: #$pr at $(git -C "$dir" rev-parse --short HEAD), jobs run in $dir"
make -C "$dir" ci-local BASE="$base"
queue=$(gh api "repos/{owner}/{repo}/rules/branches/develop" --jq '[.[] | select(.type == "merge_queue")] | length' 2>/dev/null || echo 0)
if [ "$queue" -gt 0 ]; then
  gh pr merge "$pr" --merge
  echo "merge-ready: #$pr is in the merge queue"
else
  echo "merge-ready: every job is green; develop has no merge queue rule yet, so #$pr was not merged"
fi
