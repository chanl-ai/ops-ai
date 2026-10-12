"""The shared FastAPI layer, by failure mode: the mode taken from anything but auth_mode, the dev team overriding an
explicit X-Team-Id, X-Dev-User naming only half the person, a service's per-request hook skipped, and a route on an
app that never installed auth answering as if authenticated."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ops_identity import Auth, CurrentPrincipal, Principal, install_auth
from ops_service_kit.settings import Settings

SEED = Path(__file__).parents[3] / "services" / "agents-service" / "tests" / "fixtures" / "seed"


def settings(**kw: Any) -> Settings:
    return Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, **kw)


def app_with(auth: Auth | None) -> FastAPI:
    app = FastAPI()
    if auth is not None:
        install_auth(app, auth)

    @app.get("/who")
    async def who(p: CurrentPrincipal) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return p.model_dump()

    return app


async def get(app: FastAPI, **headers: str) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/who", headers=headers)


def test_the_mode_comes_from_auth_mode_not_from_a_platform_url() -> None:
    dev = Auth.from_settings(settings(platform_url="http://127.0.0.1:8710"), audience="tools")
    assert dev.identity.dev_user is not None
    platform = Auth.from_settings(
        settings(auth_mode="platform", platform_url="http://127.0.0.1:8710"), audience="tools"
    )
    assert platform.identity.dev_user is None


async def test_dev_names_the_second_person_and_never_overrides_an_explicit_team() -> None:
    app = app_with(Auth.from_settings(settings(), audience="tools"))
    default = (await get(app)).json()
    assert (default["tenant_id"], default["team_id"], default["team_ids"]) == ("local", "team_all", ["team_all"])
    other = (await get(app, **{"X-Dev-User": "m.o@bank.test", "X-Team-Id": "team_cards"})).json()
    assert (other["email"], other["name"], other["team_id"]) == ("m.o@bank.test", "m.o@bank.test", "team_cards")


async def test_the_services_hook_runs_for_each_request() -> None:
    seen: list[Principal] = []
    auth = Auth.from_settings(settings(), audience="tools")
    auth.on_principal = seen.append
    await get(app_with(auth), **{"X-Team-Id": "team_x"})
    assert [p.team_id for p in seen] == ["team_x"]


async def test_an_app_without_installed_auth_refuses_to_answer() -> None:
    with pytest.raises(RuntimeError, match="install_auth"):
        await get(app_with(None))
