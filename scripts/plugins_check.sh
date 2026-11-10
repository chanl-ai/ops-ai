#!/usr/bin/env bash
# Says so when the plugins folder the stack reads differs from what deploy/plugins.json pins, and prints the fix.
# Warns only: a stack with a plugin missing still starts, but that plugin's tools and source kinds (the website
# source, for one) are absent from it with no other sign, which is what this line is for.
#
#   scripts/plugins_check.sh <plugins-dir>
set -uo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
dir=${1:?usage: plugins_check.sh <plugins-dir>}
cd "$root"
out=$(uv run --quiet python deploy/images/bake_plugins.py --check "$dir" 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "plugins: $dir matches deploy/plugins.json"
  exit 0
fi
echo "plugins: WARNING $dir differs from deploy/plugins.json, so some plugins' tools and source kinds will be missing:"
echo "$out" | sed 's/^/  /'
echo "plugins: fix with: make plugins-sync   (then make restart)"
exit 0
