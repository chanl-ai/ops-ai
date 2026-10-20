#!/bin/sh
# Prunes Docker's build cache after our image builds (the proofs, a local Fly build) once its own (private) space is
# past a cap, so a day of rebuilds cannot fill the Docker disk. The cap is OPS_BUILD_CACHE_CAP in GB (default 8).
# Past it, every cache record no build is using goes (`docker builder prune`; `--max-used-space` prunes nothing on
# Docker 29 here). Records an image still shares free nothing and are not counted; images and volumes are never
# touched.
set -eu
cap=${OPS_BUILD_CACHE_CAP:-8}
private() { docker buildx du 2>/dev/null | sed -n 's/^Private:[[:space:]]*//p'; }
gb() { echo "$1" | awk '{v=$1; u=v; gsub(/[0-9.]/, "", u); gsub(/[A-Za-z]/, "", v); m=(u=="GB")?1:(u=="MB")?0.001:(u=="kB"||u=="KB")?0.000001:(u=="TB")?1000:0; print v*m}'; }
before=$(private)
if awk -v p="$(gb "${before:-0B}")" -v c="$cap" 'BEGIN {exit !(p > c)}'; then
  docker builder prune --force >/dev/null
  echo "build cache (private): $before -> $(private), past the ${cap}GB cap"
else
  echo "build cache (private): $before, under the ${cap}GB cap"
fi
