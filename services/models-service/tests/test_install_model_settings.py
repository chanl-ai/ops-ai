"""The install's model connection from OPENAI_API_TYPE, OPENAI_API_BASE (or OPENAI_BASE_URL), OPENAI_API_VERSION and
OPENAI_API_REGION (c-605, owner 2026-10-31), one test per rule: a plain base starts as an OpenAI-compatible endpoint,
Azure needs its endpoint and api-version, the region is optional, an unknown type or a base that is not a URL stops
models-service naming the variable, the old OPENAI_BASE_URL name still works, nothing set changes nothing, a dev restart
moves openai-local to what the settings name, and no other service reads any of it."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.connection_settings import ModelConnectionSettings
from ops_models.seed import OPENAI_LOCAL, install_connection, seed
from ops_models.store import provider_connections
from ops_service_kit.settings import Settings

NAMES = ("OPENAI_API_TYPE", "OPENAI_API_BASE", "OPENAI_BASE_URL", "OPENAI_API_VERSION", "OPENAI_API_REGION")
AZURE = {
    "OPENAI_API_TYPE": "azure",
    "OPENAI_API_BASE": "https://contoso-claims.openai.azure.com",
    "OPENAI_API_VERSION": "2024-10-21",
    "OPENAI_API_REGION": "swedencentral",
}


def _env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def _connection(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> dict[str, str | None] | None:
    _env(monkeypatch, env)
    return install_connection(ModelConnectionSettings())


def _refused(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], named: str) -> None:
    _env(monkeypatch, env)
    with pytest.raises(ValidationError, match=named):
        ModelConnectionSettings()


def test_a_base_alone_starts_as_an_openai_compatible_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # vLLM, Ollama, LiteLLM or a gateway: a bearer key at that URL, with stray Azure values beside it ignored.
    vllm = {"OPENAI_API_BASE": "http://10.0.0.7:8000/v1", "OPENAI_API_REGION": "eastus"}
    assert _connection(monkeypatch, vllm) == {
        "type": "openai-compatible",
        "base_url": "http://10.0.0.7:8000/v1",
        "key_ref": "openai",
        "api_version": None,
        "region": None,
    }


def test_the_old_openai_base_url_name_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    got = _connection(monkeypatch, {"OPENAI_BASE_URL": "https://gateway.bank.example/v1"})
    assert got is not None and got["base_url"] == "https://gateway.bank.example/v1"


def test_azure_without_its_endpoint_or_api_version_stops_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _refused(monkeypatch, {k: v for k, v in AZURE.items() if k != "OPENAI_API_BASE"}, "OPENAI_API_BASE")
    _refused(monkeypatch, {k: v for k, v in AZURE.items() if k != "OPENAI_API_VERSION"}, "OPENAI_API_VERSION")
    _refused(monkeypatch, {**AZURE, "OPENAI_API_VERSION": "2024-02-01"}, "OPENAI_API_VERSION")
    _refused(monkeypatch, {**AZURE, "OPENAI_API_BASE": f"{AZURE['OPENAI_API_BASE']}/openai/v1"}, "OPENAI_API_BASE")


def test_the_region_never_stops_start_up(monkeypatch: pytest.MonkeyPatch) -> None:
    # It only flags an answer from elsewhere: missing, or in any spelling, the service starts.
    got = _connection(monkeypatch, {k: v for k, v in AZURE.items() if k != "OPENAI_API_REGION"})
    assert got is not None and (got["type"], got["region"]) == ("azure-openai", None)
    odd = _connection(monkeypatch, {**AZURE, "OPENAI_API_REGION": "eu-west-1"})
    assert odd is not None and odd["region"] == "eu-west-1"


def test_an_unknown_type_or_a_base_that_is_not_a_url_stops_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _refused(monkeypatch, {"OPENAI_API_TYPE": "bedrock"}, "OPENAI_API_TYPE")
    _refused(monkeypatch, {"OPENAI_API_BASE": "api.openai.com"}, "OPENAI_API_BASE")


def test_with_none_set_nothing_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _connection(monkeypatch, {}) is None
    openai = _connection(monkeypatch, {"OPENAI_API_TYPE": "openai"})
    assert openai is not None and openai["base_url"] == "https://api.openai.com/v1"


def test_no_other_service_fails_on_them(monkeypatch: pytest.MonkeyPatch) -> None:
    # The shared settings every service loads take no part: values models-service refuses do not stop them.
    _env(monkeypatch, {"OPENAI_API_TYPE": "azure", "OPENAI_API_BASE": "not a url"})
    assert Settings().openai_api_type == "azure"


async def test_a_dev_restart_moves_openai_local_to_the_azure_resource(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(database_url)
    # A dev database that already holds openai-local on the fake.
    await seed(engine, "http://127.0.0.1:6199/v1")
    await seed(engine, "http://127.0.0.1:6199/v1", _connection(monkeypatch, AZURE))
    async with engine.begin() as c:
        q = sa.select(provider_connections).where(provider_connections.c.id == OPENAI_LOCAL)
        row = (await c.execute(q)).mappings().one()
        # Back on the fake, as every other test of this database expects openai-local.
        back = {"type": "openai-compatible", "api_version": None, "region": None, "key_ref": None}
        await c.execute(provider_connections.update().where(provider_connections.c.id == OPENAI_LOCAL).values(**back))
    assert (row["type"], row["base_url"], row["api_version"], row["region"], row["key_ref"]) == (
        "azure-openai",
        AZURE["OPENAI_API_BASE"],
        "2024-10-21",
        "swedencentral",
        "openai",
    )
    await engine.dispose()
