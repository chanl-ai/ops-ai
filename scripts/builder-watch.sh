#!/usr/bin/env bash
# Every builder worktree at a glance: its branch, the age of its last commit, how many files are uncommitted and whether
# any process runs with that folder as its working directory. A worktree with uncommitted changes, no commit for
# STALL_MIN minutes (default 30) and no process in it is `stalled`: a builder that stopped without saving its work.
#
#   scripts/builder-watch.sh              one table, newest commit first
#   scripts/builder-watch.sh --watch N    every N seconds, only the rows that changed since the last look
#   scripts/builder-watch.sh --self-test  plants a stalled, a busy and a clean worktree and checks each is told apart
#
# WORKTREES=<dir> names another folder of worktrees (default: ops-ai-worktrees beside the main checkout).
# Exit 1 when any worktree is stalled, so a loop can act on it.
set -euo pipefail
# Run from a git hook these point at the committing checkout; every git call below names its own folder.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR

STALL_MIN=${STALL_MIN:-30}

worktrees_dir() {
  if [ -n "${WORKTREES:-}" ]; then echo "$WORKTREES"; return; fi
  local common main
  common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
  main=$(dirname "$common")
  echo "$(dirname "$main")/ops-ai-worktrees"
}

# One line per working directory of a running process (lsof on macOS, /proc on Linux), taken once per snapshot.
process_dirs() {
  if [ -d /proc/self ]; then
    for p in /proc/[0-9]*; do readlink "$p/cwd" 2>/dev/null || true; done
  else
    lsof -a -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true
  fi
}

# name<TAB>branch<TAB>age_min<TAB>dirty<TAB>procs<TAB>state, for each folder under the worktrees dir that is a git worktree.
snapshot() {
  local dir cwds now
  dir=$(worktrees_dir)
  [ -d "$dir" ] || { echo "builder-watch: no folder $dir" >&2; return 2; }
  cwds=$(process_dirs)
  now=$(date +%s)
  local wt name branch last age dirty procs state
  for wt in "$dir"/*/; do
    wt=${wt%/}
    [ -e "$wt/.git" ] || continue
    name=$(basename "$wt")
    branch=$(git -C "$wt" symbolic-ref --short -q HEAD || echo "(detached)")
    last=$(git -C "$wt" log -1 --format=%ct 2>/dev/null || echo "$now")
    age=$(( (now - last) / 60 ))
    dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    procs=$(printf '%s\n' "$cwds" | grep -cE "^$(printf '%s' "$wt" | sed 's/[.[\*^$/]/\\&/g')(/|$)" || true)
    state=ok
    if [ "$dirty" -gt 0 ] && [ "$age" -ge "$STALL_MIN" ] && [ "$procs" -eq 0 ]; then state=stalled
    elif [ "$procs" -gt 0 ]; then state=running
    elif [ "$dirty" -gt 0 ]; then state=dirty; fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$branch" "$age" "$dirty" "$procs" "$state"
  done | sort -t$'\t' -k3,3n
}

show() {
  { printf 'worktree\tbranch\tlast commit (min)\tuncommitted\tprocesses\tstate\n'; cat; } | column -t -s$'\t'
}

case "${1:-}" in
  --self-test)
    root=$(mktemp -d); trap 'kill ${busy_pid:-0} 2>/dev/null || true; rm -rf "$root"' EXIT
    root=$(cd "$root" && pwd -P)
    mk() { git init -q "$root/$1"; git -C "$root/$1" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -q --allow-empty -m init --date="$2"; }
    old=$(date -v-2H +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -d '2 hours ago' +%Y-%m-%dT%H:%M:%S)
    mk stalled "$old"; GIT_COMMITTER_DATE="$old" git -C "$root/stalled" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -q --amend --allow-empty --date="$old" -m init
    echo x > "$root/stalled/work.txt"
    mk busy "$old"; GIT_COMMITTER_DATE="$old" git -C "$root/busy" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -q --amend --allow-empty --date="$old" -m init
    echo x > "$root/busy/work.txt"; (cd "$root/busy" && exec sleep 60) & busy_pid=$!
    mk clean "$old"; GIT_COMMITTER_DATE="$old" git -C "$root/clean" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -q --amend --allow-empty --date="$old" -m init
    mk fresh "now"; echo x > "$root/fresh/work.txt"
    sleep 1
    out=$(WORKTREES="$root" "$0" || true)
    echo "$out"
    got() { printf '%s\n' "$out" | awk -v n="$1" '$1 == n { print $NF }'; }
    if [ "$(got stalled)" = stalled ] && [ "$(got busy)" = running ] && [ "$(got clean)" = ok ] && [ "$(got fresh)" = dirty ]; then
      WORKTREES="$root" "$0" >/dev/null && { echo "builder-watch self-test: FAILED, a stalled worktree exited 0"; exit 1; }
      echo "builder-watch self-test: ok, stalled, running, dirty and clean told apart; exit 1 on a stalled one"
    else
      echo "builder-watch self-test: FAILED"; exit 1
    fi
    ;;
  --watch)
    every=${2:?usage: builder-watch.sh --watch <seconds>}
    prev=$(mktemp); trap 'rm -f "$prev"' EXIT
    while true; do
      now=$(snapshot) || exit 2
      # A row is printed when it is new or its processes, uncommitted count or state moved; the age alone ticking does not count.
      changed=$(printf '%s\n' "$now" | awk -F'\t' -v prev="$prev" 'BEGIN { while ((getline l < prev) > 0) { split(l, a, "\t"); old[a[1]] = a[2] FS a[4] FS a[5] FS a[6] } } !($1 in old) || old[$1] != $2 FS $4 FS $5 FS $6')
      if [ -n "$changed" ]; then date '+%H:%M:%S'; printf '%s\n' "$changed" | show; fi
      printf '%s\n' "$now" > "$prev"
      sleep "$every"
    done
    ;;
  "")
    now=$(snapshot) || exit 2
    printf '%s\n' "$now" | show
    ! printf '%s\n' "$now" | grep -q $'\tstalled$'
    ;;
  *) echo "usage: builder-watch.sh [--watch <seconds> | --self-test]"; exit 2 ;;
esac
