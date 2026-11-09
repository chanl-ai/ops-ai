#!/usr/bin/env bash
# Puts the plugins deploy/plugins.json pins into the plugins folder the stack reads, the way the image bakes them, so a
# laptop, a box and an image run the same plugins.
#
#   scripts/plugins_sync.sh <plugins-dir>
#   PLUGINS_DEV=../ops-ai-plugins scripts/plugins_sync.sh <plugins-dir>   link a working copy's plugin folders instead
#
# A plugins folder holding plugins this script did not put there (hand copies) is moved to <plugins-dir>.bak-<date>/
# first and never deleted. What an earlier run put there is replaced in place, marked by .plugins-sync. The README that
# git tracks in the folder stays where it is.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
dir=${1:?usage: plugins_sync.sh <plugins-dir>}
mkdir -p "$dir"
dir=$(cd "$dir" && pwd)

existing=()
while IFS= read -r f; do existing+=("$f"); done < <(find "$dir" -mindepth 1 -maxdepth 1 ! -name README.md ! -name '.*' | sort)
if [ "${#existing[@]}" -gt 0 ] && [ -e "$dir/.plugins-sync" ]; then
  for f in "${existing[@]}"; do rm -rf "$f"; done
elif [ "${#existing[@]}" -gt 0 ]; then
  backup="$dir.bak-$(date +%Y-%m-%d)"
  n=1
  while [ -e "$backup" ]; do n=$((n + 1)); backup="$dir.bak-$(date +%Y-%m-%d)-$n"; done
  mkdir -p "$backup"
  for f in "${existing[@]}"; do mv "$f" "$backup/"; done
  echo "plugins: moved ${#existing[@]} existing entries to $backup"
fi

if [ -n "${PLUGINS_DEV:-}" ]; then
  # A working copy's plugin folders, linked so an edit shows after the next restart. Explicit only: the default is the
  # pinned commit.
  src=$(cd "$PLUGINS_DEV/plugins" 2>/dev/null && pwd) || { echo "plugins: PLUGINS_DEV=$PLUGINS_DEV has no plugins/ folder" >&2; exit 1; }
  for p in "$src"/*/; do
    ln -s "${p%/}" "$dir/$(basename "$p")"
    echo "linked $(basename "$p") -> ${p%/}"
  done
  date >"$dir/.plugins-sync"
  exit 0
fi

cd "$root"
uv run python deploy/images/bake_plugins.py --into "$dir"
date >"$dir/.plugins-sync"
