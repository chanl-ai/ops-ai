#!/usr/bin/env bash
# Serves the console from a production build (OPS_CONSOLE_MODE=prod, used on cloud boxes). next dev's HMR websocket
# cannot pass the box's proxy, and the page then reloads itself in a loop.
# NEXT_PUBLIC_* values are fixed at build time, so the build runs under the server's own environment and repeats only
# when the commit, those values or the console's uncommitted files change.
#   scripts/console-prod.sh <port>
set -euo pipefail
# A shell opened by `make restart` on a box lacks the pnpm shim box-setup.sh puts in ~/box/bin.
[ -d "$HOME/box/bin" ] && PATH="$HOME/box/bin:$PATH"
port=${1:?usage: console-prod.sh <port>}
stamp_file=apps/console/.next/.ops-built
stamp=$({ git rev-parse HEAD; env | grep '^NEXT_PUBLIC_' | sort; git status --porcelain -- apps/console packages | sort; } | cksum)
if [ "$(cat "$stamp_file" 2>/dev/null)" != "$stamp" ]; then
  rm -f "$stamp_file"
  pnpm --filter @ops-ai/console exec next build
  echo "$stamp" >"$stamp_file"
fi
exec pnpm --filter @ops-ai/console exec next start -p "$port"
