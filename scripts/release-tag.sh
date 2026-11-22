#!/bin/sh
# make release-tag: tags the develop commit of a merged release or hotfix pull request `vX.Y.Z` and pushes the tag, so
# every build can say which release it is (What's new). The version comes from the pull request's title,
# `release: X.Y.Z into develop` (`hotfix: X.Y.Z into develop`), which is the commit's subject after a squash and the
# first body line of a merge commit. Run on every push to develop of the public repo (.github/workflows/release-tag.yml)
# and by hand the same way (docs/deploy/release.md).
#   REF=<commit>   the develop commit to tag (default HEAD)
#   REMOTE=<name>  where tags are read from and pushed to (default origin; with no such remote, the tag stays local)
#   VERSION=X.Y.Z  tag this version instead of reading it from the commit's title
#   DRY=1          print the tag it would make and stop
# A commit that is not a release or hotfix merge gets no tag. A rerun on a commit that already has the tag changes
# nothing; a tag that names another commit is an error, never moved. Older installs hold date tags (vYYYY-MM-DD.N);
# nothing here touches them.
set -eu
ref=${REF:-HEAD}
remote=${REMOTE:-origin}
sha=$(git rev-parse --verify "$ref^{commit}")
version=${VERSION:-}
if [ -z "$version" ]; then
  title=$(git log -1 --format=%s "$sha")
  body_title=$(git log -1 --format=%b "$sha" | sed -n '1p')
  for line in "$title" "$body_title"; do
    version=$(printf '%s\n' "$line" | sed -nE 's@^(release|hotfix): ([0-9]+\.[0-9]+\.[0-9]+) into develop( \(#[0-9]+\))?$@\2@p')
    [ -z "$version" ] || break
  done
  if [ -z "$version" ]; then
    echo "release-tag: '$title' is not a release or hotfix merge into develop, so $sha gets no tag"
    exit 0
  fi
fi
case "$version" in *[!0-9.]* | .* | *.) echo "release-tag: '$version' is not X.Y.Z" >&2; exit 1 ;; esac
name="v$version"

has_remote=0
git remote get-url "$remote" >/dev/null 2>&1 && has_remote=1
[ "$has_remote" = 1 ] && git fetch --quiet --tags "$remote" 2>/dev/null || true

if git rev-parse --verify -q "refs/tags/$name" >/dev/null; then
  holder=$(git rev-list -n 1 "$name")
  if [ "$holder" = "$sha" ]; then echo "release-tag: $sha is already $name"; exit 0; fi
  echo "release-tag: $name already names $holder, not $sha; a tag is never moved" >&2
  exit 1
fi
if [ "${DRY:-0}" = 1 ]; then
  echo "release-tag: next is $name for $sha (dry run)"
  exit 0
fi
git tag "$name" "$sha"
if [ "$has_remote" = 0 ]; then
  echo "release-tag: $name on $sha (no remote $remote, kept local)"
  exit 0
fi
if ! git push --quiet "$remote" "refs/tags/$name"; then
  git tag -d "$name" >/dev/null
  echo "release-tag: could not push $name to $remote" >&2
  exit 1
fi
echo "release-tag: $name on $sha, pushed to $remote"
