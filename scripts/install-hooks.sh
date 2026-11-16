#!/bin/sh
# Installs the repo's git hooks (package.json prepare) into the common git dir, which every worktree shares.
# A hook already there that is not ours is kept as <hook>.local, which ours runs first, so it is never lost.
# What is installed is a launcher for the checkout's own .githooks/<hook>, not a copy: a copy kept running whatever the
# hook was at the last install, so a fixed hook did not run on the branch that fixed it, and every worktree runs the
# hook of the branch it has out.
d=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
mkdir -p "$d/hooks"
for hook in pre-commit commit-msg pre-push; do
  if [ -f "$d/hooks/$hook" ] && ! grep -qE 'ops-ai (hook|changelog gate|push check)|scripts/verify-staged' "$d/hooks/$hook" && [ ! -e "$d/hooks/$hook.local" ]; then
    mv "$d/hooks/$hook" "$d/hooks/$hook.local"
  fi
  cat > "$d/hooks/$hook" <<EOF
#!/bin/sh
# ops-ai hook launcher (scripts/install-hooks.sh): runs this checkout's own .githooks/$hook.
hook="\$(git rev-parse --show-toplevel)/.githooks/$hook"
[ -f "\$hook" ] || exit 0
exec sh "\$hook" "\$@"
EOF
  chmod +x "$d/hooks/$hook"
done
