#!/bin/sh
# make release-tag: tags the develop commit of a merged release or hotfix pull request `vX.Y.Z` and pushes the tag, so
# every build can say which release it is (What's new). The version comes from the pull request's title,
# `release: X.Y.Z into develop` (`hotfix: X.Y.Z into develop`), which is the commit's subject after a squash and the
# first body line of a merge commit. Run by .github/workflows/release-tag.yml after a develop commit's staging deploy and walk passed
# and by hand the same way (docs/deploy/release.md).
#   REF=<commit>   the develop commit to tag (default HEAD)
#   REMOTE=<name>  where tags are read from and pushed to (default origin; with no such remote, the tag stays local)
#   VERSION=X.Y.Z  tag this version instead of reading it from the commit's title
#   DRY=1          print the tag it would make and stop
#   BUMP=auto      a commit that is no release merge is tagged by its type instead: `feat` raises the minor version of the
#                  highest vX.Y.Z tag, `fix` or `perf` its patch, any other type gets no tag (the merge-queue flow, where one
#                  feature is one release and no release pull request exists)
#   WALK_PASSED=1  the staging walk of this commit passed; a run on GitHub (GITHUB_ACTIONS) refuses to push a tag without it
# A commit that is not a release or hotfix merge gets no tag. A rerun on a commit that already has the tag changes
# nothing; a tag that names another commit is an error, never moved. Older installs hold date tags (vYYYY-MM-DD.N);
# nothing here touches them.
set -eu
ref=${REF:-HEAD}
remote=${REMOTE:-origin}
sha=$(git rev-parse --verify "$ref^{commit}")
version=${VERSION:-}
if [ -z "$version" ]; then
  # A rerun, or a run by branch name after one by sha, must not raise a second version on the same commit.
  git fetch --quiet --tags "$remote" 2>/dev/null || true
  held=$(git tag --points-at "$sha" --list 'v[0-9]*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)
  if [ -n "$held" ]; then echo "release-tag: $sha is already $held"; exit 0; fi
  title=$(git log -1 --format=%s "$sha")
  body_title=$(git log -1 --format=%b "$sha" | sed -n '1p')
  for line in "$title" "$body_title"; do
    version=$(printf '%s\n' "$line" | sed -nE 's@^(release|hotfix): ([0-9]+\.[0-9]+\.[0-9]+) into develop( \(#[0-9]+\))?$@\2@p')
    [ -z "$version" ] || break
  done
  if [ -z "$version" ] && [ "${BUMP:-}" = auto ]; then
    last=$(git tag --list 'v[0-9]*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
    last=${last:-0.0.0}
    major=${last%%.*}; rest=${last#*.}; minor=${rest%%.*}; patch=${rest#*.}
    # A queue merge commit's subject is "Merge pull request #N from ...": its type is the pull request title, which is the
    # first body line; a squash commit carries the title as its subject.
    typed=$title
    case "$title" in "Merge pull request"*) typed=$body_title ;; esac
    case "$typed" in
      feat\(*\)!:* | feat!:* | feat:* | feat\(*\):*) version="$major.$((minor + 1)).0" ;;
      fix:* | fix\(*\):* | perf:* | perf\(*\):*) version="$major.$minor.$((patch + 1))" ;;
    esac
  fi
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
if [ -n "${GITHUB_ACTIONS:-}" ] && [ "${WALK_PASSED:-}" != 1 ]; then
  echo "release-tag: refused, no passed staging walk is recorded for $sha (WALK_PASSED=1)" >&2
  exit 1
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
