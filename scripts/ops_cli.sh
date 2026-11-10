#!/usr/bin/env bash
# Runs the `opsai` command for the make/cli.mk targets. The CLI needs only httpx and typing-extensions, so it must not
# depend on the contributor workspace being synced: `uv run --project sdk/python ops` syncs the whole workspace, which
# fails behind a mirror that lacks a dev-only package and, with UV_NO_SYNC=1, leaves no command at all.
#
#   scripts/ops_cli.sh <ops arguments>
#
# Order: OPS_BIN if set; `opsai` on PATH (make install-cli); an `ops` on PATH that reports `ops-ai <version>` (an older
# install; another tool may share the name `ops`); the workspace's own .venv/bin/opsai or .venv/bin/ops.
# Nothing here installs anything.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

ours() { "$1" --version 2>/dev/null | grep -q '^ops-ai '; }

if [ -n "${OPS_BIN:-}" ]; then
  exec "$OPS_BIN" "$@"
elif command -v opsai >/dev/null 2>&1; then
  exec opsai "$@"
elif command -v ops >/dev/null 2>&1 && ours ops; then
  exec ops "$@"
elif [ -x "$ROOT/.venv/bin/opsai" ]; then
  exec "$ROOT/.venv/bin/opsai" "$@"
elif [ -x "$ROOT/.venv/bin/ops" ]; then
  exec "$ROOT/.venv/bin/ops" "$@"
fi

echo "make: the opsai command is not installed; run 'make install-cli' (or 'make install-cli WHEELS=<wheelhouse>' offline)." >&2
exit 127
