#!/usr/bin/env bash
# Link the private half of Ops AI into this checkout: the board (.codeloop) and the agent setup that is not public
# (.claude commands, agents, skills, settings; .cursor). The private repo is cloned once, at the main checkout's
# .private/; a lane worktree links to that same clone, so there is one board and one copy of the private skills.
#
#   scripts/link-private.sh            link into this checkout (run again any time; it only adds missing links)
#
# Every link is listed in the shared .git/info/exclude, never in .gitignore: the public repo does not learn the names of
# private skills. Without .private the checkout is a plain public one and this script says so and exits 0.
set -euo pipefail

here=$(git rev-parse --show-toplevel)
common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
main=$(dirname "$common")
private="$main/.private"
exclude="$common/info/exclude"

if [ ! -d "$private/.git" ]; then
  echo "link-private: no private repo at $private; this is a public checkout (clone chanl-ai/ops-ai-private there to add it)"
  exit 0
fi

mkdir -p "$(dirname "$exclude")" && touch "$exclude"
add_exclude() { grep -qxF "$1" "$exclude" || printf '%s\n' "$1" >> "$exclude"; }

# link <target> <path in this checkout>: makes the link unless the path is tracked or already a real file.
link() {
  local target=$1 path=$2
  if git -C "$here" ls-files --error-unmatch "$path" >/dev/null 2>&1; then return; fi
  if [ -L "$here/$path" ]; then add_exclude "/$path"; return; fi
  if [ -e "$here/$path" ]; then echo "link-private: $path exists and is not a link; left alone"; return; fi
  mkdir -p "$(dirname "$here/$path")"
  ln -s "$target" "$here/$path"
  add_exclude "/$path"
  echo "link-private: $path -> $target"
}

[ "$here" = "$main" ] || link "$private" .private
link "$private/codeloop" .codeloop
link "$private/agents/cursor" .cursor
for entry in "$private"/agents/claude/*; do
  name=$(basename "$entry")
  if [ "$name" = skills ]; then
    for skill in "$entry"/*; do link "$skill" ".claude/skills/$(basename "$skill")"; done
  else
    link "$entry" ".claude/$name"
  fi
done
