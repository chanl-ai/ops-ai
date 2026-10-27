#!/usr/bin/env bash
# The fast tests that show a fresh install works: identity and policy packages (no database) and the console's unit
# tests. Used by `make deps-relock MIRROR=1` and the behind-a-mirror lane; run after the Python and npm installs.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python=${UV_PROJECT_ENVIRONMENT:-$ROOT/.venv}/bin/python
# Each package has its own `tests` package, so each runs from its own folder, as make python-verify does.
for pkg in ops_identity ops_policy; do (cd "$ROOT/packages/$pkg" && "$python" -m pytest -q -p no:cacheprovider); done
(cd "$ROOT" && pnpm --filter @ops-ai/console exec node --test 'src/**/*.test.ts')
