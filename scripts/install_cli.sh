#!/usr/bin/env bash
# Installs the `ops` command (sdk/python, package ops-ai) into an isolated tool environment. It needs only httpx and
# typing-extensions and never resolves the workspace's dev dependencies, which a company mirror may not serve.
#
#   scripts/install_cli.sh              from the package index (uv tool install, or pip --user when uv is missing)
#   WHEELS=dist/wheelhouse scripts/install_cli.sh    offline, from the files make wheelhouse wrote
#
# Mirror settings are honoured: UV_INDEX_URL / UV_DEFAULT_INDEX for uv, PIP_INDEX_URL / PIP_EXTRA_INDEX_URL for pip,
# and for uv they are also read from the PIP_* names when the UV_* ones are unset. A trusted host (PIP_TRUSTED_HOST,
# UV_INSECURE_HOST) and a CA bundle (SSL_CERT_FILE, PIP_CERT, UV_NATIVE_TLS) pass through to the installer.
#
# UV_NO_CONFIG skips [tool.uv] in the repository's pyproject.toml: its exclude-newer needs upload times, which many
# mirrors' indexes do not send, so every version would look too new.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PKG=$ROOT/sdk/python
WHEELS=${WHEELS:-}
offline=()
if [ -n "$WHEELS" ]; then
  [ -d "$WHEELS" ] || { echo "install-cli: WHEELS=$WHEELS is not a folder; run 'make wheelhouse' on a machine with internet" >&2; exit 2; }
  WHEELS=$(cd "$WHEELS" && pwd)
  offline=(--no-index --find-links "$WHEELS")
fi

if command -v uv >/dev/null 2>&1; then
  export UV_NO_CONFIG=1 UV_PYTHON_DOWNLOADS=${UV_PYTHON_DOWNLOADS:-never}
  # uv does not read the PIP_* names; a machine set up for pip then still works.
  if [ -z "${UV_DEFAULT_INDEX:-}${UV_INDEX_URL:-}" ] && [ -n "${PIP_INDEX_URL:-}" ]; then export UV_DEFAULT_INDEX=$PIP_INDEX_URL; fi
  if [ -z "${UV_INDEX:-}" ] && [ -n "${PIP_EXTRA_INDEX_URL:-}" ]; then export UV_INDEX=${PIP_EXTRA_INDEX_URL// /,}; fi
  if [ -z "${UV_INSECURE_HOST:-}" ] && [ -n "${PIP_TRUSTED_HOST:-}" ]; then export UV_INSECURE_HOST=$PIP_TRUSTED_HOST; fi
  if [ -z "${SSL_CERT_FILE:-}" ] && [ -n "${PIP_CERT:-}" ]; then export SSL_CERT_FILE=$PIP_CERT; fi
  target=$PKG
  [ -n "$WHEELS" ] && target=ops-ai
  uv tool install --force ${offline[@]+"${offline[@]}"} "$target"
else
  py=${PYTHON:-python3}
  if [ -n "$WHEELS" ]; then
    "$py" -m pip install --user --upgrade "${offline[@]}" ops-ai
  else
    "$py" -m pip install --user --upgrade "$PKG"
  fi
fi

if command -v ops >/dev/null 2>&1; then
  echo "install-cli: ops is on PATH at $(command -v ops)"
else
  echo "install-cli: installed, but ops is not on PATH yet; add the tool folder to PATH (uv tool update-shell, or ~/.local/bin)" >&2
fi
