#!/usr/bin/env bash
# `make sdk-check`: `make sdk-verify` (the generated layer matches the services' documents and both SDKs' tests pass),
# the built packages install and import in an empty folder, and the examples seed a fresh team and decide runs on the local stack
# (`make up`), through each SDK alone. SDK_LIVE=0 skips the stack part.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ops-sdk-check.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

make -s sdk-verify

# The packages as an outside developer gets them: built, installed into an empty folder, imported.
uv build --quiet --out-dir "$tmp/py" sdk/python
uv venv --quiet "$tmp/venv"
VIRTUAL_ENV="$tmp/venv" uv pip install --quiet "$tmp"/py/*.whl
"$tmp/venv/bin/python" -c "import ops_ai; ops_ai.OpsAI(base_url='https://ops.example.com', api_key='k'); print('sdk-check: python wheel installs and imports')"
(cd sdk/typescript && pnpm --silent pack --pack-destination "$tmp/ts" >/dev/null)
mkdir -p "$tmp/ts-app" && cd "$tmp/ts-app" && npm init -y >/dev/null && npm install --silent "$tmp"/ts/*.tgz
node --input-type=module -e "import { OpsAI } from '@chanl-ai/ops-ai'; new OpsAI({ baseUrl: 'https://ops.example.com' }); console.log('sdk-check: npm package installs and imports')"
cd "$root"

if [ "${SDK_LIVE:-1}" = 0 ]; then echo "sdk-check: SDK_LIVE=0, the stack examples are skipped"; exit 0; fi
# The dev workspace admin of the README's quick start: the local stack only, never a deployed one.
export OPS_EXAMPLE_EMAIL="${OPS_EXAMPLE_EMAIL:-w.kamau@harborpine.example}" OPS_EXAMPLE_PASSWORD="${OPS_EXAMPLE_PASSWORD:-northfield-demo}"
out="$(uv run --isolated --quiet --with-editable sdk/python python sdk/python/examples/seed_team.py --local --keep)"
echo "$out"
ids="$(echo "$out" | sed -n 's/^seed_team: done, //p')"
team="$(echo "$ids" | sed -n 's/.*team=\([^ ]*\).*/\1/p')"
export OPS_EXAMPLE_TEAM="$team" OPS_EXAMPLE_WORKFLOW="$(echo "$ids" | sed -n 's/.*workflow=\([^ ]*\).*/\1/p')"
export OPS_EXAMPLE_REVIEWER="$(echo "$ids" | sed -n 's/.*reviewer=\([^ ]*\).*/\1/p')"
node sdk/typescript/examples/run-and-decide.mjs
# The example's team is archived, so repeated checks leave no active teams behind on the shared stack.
uv run --isolated --quiet --with-editable sdk/python python - <<PY
from ops_ai import OpsAI
ports = {"platform": 8710, "agents": 8700, "tools": 8720, "kb": 8740, "files": 8750, "documents": 8760}
admin = OpsAI.sign_in("$OPS_EXAMPLE_EMAIL", "$OPS_EXAMPLE_PASSWORD", base_url="http://127.0.0.1", services={s: f"http://127.0.0.1:{p}" for s, p in ports.items()})
admin.raw.platform.teams_archive_team("$team")
print("sdk-check: the example team $team is archived")
PY
echo "sdk-check: ok"
