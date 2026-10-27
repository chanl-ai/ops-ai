#!/bin/bash
# Installs workspace dependencies. Provider keys stay in .devcontainer/.env.local (gitignored).
set -euo pipefail
cd /workspaces/ops-ai
bash .devcontainer/own-volumes.sh
if [ ! -f .devcontainer/.env.local ]; then
  cp .devcontainer/.env.local.example .devcontainer/.env.local
fi
make install
if [ "${OPS_PLAYWRIGHT:-}" = 1 ]; then
  pnpm --filter @ops-ai/usecase-runner exec playwright install --with-deps chromium
fi
