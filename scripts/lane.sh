#!/usr/bin/env bash
# Lanes: long-lived git worktrees of this repo, one per area of work, beside the main checkout.
#
#   scripts/lane.sh add <name> <number> [base]   make ../ops-ai-lane-<name> on a fresh branch from origin/main (or base)
#   scripts/lane.sh list                  each lane: number, branch, last commit, its PR, whether its stack is up
#   scripts/lane.sh next <branch> [base]  in a lane: start the next card on <branch> from origin/main (or <base>)
#   scripts/lane.sh remove <name>         remove a lane whose work is pushed; drops its stack and database
#
# Each lane shares this repo's .git (no clone) and the pnpm and uv caches (installs take seconds). Its .lane file names
# its number; make/env.mk reads it, so every make target run in the lane (up, api, usecase-test, restart) acts on the
# lane's own stack and database, never the main checkout's. One card at a time per lane: `next` refuses while the lane
# has uncommitted work, or commits on its branch that are not pushed.
set -euo pipefail

common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
main=$(dirname "$common")
lane_dir() { printf '%s-lane-%s' "$main" "$1"; }
die() { echo "lane: $*" >&2; exit 1; }

clean_and_pushed() {
  local dir=$1 branch upstream
  [ -z "$(git -C "$dir" status --porcelain)" ] || die "$dir has uncommitted work; commit it to its branch first"
  branch=$(git -C "$dir" branch --show-current)
  upstream=$(git -C "$dir" rev-parse --abbrev-ref "$branch@{upstream}" 2>/dev/null || true)
  if [ -z "$upstream" ]; then
    [ -z "$(git -C "$dir" log --oneline origin/main.."$branch" 2>/dev/null)" ] || die "$branch has commits that are not pushed; git push -u origin HEAD"
  else
    [ -z "$(git -C "$dir" log --oneline "$upstream..$branch")" ] || die "$branch has commits that are not pushed; git push"
  fi
}

case "${1:-}" in
  add)
    name=${2:?usage: lane.sh add <name> <number>}; number=${3:?usage: lane.sh add <name> <number 1-5>}; base=${4:-origin/main}
    [[ $number =~ ^[1-5]$ ]] || die "number is 1 to 5 (ports +number×1000)"
    dir=$(lane_dir "$name")
    [ ! -e "$dir" ] || die "$dir exists"
    for other in "$main"-lane-*; do
      [ -f "$other/.lane" ] && grep -qx "number=$number" "$other/.lane" && die "lane number $number is taken by $other"
    done
    git -C "$main" fetch -q origin
    [[ $base == origin/* ]] || base="origin/$base"
    git -C "$main" worktree add -q -b "lane/$name" "$dir" "$base"
    printf 'name=%s\nnumber=%s\n' "$name" "$number" > "$dir/.lane"
    (cd "$dir" && bash scripts/link-private.sh >/dev/null)
    for f in .env .devcontainer/.env.local apps/console/.env.local; do
      [ -f "$main/$f" ] && [ ! -e "$dir/$f" ] && cp -p "$main/$f" "$dir/$f"
    done
    (cd "$dir" && pnpm install --frozen-lockfile --silent && uv sync --all-packages --quiet)
    echo "lane: $dir ready on branch lane/$name, ports +${number}000; next: cd $dir && make lane-next BRANCH=feat/<scope>-<change>"
    ;;
  list)
    printf '%-10s %-3s %-44s %-9s %s\n' LANE NO BRANCH STACK "LAST COMMIT"
    printf '%-10s %-3s %-44s %-9s %s\n' main 0 "$(git -C "$main" branch --show-current)" \
      "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3016/ | sed 's/^200$/up/;s/^000$/down/')" \
      "$(git -C "$main" log -1 --format='%h %cr %s' | cut -c1-60)"
    for dir in "$main"-lane-*; do
      [ -f "$dir/.lane" ] || continue
      name=$(sed -n 's/^name=//p' "$dir/.lane"); number=$(sed -n 's/^number=//p' "$dir/.lane")
      branch=$(git -C "$dir" branch --show-current)
      up=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$((3016 + number * 1000))/" | sed 's/^200$/up/;s/^000$/down/')
      pr=$(gh pr view "$branch" --json number -q '"#\(.number)"' 2>/dev/null || true)
      printf '%-10s %-3s %-44s %-9s %s %s\n' "$name" "$number" "$branch" "$up" \
        "$(git -C "$dir" log -1 --format='%h %cr %s' | cut -c1-60)" "$pr"
    done
    ;;
  next)
    branch=${2:?usage: lane.sh next <feat/scope-change> [base branch]}; base=${3:-origin/main}
    dir=$(git rev-parse --show-toplevel)
    [ -f "$dir/.lane" ] || die "run this inside a lane (a folder made by lane.sh add)"
    clean_and_pushed "$dir"
    git -C "$dir" fetch -q origin
    [[ $base == origin/* ]] || base="origin/$base"
    git -C "$dir" switch -q -c "$branch" "$base"
    (cd "$dir" && pnpm install --frozen-lockfile --silent && uv sync --all-packages --quiet)
    # The lane's own database follows its branch: migrate forward; a branch behind the last one's migrations reseeds.
    (cd "$dir" && { make -s migrate || make -s reset-db CONFIRM=yes; })
    echo "lane: $(sed -n 's/^name=//p' "$dir/.lane") now on $branch from $base; database migrated"
    ;;
  remove)
    name=${2:?usage: lane.sh remove <name>}; dir=$(lane_dir "$name")
    [ -d "$dir" ] || die "no lane $dir"
    clean_and_pushed "$dir"
    (cd "$dir" && make -s down >/dev/null 2>&1 || true; make -s db-down >/dev/null 2>&1 || true)
    git -C "$main" worktree remove "$dir"
    echo "lane: removed $dir (its branches stay on origin)"
    ;;
  *)
    sed -n '2,13p' "$0"; exit 2 ;;
esac
