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
# The one list of checks the hook runs (make checks STAGED=1).
cp "$root/Makefile" Makefile
cp "$root/make/checks.mk" make/checks.mk
git add make/checks.mk
git -c user.name=t -c user.email=t@local commit -q --no-verify -am "hook under test" >/dev/null 2>&1 || true
# apps/embed/node_modules: the hook's console verify type-checks the embed app too (verify-staged.sh links it the same way).
# sdk/typescript/node_modules: the sdk gate runs openapi-typescript from there (verify-staged.sh links it the same way).
for dep in node_modules apps/console/node_modules apps/embed/node_modules packages/usecase-runner/node_modules sdk/typescript/node_modules .venv; do
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
# A route change committed with its openapi.json regenerated, and the SDK drift check run on it. Whether a document matches
# its app is a CI and `make verify` check (`make openapi`), not a commit's: the commit check skips service builds.
app=services/models-service/src/ops_models/app.py
python3 - "$app" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = '    @app.get("/health", tags=["health"], response_model=Health)'
assert s.count(old) == 1
# A route a service may add without a new finding: authenticated, with a typed reply, so only the openapi gate fails.
route = (
    '    @app.get("/v1/models/probe", tags=["health"], response_model=Envelope[ProbeOut])\n'
    "    async def probe(p: CurrentTenantCaller) -> Envelope[ProbeOut]:  # pyright: ignore[reportUnusedFunction]\n"
    '        return ok(ProbeOut(status="ok"))\n\n'
)
model = "class _Wire(In):"
assert s.count(model) == 1
s = s.replace(model, "class ProbeOut(Out):\n    status: str\n\n\n" + model, 1)
p.write_text(s.replace(old, route + old, 1))
PY
git add "$app"
pp=$(ls -d "$PWD"/packages/*/src "$PWD"/services/*/src | tr '\n' ':')
(cd services/models-service && "$root/.venv/bin/python" -I -c "import runpy, sys; sys.path[:0] = '$pp'.split(':'); sys.argv = ['check_openapi.py', '--write']; runpy.run_path('scripts/check_openapi.py', run_name='__main__')" >/dev/null)
git add services/models-service/openapi.json
if commit routed "$app" services/models-service/openapi.json; then echo "PASS the same change with its regenerated openapi.json goes through"; else echo "FAIL the regenerated openapi.json was refused:"; tail -5 "$tmp/routed.log"; pass=1; fi
# A database driver imported outside a store package (the import contracts).
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
# The list of checks (make/checks.mk): a staged path a check names runs it, and a failure refuses the commit under the
# check's command. A loopback fallback in a service is one the config-literals check lists.
printf '\nPROBE = None or "http://127.0.0.1:9"\n' >> services/files-service/src/ops_files/__init__.py
git add services/files-service/src/ops_files/__init__.py
if commit listed services/files-service/src/ops_files/__init__.py; then echo "FAIL a loopback fallback in a service was committed"; pass=1; else
  grep -q "check_config_literals.py --strict (exit 1)" "$tmp/listed.log" && echo "PASS a check on the list refuses a commit it fails, naming it" || { echo "FAIL the listed-check commit failed for another reason:"; tail -5 "$tmp/listed.log"; pass=1; }
fi
git checkout -q HEAD -- services/files-service/src/ops_files/__init__.py
# The checks that sat beside the list in verify-staged.sh are on it: a staged path a check names runs it, and a failure
# refuses the commit under the check's command. Proved once on cross-service with a test importing another service
# (c4957ea5's fault), then with that check taken off the list in this clone: the same commit goes through, so the
# refusal came from the list and not from another check. Each check has tests of its own (test_no_cross_service_imports.py).
probe=services/tools-service/tests/test_zz_gate_probe.py
printf 'from ops_agents.activities.catalog import Catalog\n\n\ndef test_probe() -> None:\n    assert Catalog\n' > "$probe"
git add "$probe"
if commit gate "$probe"; then echo "FAIL a service test importing another service was committed"; pass=1; else
  grep -q "test_no_cross_service_imports.py (exit 1)" "$tmp/gate.log" && echo "PASS a check on the list refuses a commit it fails, by name" || { echo "FAIL the gate commit failed for another reason:"; tail -5 "$tmp/gate.log"; pass=1; }
fi
python3 - make/checks.mk <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
assert " cross-service " in s, "no cross-service check to take out"
p.write_text(s.replace(" cross-service ", " ", 1))
PY
git add make/checks.mk
git -c user.name=t -c user.email=t@local commit -q --no-verify -m "take cross-service off the list" -- make/checks.mk >/dev/null 2>&1
if commit gate_off "$probe"; then echo "PASS with the check off the list the same commit goes through"; else echo "FAIL the commit was refused with the check off the list:"; tail -5 "$tmp/gate_off.log"; pass=1; fi
exit $pass
