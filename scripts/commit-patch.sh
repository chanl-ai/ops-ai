#!/usr/bin/env bash
# Commits a patch, and only it, onto HEAD: for a shared file (a README row, uv.lock, openapi.json, the allowlist) that
# also holds other builders' unfinished lines, so `make commit FILES=…` would take their lines too. The patch is
# applied to HEAD in a private index, both repository hooks run on it, and the commit lands only if HEAD has not moved
# (a compare-and-swap). The working tree is never written: your lines are already in it, and so are everyone else's.
#   scripts/commit-patch.sh <message-file> <patch-file>
# Make the patch from your own hunks: `make my-hunks FILE=docs/usecases/README.md > mine.patch`, delete the hunks that
# are not yours, then `make commit-hunks PATCH=mine.patch MSG='…' CARD=c-NNN`.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: scripts/commit-patch.sh <message-file> <patch-file>" >&2; exit 2; }
msg_in=$1; patch=$2
[ -f "$msg_in" ] || { echo "commit-patch: no message file $msg_in" >&2; exit 2; }
[ -s "$patch" ] || { echo "commit-patch: the patch $patch is empty or missing" >&2; exit 2; }
patch=$(cd "$(dirname "$patch")" && pwd)/$(basename "$patch")
root=$(git rev-parse --show-toplevel)
git_dir=$(git rev-parse --absolute-git-dir)
work=$(mktemp -d "${TMPDIR:-/tmp}/commit-patch.XXXXXX")
trap 'rm -rf "$work"' EXIT
base=$(git -C "$root" rev-parse HEAD)
export GIT_INDEX_FILE="$work/index"
git -C "$root" read-tree "$base"
git -C "$root" apply --cached --whitespace=nowarn "$patch" \
  || { echo "commit-patch: the patch does not apply to HEAD; make it again from HEAD (make my-hunks)" >&2; exit 1; }
if git -C "$root" diff --cached --quiet "$base"; then echo "commit-patch: the patch changes nothing" >&2; exit 1; fi
git -C "$root" diff --cached --stat "$base" | tail -1
"$root/.githooks/pre-commit"
cp "$msg_in" "$work/message"
(cd "$root" && "$root/.githooks/commit-msg" "$work/message")
tree=$(git -C "$root" write-tree)
unset GIT_INDEX_FILE
commit=$(git -C "$root" commit-tree "$tree" -p "$base" -F "$work/message")
git -C "$root" update-ref -m "commit-patch: $(head -1 "$work/message")" HEAD "$commit" "$base" \
  || { echo "commit-patch: HEAD moved since $base; nothing was committed, run it again" >&2; exit 1; }
# The shared index for these paths follows the new HEAD, so the committed lines no longer show as staged.
mapfile -t paths < <(git -C "$root" diff --name-only "$base" "$commit")
git -C "$root" reset -q "$commit" -- "${paths[@]}" 2>/dev/null || true
if [ -x "$git_dir/hooks/post-commit" ]; then (cd "$root" && "$git_dir/hooks/post-commit") || true; fi
echo "committed $(git -C "$root" rev-parse --short "$commit")"
