#!/bin/sh
# make release-tag: tags a merged commit `vYYYY-MM-DD.N` (UTC date; N counts that day's tags, from 1) and pushes the tag,
# so every build can say which release it is (What's new, c-510). Run on every push to main of the public repo
# (.github/workflows/release-tag.yml) and by hand the same way.
#   REF=<commit>   the commit to tag (default HEAD)
#   REMOTE=<name>  where tags are read from and pushed to (default origin; with no such remote, the tag stays local)
#   DRY=1          print the tag it would make and stop
# A commit that already has a date tag keeps it, so a rerun of the same merge makes no second tag. Two merges tagging at
# once: the second push is refused, and the next number is tried, three times.
set -eu
ref=${REF:-HEAD}
remote=${REMOTE:-origin}
sha=$(git rev-parse --verify "$ref^{commit}")
day=$(date -u +%Y-%m-%d)
has_remote=0
git remote get-url "$remote" >/dev/null 2>&1 && has_remote=1

existing=$(git tag --points-at "$sha" --list 'v[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].*' | head -1)
if [ -n "$existing" ]; then
  echo "release-tag: $sha is already $existing"
  exit 0
fi

for attempt in 1 2 3; do
  [ "$has_remote" = 1 ] && git fetch --quiet --tags "$remote" 2>/dev/null || true
  last=$(git tag --list "v$day.*" | sed "s/^v$day\.//" | grep -E '^[0-9]+$' | sort -n | tail -1)
  name="v$day.$(( ${last:-0} + 1 ))"
  if [ "${DRY:-0}" = 1 ]; then
    echo "release-tag: next is $name for $sha (dry run)"
    exit 0
  fi
  git tag "$name" "$sha"
  if [ "$has_remote" = 0 ]; then
    echo "release-tag: $name on $sha (no remote $remote, kept local)"
    exit 0
  fi
  if git push --quiet "$remote" "refs/tags/$name"; then
    echo "release-tag: $name on $sha, pushed to $remote"
    exit 0
  fi
  git tag -d "$name" >/dev/null
  echo "release-tag: $name was taken, trying the next number"
done
echo "release-tag: no free number after three tries" >&2
exit 1
