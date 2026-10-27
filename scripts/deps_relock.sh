#!/usr/bin/env bash
# `make deps-relock MIRROR=1`: locks again inside what `make deps-doctor` found the mirror serves, then installs and runs
# a fast test subset. Reads .mirror/constraints.txt (Python) and .mirror/npm-overrides.json (npm), with the mirror in
# UV_DEFAULT_INDEX and NPM_CONFIG_REGISTRY.
#
# The result is for this machine: uv.lock now names the mirror's file URLs and pnpm-workspace.yaml carries the npm
# overrides. Do not commit either; `git checkout uv.lock pnpm-lock.yaml pnpm-workspace.yaml` puts them back.
#
# exclude-newer is set aside for the Python lock: it needs upload times in the index, which many mirrors (Sonatype
# Nexus among them) do not send, and setting it aside makes uv drop the old lock. Each package is therefore constrained
# to its locked version, except the ones the constraints file replaces.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
: "${UV_DEFAULT_INDEX:?set UV_DEFAULT_INDEX and NPM_CONFIG_REGISTRY to your mirror; see Behind a company mirror in docs/deploy/install.md}"
# A mirror fetching a file for the first time can take longer than uv's default 30 seconds.
export UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT:-300}
[ -f .mirror/constraints.txt ] || { echo "deps-relock: run make deps-doctor first (it writes .mirror/constraints.txt)"; exit 1; }

backup=$(mktemp -t pyproject.XXXXXX)
cp pyproject.toml "$backup"
trap 'cp "$backup" "$ROOT/pyproject.toml"; rm -f "$backup"' EXIT

# One constraint per locked package, with the doctor's versions in place of the blocked ones, so the lock below keeps
# every version it has except those. They go into pyproject.toml only while uv lock runs (uv takes no constraints
# file for a lock) and exclude-newer is set aside the same way.
python3 - <<'PY'
import re
import subprocess
from pathlib import Path

locked = subprocess.run(
    ["uv", "export", "--frozen", "--no-emit-workspace", "--no-hashes", "--no-header", "--no-annotate"],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
pins = {}
for line in locked:
    m = re.match(r"^([A-Za-z0-9_.-]+)==([^;\s]+)(.*)$", line.strip())
    if m:
        pins[m.group(1).lower().replace("_", "-")] = (m.group(2), m.group(3).strip())
replaced = 0
for line in Path(".mirror/constraints.txt").read_text().splitlines():
    name, _, version = line.partition("==")
    if name and version:
        key = name.lower().replace("_", "-")
        pins[key] = (version, pins.get(key, ("", ""))[1])
        replaced += 1
entries = ",\n".join(f'    "{n}=={v}{(" ; " + m.lstrip("; ")) if m else ""}"' for n, (v, m) in sorted(pins.items()))
text = Path("pyproject.toml").read_text()
text = re.sub(r"(?m)^exclude-newer = .*\n", "", text)
text = text.replace("[tool.uv]\n", f"[tool.uv]\nconstraint-dependencies = [\n{entries},\n]\n", 1)
Path("pyproject.toml").write_text(text)
print(f"{len(pins)} version constraints, {replaced} replaced by what the mirror serves")
PY
echo "== uv lock"
uv lock

echo "== pnpm overrides from .mirror/npm-overrides.json"
python3 - <<'PY'
import json
from pathlib import Path

overrides = json.loads(Path(".mirror/npm-overrides.json").read_text())
if overrides:
    path = Path("pnpm-workspace.yaml")
    text = path.read_text().rstrip("\n")
    if "\noverrides:\n" not in text:
        text += "\n# Local mirror overrides written by make deps-relock MIRROR=1; do not commit.\noverrides:"
    for name, version in overrides.items():
        line = f"  '{name}': {version}"
        if line not in text:
            head, _, tail = text.partition("\noverrides:")
            text = f"{head}\noverrides:{tail}\n{line}"
    path.write_text(text + "\n")
    print(f"{len(overrides)} npm overrides in pnpm-workspace.yaml")
PY
pnpm install --lockfile-only

echo "== install and fast tests"
bash scripts/install_via_mirror.sh
pnpm install --frozen-lockfile
bash scripts/deps_smoke.sh
echo "deps-relock: PASS (do not commit uv.lock, pnpm-lock.yaml or pnpm-workspace.yaml)"
