#!/bin/sh
# Installs the repo's git hooks (package.json prepare). A commit-msg hook that is not ours, such as the one
# `codeloop init --hooks` writes, is kept as commit-msg.codeloop and run by ours, never overwritten.
d=$(git rev-parse --git-dir 2>/dev/null) || exit 0
mkdir -p "$d/hooks"
cp .githooks/pre-commit "$d/hooks/pre-commit" && chmod +x "$d/hooks/pre-commit"
if [ -f "$d/hooks/commit-msg" ] && ! grep -q 'ops-ai changelog gate' "$d/hooks/commit-msg"; then
  mv "$d/hooks/commit-msg" "$d/hooks/commit-msg.codeloop"
fi
cp .githooks/commit-msg "$d/hooks/commit-msg" && chmod +x "$d/hooks/commit-msg"
