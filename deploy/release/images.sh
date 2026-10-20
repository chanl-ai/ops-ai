#!/bin/sh
# Builds every Ops AI image from one commit (`git archive`, so uncommitted files never reach an image), for the
# platforms given, and loads them here or pushes them. One place for the image names, targets and OCI labels: the
# release package (package.sh), the release workflow (.github/workflows/release-images.yml) and install.sh --build.
#   sh deploy/release/images.sh <ref> <version> [--platforms linux/amd64,linux/arm64] [--push] [--latest]
# Images are <IMAGE_PREFIX>/<target>:<version> (IMAGE_PREFIX default ghcr.io/chanl-ai/ops-ai); --latest adds :latest.
# Without --push they are loaded into this machine's Docker (one platform, unless its image store holds several).
set -eu
# Files keep their checked-in modes in the image: a caller's umask 077 (install.sh) would leave them unreadable to the
# images' non-root user.
umask 022
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
REF=${1:?usage: images.sh <ref> <version> [--platforms p[,p]] [--push] [--latest]}
VERSION=${2:?usage: images.sh <ref> <version>}
shift 2
PLATFORMS=linux/$(docker info --format '{{.Architecture}}' | sed 's/x86_64/amd64/; s/aarch64/arm64/')
OUTPUT=--load
LATEST=0
while [ $# -gt 0 ]; do
  case $1 in
    --platforms) PLATFORMS=$2; shift ;;
    --push) OUTPUT=--push ;;
    --latest) LATEST=1 ;;
    *) echo "images.sh: unknown option $1"; exit 2 ;;
  esac
  shift
done
PREFIX=${IMAGE_PREFIX:-ghcr.io/chanl-ai/ops-ai}
# db-scripts holds the DBA's PostgreSQL scripts for the commit (deploy/fly/Dockerfile); install.sh --db-mode dba copies them out.
TARGETS=${TARGETS:-platform agents tools models kb files documents opa proxy console db-scripts}
SOURCE=https://github.com/chanl-ai/ops-ai
SHA=$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
git -C "$ROOT" archive "$SHA" | tar -x -C "$WORK"

for t in $TARGETS; do
  tags="-t $PREFIX/$t:$VERSION"
  [ "$LATEST" = 1 ] && tags="$tags -t $PREFIX/$t:latest"
  # A pushed multi-platform image is an index; GHCR reads the repository link and description from its annotations.
  notes=""
  [ "$OUTPUT" = --push ] && notes="--annotation index:org.opencontainers.image.source=$SOURCE --annotation index:org.opencontainers.image.licenses=Apache-2.0"
  echo "images: $PREFIX/$t:$VERSION ($PLATFORMS, ${OUTPUT#--})"
  # shellcheck disable=SC2086
  docker buildx build -q --platform "$PLATFORMS" $OUTPUT -f "$WORK/deploy/fly/Dockerfile" --target "$t" \
    --build-arg OPS_COMMIT="$SHA" \
    --label org.opencontainers.image.title="Ops AI $t" --label org.opencontainers.image.vendor="Elemente" \
    --label org.opencontainers.image.version="$VERSION" --label org.opencontainers.image.revision="$SHA" \
    --label org.opencontainers.image.source="$SOURCE" --label org.opencontainers.image.licenses=Apache-2.0 \
    --label org.opencontainers.image.description="Ops AI $t, version $VERSION" \
    $notes $tags "$WORK" >/dev/null
done
