#!/usr/bin/env bash
# Commits the given paths, and only them, from the shared tree: HEAD plus each path as it is in the working tree (a
# path that is gone is removed), built in a private index so nobody else's staged or unfinished work comes along.
# Runs both repository hooks on that index, pre-commit and then commit-msg, which a private-index commit through
# commit-tree skips: four feat commits reached HEAD with no changelog entry that way and blocked a release on 10-30.
# The commit lands only if HEAD has not moved since it was read (a compare-and-swap update-ref); otherwise rerun.
#   scripts/commit-paths.sh <message-file> <path>...
set -euo pipefail
[ $# -ge 2 ] || { echo "usage: scripts/commit-paths.sh <message-file> <path>..." >&2; exit 2; }
msg_in=$1; shift
[ -f "$msg_in" ] || { echo "commit-paths: no message file $msg_in" >&2; exit 2; }
root=$(git rev-parse --show-toplevel)
git_dir=$(git rev-parse --absolute-git-dir)
work=$(mktemp -d "${TMPDIR:-/tmp}/commit-paths.XXXXXX")
trap 'rm -rf "$work"' EXIT
base=$(git -C "$root" rev-parse HEAD)
export GIT_INDEX_FILE="$work/index"
git -C "$root" read-tree "$base"
for p in "$@"; do
  # -A stages a deletion too; a path that matches nothing at all is a typo, not an empty commit.
  git -C "$root" add -A -- "$p"
done
if git -C "$root" diff --cached --quiet "$base"; then echo "commit-paths: nothing to commit in $*" >&2; exit 1; fi
git -C "$root" diff --cached --stat "$base" | tail -1
# The hooks are the tracked ones, so a commit is checked by the gate in the tree, not by whatever was installed once.
"$root/.githooks/pre-commit"
cp "$msg_in" "$work/message"
(cd "$root" && "$root/.githooks/commit-msg" "$work/message")
tree=$(git -C "$root" write-tree)
unset GIT_INDEX_FILE
commit=$(git -C "$root" commit-tree "$tree" -p "$base" -F "$work/message")
git -C "$root" update-ref -m "commit-paths: $(head -1 "$work/message")" HEAD "$commit" "$base" \
  || { echo "commit-paths: HEAD moved since $base; nothing was committed, run it again" >&2; exit 1; }
# The shared index now matches the new HEAD for these paths, so they do not show as staged changes afterwards.
git -C "$root" reset -q "$commit" -- "$@" 2>/dev/null || true
if [ -x "$git_dir/hooks/post-commit" ]; then (cd "$root" && "$git_dir/hooks/post-commit") || true; fi
echo "committed $(git -C "$root" rev-parse --short "$commit")"
