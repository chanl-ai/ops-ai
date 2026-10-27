#!/bin/bash
# Docker creates named volumes owned by root; the vscode user must own every one before it installs or writes into it.
# The one list of the workspace's own volumes, kept in step with compose.yaml's workspace mounts.
set -euo pipefail
cd /workspaces/ops-ai
sudo chown -R "$(id -u):$(id -g)" node_modules .venv .run .logs .data \
  apps/*/node_modules apps/*/.next packages/*/node_modules sdk/typescript/node_modules
