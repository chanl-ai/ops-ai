#!/usr/bin/env python3
"""The kit's code rules (ops_service_kit.standards.check) for every service, not only agents-service: the environment
is read only in the kit's settings module, nothing prints or builds its own logger, and every route of the service's
app depends on one of the service's authentication functions or is on its list of public routes (rules 4 to 6).

agents-service runs the same check beside its layer rules in services/agents-service/scripts/check_standards.py. Each
other service's app comes from the `build_app` of its scripts/check_openapi.py, which builds it without a database.

A service the check finds problems in today is on WAITING with the count it holds: the count may fall and never rises,
and a service on the list that has fallen to zero is taken off it. `--self-test` plants a route with no authentication
and a count above the list and proves each is reported.

    uv run python scripts/check_service_standards.py [--self-test]
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from ops_identity import current_caller, current_principal, current_service, current_tenant_caller
from ops_models.app import model_key
from ops_platform.api.app import _bearer
from ops_runner.app import create_runner_app
from ops_runner.wasm import WasmPython
from ops_service_kit import standards
from ops_service_kit.settings import Settings, isolate_from_stack

ROOT = Path(__file__).resolve().parents[1]
# The one module allowed to read the environment: every service reads its settings through the kit's.
SETTINGS_MODULE = "ops_service_kit.settings"
# The sign-in dependencies of ops_identity, which most services' routes name.
IDENTITY = frozenset({current_caller, current_principal, current_service, current_tenant_caller})

# Services the check finds problems in, with how many. A count only falls; one at zero is removed.
WAITING: dict[str, int] = {}
# Services with no app of their own to read: a folder with no source.
NO_APP = {"hitl-service"}


@dataclass
class Target:
    app: FastAPI
    authenticated: set[Callable[..., Any]] = field(default_factory=lambda: set(IDENTITY))
    public: set[str] = field(default_factory=set)


# platform-service signs people in, so its public app holds the sign-in, single sign-on, OAuth and invite routes that
# are reached before any token exists; every other route there depends on the bearer token.
PLATFORM_PUBLIC = {
    "/v1/health",
    "/.well-known/jwks.json",
    "/.well-known/oauth-authorization-server",
    "/v1/auth/sign-in",
    "/v1/auth/refresh",
    "/v1/auth/options",
    "/v1/auth/sso/start",
    "/v1/auth/sso/complete",
    "/v1/auth/oidc/callback",
    "/v1/auth/saml/metadata",
    "/v1/auth/saml/metadata/{sp_id}",
    "/v1/auth/saml/acs",
    "/v1/auth/saml/acs/{sp_id}",
    "/v1/auth/password/forgot",
    "/v1/auth/password/reset",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/token",
    "/v1/invites/{token}",
    "/v1/invites/{token}/accept",
}


def _script(service: str) -> Any:
    path = ROOT / "services" / service / "scripts" / "check_openapi.py"
    spec = importlib.util.spec_from_file_location(f"openapi_{service.replace('-', '_')}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def service_principals(app: FastAPI) -> set[Callable[..., Any]]:
    """The `principal` of each ServiceAuth an app's routes depend on: a bound method, one per instance."""
    found: set[Callable[..., Any]] = set()
    stack = [route.dependant for route in app.routes if isinstance(route, APIRoute)]
    while stack:
        node = stack.pop()
        for sub in node.dependencies:
            if type(getattr(sub.call, "__self__", None)).__name__ == "ServiceAuth":
                found.add(cast(Callable[..., Any], sub.call))
            stack.append(sub)
    return found


def targets(service: str) -> list[Target]:
    if service == "runner-service":
        return [Target(create_runner_app(cast(WasmPython, None), settings=Settings(), tools=None))]
    module = _script(service)
    if service == "platform-service":
        public, internal = module.build_apps()
        return [
            Target(public, {_bearer}, PLATFORM_PUBLIC),
            Target(internal, service_principals(internal)),
        ]
    if service == "models-service":
        # The OpenAI-compatible completion and embedding routes authenticate by the model key a client sends.
        return [Target(module.build_app(), set(IDENTITY) | {model_key})]
    return [Target(module.build_app())]


def services() -> list[str]:
    return sorted(p.name for p in (ROOT / "services").glob("*-service") if (p / "src").is_dir())


def findings(service: str, sweep: bool) -> list[str]:
    out: list[str] = []
    for index, target in enumerate(targets(service)):
        out += standards.check(
            target.app,
            settings_module=SETTINGS_MODULE,
            authenticated=target.authenticated,
            public=target.public,
            # The source rules read the whole workspace, so they run once.
            roots=None if sweep and index == 0 else [],
        )
    return out


def verdict(service: str, found: list[str], waiting: dict[str, int]) -> list[str]:
    """What fails for `service`: any problem beyond its count on the waiting list, and a count that has fallen."""
    held = waiting.get(service, 0)
    if len(found) > held:
        return [f"{service}: {len(found)} problems, {held} allowed:", *(f"  {line}" for line in found)]
    if len(found) < held:
        return [f"{service}: {len(found)} problems now; lower its WAITING count from {held} to {len(found)}"]
    return []


def main() -> int:
    isolate_from_stack()
    failed: list[str] = []
    names = [s for s in services() if s not in {"agents-service", *NO_APP}]
    for index, service in enumerate(names):
        found = findings(service, sweep=index == 0)
        failed += verdict(service, found, WAITING)
        print(
            f"{service}: {len(found)} problems" + (f" (waiting list: {WAITING[service]})" if service in WAITING else "")
        )
    failed += [f"{s} is on WAITING and has no app to check" for s in WAITING if s not in names]
    print("\n".join(failed))
    return 1 if failed else 0


def self_test() -> int:
    """Plants a route with no authentication and a count above the list; each must be reported."""
    isolate_from_stack()
    app = FastAPI()

    @app.get("/v1/open")
    def open_route() -> dict[str, str]:
        return {}

    @app.get("/v1/closed")
    def closed_route(_: object = Depends(current_service)) -> dict[str, str]:
        return {}

    planted = standards.check(app, settings_module=SETTINGS_MODULE, authenticated=IDENTITY, roots=[])
    assert len(planted) == 1 and "/v1/open" in planted[0], planted
    assert verdict("x", planted, {}) and not verdict("x", planted, {"x": 1}), "a count above the list must fail"
    assert verdict("x", [], {"x": 1}), "a count that fell must be lowered"
    print("PASS a route with no authentication, a count above the list and one below it are each reported")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
