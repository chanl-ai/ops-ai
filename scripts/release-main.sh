#!/bin/sh
# make release-main: moves main to a tagged develop commit with a plain push, so main and develop hold the same commits
# and a release needs no pull request to main and no back-merge (docs/deploy/release.md). Run by
# .github/workflows/release-tag.yml after the tag, and by hand with the same command it prints when the push is refused.
#   REF=<commit>   the develop commit main moves to (default HEAD)
#   REMOTE=<name>  default origin
#   DRY=1          print what would happen and stop
# Never forced: main must be an ancestor of REF. When main's protection refuses the push (the workflow token may not
# push there), this prints the one command the owner runs and exits 3, so a rerun of the job finishes the release.
set -eu
ref=${REF:-HEAD}
remote=${REMOTE:-origin}
sha=$(git rev-parse --verify "$ref^{commit}")
git fetch --quiet "$remote" main
main=$(git rev-parse --verify "refs/remotes/$remote/main^{commit}")
if [ "$main" = "$sha" ]; then echo "release-main: main is already at $sha"; exit 0; fi
if ! git merge-base --is-ancestor "$main" "$sha"; then
  echo "release-main: main at $main is not an ancestor of $sha, so this is not a fast-forward; nothing pushed" >&2
  exit 1
fi
if [ "${DRY:-0}" = 1 ]; then echo "release-main: git push $remote $sha:main (dry run)"; exit 0; fi
if git push --quiet "$remote" "$sha:refs/heads/main"; then
  echo "release-main: main is now at $sha"
  exit 0
fi
echo "release-main: $remote refused the push to main. The owner runs, from a checkout with push rights to main:" >&2
echo "  git push $remote $sha:main" >&2
exit 3
