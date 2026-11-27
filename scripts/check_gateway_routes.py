"""Refuses a console call that no gateway routes: every /api/<service>/... path the console's clients call must match
a route in each gateway config (deploy/**/Caddyfile).

The browser reaches one origin; the gateway sends /api/<service>/ to that service and everything else to the console.
A call the gateway does not route falls through to the console and answers 404 (a gateway that listed only
/api/models/v1/provider-keys* left the model connections and aliases screens empty). One Caddyfile is the gateway of
the compose, Kubernetes and Fly installs (the proxy image, deploy/CLAUDE.md), so one file is read; every Caddyfile
found under deploy/ is held to the same list.

The calls are read from the one place that builds them: each service's address is NEXT_PUBLIC_OPS_<X>_API_URL in
deploy/compose/app.yaml (`${OPS_PUBLIC_ORIGIN}/api/<service>`); apps/console/src/lib/api/index.ts hands that address to
a client factory, whose file (and the `-http` files it imports) holds the paths it calls. Matching follows Caddy's path
matcher: a pattern ending in `*` is a prefix, any other is exact, case-insensitively. The generated SDK clients are not
read; they reach services that route their whole prefix.

  uv run python scripts/check_gateway_routes.py              # exit 1 on a finding
  uv run python scripts/check_gateway_routes.py --self-test  # plants a missing route and a covered prefix
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "compose" / "app.yaml"
API = ROOT / "apps" / "console" / "src" / "lib" / "api"

Reader = Callable[[str], str | None]
PUBLIC_URL = re.compile(r"NEXT_PUBLIC_(OPS_\w+): \$\{OPS_PUBLIC_ORIGIN\}/api/([\w-]+)\s*$", re.M)
URL_VAR = re.compile(r"const (\w+) = process\.env\.(NEXT_PUBLIC_OPS_\w+);")
FACTORY_CALL = re.compile(r"\b(create\w+)\(\s*(\w+)!?[,)]")
IMPORT = re.compile(r"import \{([^}]*)\} from '(\./[\w-]+)';")
PATH_CALL = re.compile(r"\b(?:get|send)\(\s*(?:'[A-Z]+'\s*,\s*)?[`'\"](/[^`'\"?]*)")
V1_TRANSPORT = re.compile(r"createTransport\(`\$\{baseUrl\}/v1`\)")
HANDLE = re.compile(r"^\s*handle(?:_path)?\s+(/\S+)\s*\{", re.M)
MATCHER = re.compile(r"^\s*@(\w+) path ([^\n]+)$", re.M)
HANDLE_MATCHER = re.compile(r"^\s*handle @(\w+)\s*\{", re.M)


def routes(caddyfile: str) -> list[str]:
    """The path patterns a gateway routes to a service (the catch-all `handle {` goes to the console)."""
    named = {n: v.split() for n, v in MATCHER.findall(caddyfile)}
    used = [p for n in HANDLE_MATCHER.findall(caddyfile) for p in named.get(n, [])]
    return [p.lower() for p in HANDLE.findall(caddyfile) + used]


def routed(path: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(path.lower(), p) for p in patterns)


def _normal(path: str) -> str:
    return re.sub(r"\$\{[^}]*\}", "x", path)


def calls(compose: str, index: str, read: Reader) -> dict[str, str]:
    """Each full path the console calls, mapped to the client file that calls it."""
    env_service = dict(PUBLIC_URL.findall(compose))
    var_env = dict(URL_VAR.findall(index))
    imports: dict[str, str] = {}
    for names, mod in IMPORT.findall(index):
        for n in names.split(","):
            imports[n.strip().split(" as ")[0]] = mod
    found: dict[str, str] = {}
    for factory, var in FACTORY_CALL.findall(index):
        env = var_env.get(var, "")
        service = env_service.get(env.removeprefix("NEXT_PUBLIC_"))
        mod = imports.get(factory)
        if not service or not mod or mod == "./http":
            continue
        text = read(mod)
        if text is None:
            continue
        prefix = "/v1" if V1_TRANSPORT.search(text) else ""
        seen: set[str] = set()
        todo = [mod]
        while todo:
            m = todo.pop()
            if m in seen:
                continue
            seen.add(m)
            body = read(m) or ""
            for p in PATH_CALL.findall(body):
                found.setdefault(f"/api/{service}{prefix}{_normal(p)}", m)
            todo += [i for _, i in IMPORT.findall(body) if i.endswith("-http") and i != "./http"]
    return found


def findings(compose: str, index: str, read: Reader, gateways: dict[str, str]) -> list[str]:
    out: list[str] = []
    wanted = calls(compose, index, read)
    for name, text in gateways.items():
        patterns = routes(text)
        for path, client in sorted(wanted.items()):
            if not routed(path, patterns):
                out.append(f"{name}: no route for {path} (called by apps/console/src/lib/api/{client[2:]}.ts)")
    return out


def _read(mod: str) -> str | None:
    f = API / f"{mod[2:]}.ts"
    return f.read_text() if f.exists() else None


def load() -> list[str]:
    gateways = {str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT / "deploy").rglob("Caddyfile"))}
    if not gateways:
        return ["no gateway config (deploy/**/Caddyfile) found"]
    return findings(COMPOSE.read_text(), (API / "index.ts").read_text(), _read, gateways)


def self_test() -> None:
    compose = (
        "NEXT_PUBLIC_OPS_MODELS_API_URL: ${OPS_PUBLIC_ORIGIN}/api/models\n"
        "NEXT_PUBLIC_OPS_TOOLS_API_URL: ${OPS_PUBLIC_ORIGIN}/api/tools\n"
    )
    index = (
        "const modelsUrl = process.env.NEXT_PUBLIC_OPS_MODELS_API_URL;\n"
        "const toolsUrl = process.env.NEXT_PUBLIC_OPS_TOOLS_API_URL;\n"
        "import { createModelsHttp } from './models-http';\nimport { createToolsOnlyHttp } from './tools-http';\n"
        "api = createModelsHttp(modelsUrl); api = createToolsOnlyHttp(toolsUrl!);\n"
    )
    files = {
        "./models-http": (
            "import { a } from './keys-http';\ncreateTransport(`${baseUrl}/v1`); "
            "get(`/models/providers?${qs}`); send('POST', '/models/aliases', x);"
        ),
        "./keys-http": "get(`/provider-keys?${qs(p)}`); send('PUT', `/provider-keys/${name}`, v);",
        "./tools-http": "createTransport(`${baseUrl}/v1`); get('/anything/deep');",
    }
    read = files.get
    partial = "handle /api/models/v1/provider-keys* {\n}\nhandle_path /api/tools/* {\n}\nhandle {\n}\n"
    got = findings(compose, index, read, {"Caddyfile": partial})
    assert any("/api/models/v1/models/providers" in f for f in got), got
    assert any("/api/models/v1/models/aliases" in f for f in got), got
    assert not any("provider-keys" in f or "/api/tools" in f for f in got), got
    whole = partial.replace("handle /api/models/v1/provider-keys*", "handle /api/models/*")
    assert findings(compose, index, read, {"Caddyfile": whole}) == [], "a whole-prefix route covers every path"
    assert (
        findings(compose, index, read, {"Caddyfile": partial.replace("provider-keys*", "provider-keys")})[0:1] != []
    ), "no star is exact"
    named = (
        "@m path /api/models/v1/provider-keys* /api/models/v1/models/providers*"
        " /api/models/v1/models/aliases*\nhandle @m {\n}\nhandle_path /api/tools/* {\n}\n"
    )
    got = findings(compose, index, read, {"Caddyfile": named})
    assert got == [], got
    print("check_gateway_routes: self-test ok")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test()
        return 0
    found = load()
    for f in found:
        print(f)
    print(f"check_gateway_routes: {len(found)} findings")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
