#!/usr/bin/env bash
# Sourced by commit-paths.sh and commit-patch.sh. One repository-wide lock around read HEAD -> hooks -> update-ref, so
# builders sharing a tree queue and each lands on its first run instead of losing the compare-and-swap on HEAD.
# An atomic mkdir under the common git dir (every worktree shares it; macOS has no flock) holds the owner's pid.
# A waiter takes over a lock whose owner is dead and gives up after COMMIT_LOCK_TIMEOUT seconds (default 1800).
# The compare-and-swap in the callers stays: someone may still commit with plain git, which does not take this lock.
commit_lock_dir=""

commit_lock_acquire() {
  local tag=$1 common timeout=${COMMIT_LOCK_TIMEOUT:-1800} poll=${COMMIT_LOCK_POLL:-1}
  local waited=0 announced="" owner=0 nopid=0
  common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
  local dir="$common/commit.lock"
  while ! mkdir "$dir" 2>/dev/null; do
    owner=$(cat "$dir/pid" 2>/dev/null || true)
    if [ -z "$owner" ]; then
      # The holder has made the directory and not yet written its pid; only a long gap means it died in between.
      nopid=$((nopid + 1))
      [ "$nopid" -le 10 ] || owner=0
    else
      nopid=0
    fi
    if [ "$owner" = 0 ] || { [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; }; then
      # rename is atomic, so of several waiters that see the same dead owner only one removes the lock.
      if mv "$dir" "$dir.stale.$$" 2>/dev/null; then
        echo "$tag: took over the commit lock of dead process $owner" >&2
        rm -rf "$dir.stale.$$"
      fi
      nopid=0
      continue
    fi
    if [ -z "$announced" ]; then
      echo "$tag: waiting for the commit lock held by process ${owner:-?}; commits here run one at a time" >&2
      announced=1
    fi
    if [ "$waited" -ge "$timeout" ]; then
      echo "$tag: gave up after ${timeout}s waiting for the commit lock held by process ${owner:-?}; if it is stuck, kill it or remove $dir" >&2
      return 1
    fi
    sleep "$poll"
    waited=$((waited + poll))
  done
  echo $$ > "$dir/pid"
  commit_lock_dir=$dir
}

commit_lock_release() {
  [ -n "$commit_lock_dir" ] || return 0
  if [ "$(cat "$commit_lock_dir/pid" 2>/dev/null || true)" = "$$" ]; then rm -rf "$commit_lock_dir"; fi
  commit_lock_dir=""
}
