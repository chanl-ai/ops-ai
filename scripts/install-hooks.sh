#!/bin/sh
# Installs the repo's git hooks (package.json prepare). A commit-msg or pre-push hook that is not ours, such as the ones
# `codeloop init --hooks` writes, is kept as <hook>.codeloop and run by ours, never overwritten.
# Hooks live in the common git dir, so the main checkout and every lane worktree share them.
d=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
mkdir -p "$d/hooks"
cp .githooks/pre-commit "$d/hooks/pre-commit" && chmod +x "$d/hooks/pre-commit"
if [ -f "$d/hooks/commit-msg" ] && ! grep -q 'ops-ai changelog gate' "$d/hooks/commit-msg"; then
  mv "$d/hooks/commit-msg" "$d/hooks/commit-msg.codeloop"
fi
cp .githooks/commit-msg "$d/hooks/commit-msg" && chmod +x "$d/hooks/commit-msg"
if [ -f "$d/hooks/pre-push" ] && ! grep -q 'ops-ai push check' "$d/hooks/pre-push"; then
  mv "$d/hooks/pre-push" "$d/hooks/pre-push.codeloop"
fi
cp .githooks/pre-push "$d/hooks/pre-push" && chmod +x "$d/hooks/pre-push"
