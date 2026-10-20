"""Another service reads a credential from the Secrets store (c-221, for c-177's model provider keys), by failure mode:
a team's own secret reaching another service, a service without `secrets_egress:run` or a person reading values, a
read the audit does not show, and a missing secret answered as if it were empty."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_policy import AesGcmCipher, context_of
from ops_service_kit.settings import Settings
from ops_tools.store.secrets import SecretStore

from .conftest import Api, service_headers

MODELS = ["secrets_egress:run"]


async def _secret(engine: AsyncEngine, tenant: str, name: str, value: str, teams: list[str] | None = None) -> None:
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    blob = cipher.encrypt(value, context=context_of(tenant, name))
    assert await SecretStore(engine).create(tenant, name, blob, actor="Sam Adeyemi", at=datetime.now(UTC), teams=teams)


async def values(api: Api, names: list[str], *, scopes: list[str] | None = MODELS, **headers: str) -> dict[str, Any]:
    auth = service_headers(api.tenant, service="models", scopes=scopes) if scopes is not None else {}
    r = await api.client.post("/v1/secrets/values", json={"names": names}, headers={**auth, **headers})
    return {"status": r.status_code, **r.json()}


async def test_a_service_reads_a_workspace_secret_and_the_audit_shows_it(api: Api, engine: AsyncEngine) -> None:
    await _secret(engine, api.tenant, "OPENAI_API_KEY", "sk-test-1")
    got = await values(api, ["OPENAI_API_KEY"])
    assert (got["status"], got["data"]["values"]) == (200, {"OPENAI_API_KEY": "sk-test-1"}), got
    used = [a for a in await SecretStore(engine).audit(api.tenant) if a["action"] == "used"]
    read = [(a["name"], a["actor"], a["tool"]) for a in used]
    assert read == [("OPENAI_API_KEY", "service:models", "secrets.values")], read


async def test_a_teams_own_secret_never_reaches_another_service(api: Api, engine: AsyncEngine) -> None:
    await _secret(engine, api.tenant, "FRAUD_KEY", "k-fraud", teams=["team_fraud"])
    got = await values(api, ["FRAUD_KEY"])
    assert (got["status"], got["error"]["code"]) == (403, "secret_out_of_scope"), got
    assert "k-fraud" not in str(got)
    assert not [a for a in await SecretStore(engine).audit(api.tenant) if a["action"] == "used"]


async def test_only_a_service_holding_the_scope_reads_values(api: Api, engine: AsyncEngine) -> None:
    await _secret(engine, api.tenant, "OPENAI_API_KEY", "sk-test-1")
    unscoped = await values(api, ["OPENAI_API_KEY"], scopes=[])
    assert (unscoped["status"], unscoped["error"]["code"]) == (403, "scope_required"), unscoped
    person = await values(api, ["OPENAI_API_KEY"], scopes=None, **{"X-Dev-User": "Sam Adeyemi"})
    assert person["status"] == 401, person
    assert not [a for a in await SecretStore(engine).audit(api.tenant) if a["action"] == "used"]


async def test_a_missing_secret_is_named_not_answered_empty(api: Api) -> None:
    got = await values(api, ["NO_SUCH_KEY"])
    assert (got["status"], "NO_SUCH_KEY" in got["error"]["message"]) == (404, True), got
