#!/usr/bin/env bash
# Runs the `ops` command for the make/cli.mk targets. The CLI needs only httpx and typing-extensions, so it must not
# depend on the contributor workspace being synced: `uv run --project sdk/python ops` syncs the whole workspace, which
# fails behind a mirror that lacks a dev-only package and, with UV_NO_SYNC=1, leaves no `ops` at all.
#
#   scripts/ops_cli.sh <ops arguments>
#
# Order: OPS_BIN if set, an `ops` on PATH (make install-cli), the workspace's own .venv/bin/ops (make install).
# Nothing here installs anything.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if [ -n "${OPS_BIN:-}" ]; then
  exec "$OPS_BIN" "$@"
elif command -v ops >/dev/null 2>&1; then
  exec ops "$@"
elif [ -x "$ROOT/.venv/bin/ops" ]; then
  exec "$ROOT/.venv/bin/ops" "$@"
fi

echo "make: the ops command is not installed; run 'make install-cli' (or 'make install-cli WHEELS=<wheelhouse>' offline)." >&2
exit 127
