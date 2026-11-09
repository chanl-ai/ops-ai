#!/usr/bin/env bash
# Installs the `opsai` command (sdk/python, package ops-ai) into an isolated tool environment. It needs only httpx and
# typing-extensions and never resolves the workspace's dev dependencies, which a company mirror may not serve.
#
#   scripts/install_cli.sh              from the package index (uv tool install, or pip --user when uv is missing)
#   WHEELS=dist/wheelhouse scripts/install_cli.sh    offline, from the files make wheelhouse wrote
#
# FROM_INDEX=1 installs `ops-ai` by name from the configured index instead of building the checkout: for an index that
# holds the wheelhouse's files (a Nexus hosted repository) and not the build tool.
#
# Mirror settings are honoured: UV_INDEX_URL / UV_DEFAULT_INDEX for uv, PIP_INDEX_URL / PIP_EXTRA_INDEX_URL for pip,
# and for uv they are also read from the PIP_* names when the UV_* ones are unset. A trusted host (PIP_TRUSTED_HOST,
# UV_INSECURE_HOST) and a CA bundle (SSL_CERT_FILE, PIP_CERT, UV_NATIVE_TLS) pass through to the installer.
#
# uv runs from a folder outside the repository, so [tool.uv] in the repository's pyproject.toml (its exclude-newer needs
# upload times, which many mirrors' indexes do not send) is not read, while the person's own uv.toml (index,
# credentials, certificates) is.
set -euo pipefail

# The package also ships an `ops` shim, kept for one release. It is removed again when another tool already owns the
# name `ops` on PATH, and kept (with a note) otherwise.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PKG=$ROOT/sdk/python
foreign_ops=
if existing=$(command -v ops 2>/dev/null) && ! "$existing" --version 2>/dev/null | grep -q '^ops-ai '; then foreign_ops=$existing; fi
WHEELS=${WHEELS:-}
FROM_INDEX=${FROM_INDEX:-}
bindir=
offline=()
if [ -n "$WHEELS" ]; then
  [ -d "$WHEELS" ] || { echo "install-cli: WHEELS=$WHEELS is not a folder; run 'make wheelhouse' on a machine with internet" >&2; exit 2; }
  WHEELS=$(cd "$WHEELS" && pwd)
  offline=(--no-index --find-links "$WHEELS")
fi

if command -v uv >/dev/null 2>&1; then
  export UV_PYTHON_DOWNLOADS=${UV_PYTHON_DOWNLOADS:-never}
  # uv does not read the PIP_* names; a machine set up for pip then still works.
  if [ -z "${UV_DEFAULT_INDEX:-}${UV_INDEX_URL:-}" ] && [ -n "${PIP_INDEX_URL:-}" ]; then export UV_DEFAULT_INDEX=$PIP_INDEX_URL; fi
  if [ -z "${UV_INDEX:-}" ] && [ -n "${PIP_EXTRA_INDEX_URL:-}" ]; then export UV_INDEX=${PIP_EXTRA_INDEX_URL// /,}; fi
  if [ -z "${UV_INSECURE_HOST:-}" ] && [ -n "${PIP_TRUSTED_HOST:-}" ]; then export UV_INSECURE_HOST=$PIP_TRUSTED_HOST; fi
  if [ -z "${SSL_CERT_FILE:-}" ] && [ -n "${PIP_CERT:-}" ]; then export SSL_CERT_FILE=$PIP_CERT; fi
  target=$PKG
  [ -n "$WHEELS$FROM_INDEX" ] && target=ops-ai
  cd "$(mktemp -d)"
  bindir=$(uv tool dir --bin)
  uv tool install --force ${offline[@]+"${offline[@]}"} "$target"
else
  py=${PYTHON:-python3}
  bindir=$("$py" -c 'import site,sys;print(site.USER_BASE + ("\\Scripts" if sys.platform == "win32" else "/bin"))' 2>/dev/null || true)
  if [ -n "$WHEELS" ]; then
    "$py" -m pip install --user --upgrade "${offline[@]}" ops-ai
  elif [ -n "$FROM_INDEX" ]; then
    "$py" -m pip install --user --upgrade ops-ai
  else
    "$py" -m pip install --user --upgrade "$PKG"
  fi
fi

if [ -n "$bindir" ] && [ -n "$foreign_ops" ]; then
  rm -f "$bindir/ops" "$bindir/ops.exe"
  echo "install-cli: another tool already owns the name ops ($foreign_ops), so only opsai was installed"
elif [ -n "$bindir" ] && [ -e "$bindir/ops" ]; then
  echo "install-cli: ops is also installed as an alias for opsai (it goes away in the next release)"
fi
if command -v opsai >/dev/null 2>&1; then
  echo "install-cli: opsai is on PATH at $(command -v opsai)"
else
  echo "install-cli: installed, but opsai is not on PATH yet; add the tool folder to PATH (uv tool update-shell, or ~/.local/bin)" >&2
fi
