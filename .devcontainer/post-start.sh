#!/bin/bash
# Mailpit listens in a side container. Bind its web port on localhost so forwardPorts 8025 works.
set -euo pipefail
cd /workspaces/ops-ai
bash .devcontainer/own-volumes.sh
command -v socat >/dev/null 2>&1 || exit 0
if pgrep -f 'socat TCP-LISTEN:8025' >/dev/null 2>&1; then
  exit 0
fi
socat TCP-LISTEN:8025,bind=127.0.0.1,fork,reuseaddr TCP:mailpit:8025 &
