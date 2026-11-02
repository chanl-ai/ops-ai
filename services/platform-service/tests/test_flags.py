"""The install's feature flags in the console's one answer, GET /v1/me (c-611)."""

from __future__ import annotations

import pytest

from .conftest import SignInRig


@pytest.fixture
def no_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_FLAGS", raising=False)


@pytest.fixture
def mcp_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_FLAGS", '["mcp_gateway"]')


async def _flags(signin: SignInRig) -> dict[str, bool]:
    r = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    assert r.status_code == 200, r.text
    return {f["name"]: f["on"] for f in r.json()["data"]["flags"]}


async def test_every_flag_is_listed_off_when_the_install_config_names_none(no_flags: None, signin: SignInRig) -> None:
    flags = await _flags(signin)
    assert "mcp_gateway" in flags
    assert not any(flags.values()), flags


async def test_a_flag_the_install_config_names_is_on(mcp_on: None, signin: SignInRig) -> None:
    assert (await _flags(signin))["mcp_gateway"] is True
