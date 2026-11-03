#!/bin/sh
# Installs the repo's git hooks (package.json prepare) into the common git dir, which every worktree shares.
# A hook already there that is not ours is kept as <hook>.local, which ours runs first, so it is never lost.
d=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
mkdir -p "$d/hooks"
for hook in pre-commit commit-msg pre-push; do
  if [ -f "$d/hooks/$hook" ] && ! grep -qE 'ops-ai (hook|changelog gate|push check)|scripts/verify-staged' "$d/hooks/$hook" && [ ! -e "$d/hooks/$hook.local" ]; then
    mv "$d/hooks/$hook" "$d/hooks/$hook.local"
  fi
  cp ".githooks/$hook" "$d/hooks/$hook" && chmod +x "$d/hooks/$hook"
done
