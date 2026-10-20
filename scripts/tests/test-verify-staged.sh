#!/usr/bin/env bash
# The pre-commit hook checks what is being committed, by failure mode: another builder's unfinished file in the tree
# blocking a clean commit, and a bad file getting through once it is the one committed. Runs the real hook in a shared
# clone of this repo at HEAD (objects borrowed, nothing written to this tree), with this tree's hook and script.
#   scripts/tests/test-verify-staged.sh [hook]   # hook defaults to .githooks/pre-commit
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
hook="$(cd "$root" && realpath "${1:-.githooks/pre-commit}")"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ops-ai-hooktest.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
git clone -q --shared --no-checkout "$root" "$tmp/repo"
cd "$tmp/repo"
git checkout -q --detach "$(git -C "$root" rev-parse HEAD)"
cp "$hook" .githooks/pre-commit
cp "$root/scripts/verify-staged.sh" scripts/verify-staged.sh
git -c user.name=t -c user.email=t@local commit -q --no-verify -am "hook under test" >/dev/null 2>&1 || true
# apps/embed/node_modules: the hook's console verify type-checks the embed app too (verify-staged.sh links it the same way).
for dep in node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules .venv; do
  [ -e "$root/$dep" ] && ln -s "$root/$dep" "$dep"
done
git config core.hooksPath .githooks
commit() { git -c user.name=t -c user.email=t@local commit -q -m "$1" -- "${@:2}" >"$tmp/$1.log" 2>&1; }

# Another builder's half-written component: it imports the API client, which check-standards refuses.
printf "import { api } from '@/lib/api';\n\nexport const Probe = () => api;\n" > apps/console/src/components/zz-unfinished.tsx
echo "a clean change" >> docs/usecases/README.md
pass=0
if commit clean docs/usecases/README.md; then echo "PASS a clean commit goes through while another file in the tree fails the standards"; else echo "FAIL a clean commit was blocked by another file:"; tail -5 "$tmp/clean.log"; pass=1; fi
git add apps/console/src/components/zz-unfinished.tsx
if commit bad apps/console/src/components/zz-unfinished.tsx; then echo "FAIL the bad file was committed"; pass=1; else
  grep -q "imports the API client" "$tmp/bad.log" && echo "PASS committing the bad file fails on check-standards" || { echo "FAIL the bad commit failed for another reason:"; tail -5 "$tmp/bad.log"; pass=1; }
fi
# A route change committed without its openapi.json, then with it regenerated (the openapi gate, 10-18).
app=services/models-service/src/ops_models/app.py
python3 - "$app" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = '    @app.get("/health", tags=["health"], response_model=Health)'
assert s.count(old) == 1
p.write_text(s.replace(old, '    @app.get("/health/probe", tags=["health"], response_model=Health)\n    async def probe() -> Health:  # pyright: ignore[reportUnusedFunction]\n        return Health(status="ok")\n\n' + old, 1))
PY
git add "$app"
if commit route "$app"; then echo "FAIL a route change without its openapi.json was committed"; pass=1; else
  grep -q "models-service/openapi.json does not match" "$tmp/route.log" && echo "PASS a route change without its openapi.json is refused" || { echo "FAIL the route commit failed for another reason:"; tail -5 "$tmp/route.log"; pass=1; }
fi
pp=$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src | tr '\n' ':')
(cd services/models-service && "$root/.venv/bin/python" -I -c "import runpy, sys; sys.path[:0] = '$pp'.split(':'); sys.argv = ['check_openapi.py', '--write']; runpy.run_path('scripts/check_openapi.py', run_name='__main__')" >/dev/null)
git add services/models-service/openapi.json
if commit routed "$app" services/models-service/openapi.json; then echo "PASS the same change with its regenerated openapi.json goes through"; else echo "FAIL the regenerated openapi.json was refused:"; tail -5 "$tmp/routed.log"; pass=1; fi
# A database driver imported outside a store package (the import contracts, c-346).
leak=services/files-service/src/ops_files/service.py
printf 'import sqlalchemy as _sa  # probe\n' >> "$leak"
git add "$leak"
if commit leak "$leak"; then echo "FAIL a driver import outside a store was committed"; pass=1; else
  grep -q "ops_files.service -> sqlalchemy" "$tmp/leak.log" && echo "PASS a driver import outside a store is refused" || { echo "FAIL the leak commit failed for another reason:"; tail -5 "$tmp/leak.log"; pass=1; }
fi
git checkout -q HEAD -- "$leak"
# A commit whose only Python file is a script, outside services/ and packages/ (b78a5a83 refused every such commit).
printf '\n# probe\n' >> scripts/sbom.py
git add scripts/sbom.py
if commit script scripts/sbom.py; then echo "PASS a commit of a script alone goes through"; else echo "FAIL a script-only commit was refused:"; tail -5 "$tmp/script.log"; pass=1; fi
# The gate rows (verify-staged.sh `gate`): a staged path a row names runs its check, and a failure refuses the commit
# under the row's name. Proved once on the cross-service row with a test importing another service (c4957ea5's fault),
# then with that row taken out of this clone's hook: the same commit goes through, so the refusal came from the gate and
# not from another check. Each row's check has tests of its own (test_mssql_ddl.py, test_sbom.py,
# test_no_cross_service_imports.py).
probe=services/tools-service/tests/test_zz_gate_probe.py
printf 'from ops_agents.activities.catalog import Catalog\n\n\ndef test_probe() -> None:\n    assert Catalog\n' > "$probe"
git add "$probe"
if commit gate "$probe"; then echo "FAIL a service test importing another service was committed"; pass=1; else
  grep -q "verify-staged: cross-service:" "$tmp/gate.log" && echo "PASS a gate row refuses a commit its check fails, by name" || { echo "FAIL the gate commit failed for another reason:"; tail -5 "$tmp/gate.log"; pass=1; }
fi
python3 - scripts/verify-staged.sh <<'PY'
import pathlib, re, sys
p = pathlib.Path(sys.argv[1])
s, n = re.subn(r"gate cross-service .*?test_no_cross_service_imports\.py\n", "", p.read_text(), flags=re.S)
assert n == 1, "no cross-service row to take out"
p.write_text(s)
PY
if commit gate_off "$probe"; then echo "PASS with the row taken out the same commit goes through"; else echo "FAIL the commit was refused with the row taken out:"; tail -5 "$tmp/gate_off.log"; pass=1; fi
exit $pass
