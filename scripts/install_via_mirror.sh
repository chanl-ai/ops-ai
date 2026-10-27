#!/usr/bin/env bash
# Installs the Python workspace at the versions uv.lock pins, downloading from the index in UV_DEFAULT_INDEX instead of
# the URLs the lock records. `uv sync --frozen` fetches every locked file from the address written in uv.lock
# (files.pythonhosted.org), which a company mirror does not serve; this script reads only the versions and hashes from
# the lock, and the package manager asks the configured index for them.
#
#   scripts/install_via_mirror.sh [--no-dev]
#
# UV_NO_CONFIG skips [tool.uv] in pyproject.toml: its exclude-newer needs upload times, which many mirrors' PyPI
# indexes (Sonatype Nexus among them) do not send, so every version looks too new and nothing resolves. The lock already
# pins the versions, and hash checking (--require-hashes) rejects a file that is not the locked one.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
: "${UV_DEFAULT_INDEX:?set UV_DEFAULT_INDEX to the PyPI simple index of your mirror; see Behind a company mirror in docs/deploy/install.md}"
export UV_NO_CONFIG=1 UV_PYTHON_DOWNLOADS=${UV_PYTHON_DOWNLOADS:-never}

dev=()
[ "${1:-}" = --no-dev ] && dev=(--no-dev)
python=${UV_PYTHON:-python3.12}
venv=${UV_PROJECT_ENVIRONMENT:-$ROOT/.venv}

[ -x "$venv/bin/python" ] || uv venv --python "$python" "$venv" >/dev/null

reqs=$(mktemp)
trap 'rm -f "$reqs"' EXIT
# --no-emit-workspace leaves out the repo's own packages (they have no hashes); they are installed below from this checkout.
uv export --frozen --no-emit-workspace --no-header --no-annotate ${dev[@]+"${dev[@]}"} >"$reqs"
uv pip install --python "$venv/bin/python" --require-hashes --no-deps -r "$reqs"

members=$(python3 - <<'E'
import tomllib
print(" ".join(tomllib.load(open("pyproject.toml", "rb"))["tool"]["uv"]["workspace"]["members"]))
E
)
args=()
for m in $members; do args+=(-e "$m"); done
uv pip install --python "$venv/bin/python" --no-deps "${args[@]}"
printf 'installed %s packages from %s into %s\n' "$(grep -c '==' "$reqs")" "$(printf '%s' "$UV_DEFAULT_INDEX" | sed -E 's#//[^/@]*@#//***@#')" "$venv"
