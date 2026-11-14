#!/usr/bin/env bash
# Says so when the plugins folder the stack reads differs from what deploy/plugins.json pins (outside plugins only;
# the built-in ones load from builtin-plugins/ with no step), and names each folder there that replaces a built-in
# plugin, which then runs that copy instead. Warns only: a stack with a plugin missing still starts, but that plugin's
# tools and source kinds are absent from it with no other sign, which is what these lines are for.
#
#   scripts/plugins_check.sh <plugins-dir>
set -uo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
dir=${1:?usage: plugins_check.sh <plugins-dir>}
cd "$root"
for f in "$dir"/*/; do
  [ -d "$f" ] || continue
  pkg=$(basename "$f")
  [ -f "$f/plugin.yaml" ] || { for m in "$f"src/*/plugin.yaml; do [ -f "$m" ] && pkg=$(basename "$(dirname "$m")"); done; }
  if [ -d "builtin-plugins/$pkg" ]; then
    echo "plugins: $f replaces the built-in $pkg; remove it (or make plugins-sync) to run the built-in one"
  fi
done
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
