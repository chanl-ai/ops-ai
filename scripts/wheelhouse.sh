#!/usr/bin/env bash
# Writes every wheel the `ops` command needs into one folder, for machines with no package index at all.
# Run it on a machine with internet; copy the folder across; install with `make install-cli WHEELS=<folder>`.
#
#   scripts/wheelhouse.sh [OUT]            OUT defaults to dist/wheelhouse
#   PLATFORMS="macosx_11_0_arm64 manylinux2014_x86_64" PYTHONS="3.11 3.12" scripts/wheelhouse.sh
#
# Wheels are fetched per platform and Python version because a dependency may ship a compiled wheel for some of them.
# requirements.txt in the folder pins every file written. Honours PIP_INDEX_URL, PIP_EXTRA_INDEX_URL and the other pip settings.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-$ROOT/dist/wheelhouse}
PLATFORMS=${PLATFORMS:-"macosx_11_0_arm64 macosx_10_9_x86_64 manylinux2014_x86_64 win_amd64"}
PYTHONS=${PYTHONS:-"3.11 3.12"}
py=${PYTHON:-python3}

mkdir -p "$OUT"
rm -f "$OUT"/*.whl "$OUT"/requirements.txt

# The CLI's own wheel; pip builds it from the checkout, so hatchling comes from the index on this machine only.
"$py" -m pip wheel --no-deps --wheel-dir "$OUT" "$ROOT/sdk/python" >/dev/null

tags=()
for p in $PLATFORMS; do tags+=(--platform "$p"); done
for v in $PYTHONS; do
  "$py" -m pip download --only-binary=:all: --dest "$OUT" --find-links "$OUT" \
    --python-version "$v" --implementation cp "${tags[@]}" ops-ai >/dev/null
done

"$py" - "$OUT" <<'E'
import pathlib, sys
out = pathlib.Path(sys.argv[1])
pins = sorted({"==".join(w.name.split("-")[:2]).replace("_", "-") for w in out.glob("*.whl")})
(out / "requirements.txt").write_text("\n".join(pins) + "\n")
print(f"wheelhouse: {len(list(out.glob('*.whl')))} wheels in {out}")
E
