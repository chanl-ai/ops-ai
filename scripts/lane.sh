#!/usr/bin/env bash
# `make lane BRANCH=x`: a worktree for one lane of work, on a new branch off origin/develop, under ops-ai-worktrees beside
# the main checkout. The main checkout's .venv and node_modules are linked in (a second install costs minutes and
# gigabytes), and the lane is written to <git common dir>/lanes.tsv (time, branch, path), which `git worktree list` cannot
# tell apart from a review or throwaway tree.
#   lane.sh <branch>        create the lane
#   lane.sh --link <dir>    link the main checkout's environments into an existing worktree (verify-staged.sh calls
#                           this when a worktree has no .venv)
#   lane.sh --self-test     both, in a throwaway repository
# The linked .venv's editable installs import the main checkout's sources: a test of a changed package reads the lane's
# code only with PYTHONPATH set to it (the commit hook does this), or after `uv sync` in the lane.
set -euo pipefail
self="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
LINKS=".venv node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules sdk/typescript/node_modules"

main_checkout() { git -C "$1" worktree list --porcelain | sed -n '1s/^worktree //p'; }

link_envs() {
  local dir=$1 main dep
  main=$(main_checkout "$dir")
  [ "$main" != "$(cd "$dir" && pwd -P)" ] || return 0
  for dep in $LINKS; do
    if [ -e "$main/$dep" ] && [ ! -e "$dir/$dep" ] && [ -d "$dir/$(dirname "$dep")" ]; then
      ln -s "$main/$dep" "$dir/$dep"
      echo "lane: linked $dep from $main"
    fi
  done
}

create() {
  local branch=$1 main dir
  main=$(main_checkout .)
  dir="${LANE_DIR:-$(dirname "$main")/ops-ai-worktrees}/${branch//\//-}"
  [ ! -e "$dir" ] || { echo "lane: $dir exists"; exit 2; }
  [ -n "${LANE_BASE:-}" ] || git -C "$main" fetch -q origin develop
  # --no-track: the branch's upstream is its own name on origin once pushed, never develop.
  git -C "$main" worktree add -q --no-track -b "$branch" "$dir" "${LANE_BASE:-origin/develop}"
  link_envs "$dir"
  printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$branch" "$dir" >> "$(git -C "$main" rev-parse --path-format=absolute --git-common-dir)/lanes.tsv"
  echo "lane: $branch at $(git -C "$dir" rev-parse --short HEAD) in $dir"
}

self_test() {
  local tmp fail=0
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' RETURN
  git init -q "$tmp/main"
  git -C "$tmp/main" -c user.name=t -c user.email=t@t commit -q --allow-empty -m a
  mkdir -p "$tmp/main/.venv/bin" "$tmp/main/node_modules"; : > "$tmp/main/.venv/bin/python"
  printf '.venv\nnode_modules\n' > "$tmp/main/.git/info/exclude"
  (cd "$tmp/main" && LANE_BASE=HEAD LANE_DIR="$tmp/wt" bash "$self" fix/console-thing >/dev/null)
  local dir="$tmp/wt/fix-console-thing"
  check() { if ! eval "$2"; then echo "lane self-test FAILED: $1"; fail=1; fi; }
  check "the worktree is on the new branch" '[ "$(git -C "$dir" branch --show-current)" = fix/console-thing ]'
  check "the branch has no upstream, so a push cannot go to develop" '! git -C "$dir" rev-parse -q --verify "@{upstream}" >/dev/null 2>&1'
  check ".venv is linked to the main checkout's" '[ -L "$dir/.venv" ] && [ -e "$dir/.venv/bin/python" ]'
  check "node_modules is linked" '[ -L "$dir/node_modules" ]'
  check "the links are not seen as changes" '[ -z "$(git -C "$dir" status --porcelain)" ]'
  check "the lane is written down" 'grep -q "fix/console-thing	$dir\$" "$tmp/main/.git/lanes.tsv"'
  rm "$dir/.venv"; bash "$self" --link "$dir" >/dev/null
  check "--link restores a missing .venv" '[ -L "$dir/.venv" ]'
  check "an existing lane is refused" '! (cd "$tmp/main" && LANE_BASE=HEAD LANE_DIR="$tmp/wt" bash "$self" fix/console-thing >/dev/null 2>&1)'
  [ "$fail" -eq 0 ] && echo "lane self-test: 8 cases passed"
  return "$fail"
}

case "${1:-}" in
  --self-test) self_test ;;
  --link) link_envs "${2:?usage: lane.sh --link <worktree>}" ;;
  "" | -*) echo "usage: lane.sh <branch> | --link <worktree> | --self-test"; exit 2 ;;
  *) create "$1" ;;
esac
