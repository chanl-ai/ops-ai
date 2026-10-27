"""Another service asks the Secrets store for a credential (c-221, for c-177's model provider keys), by failure mode: a
team's secret reaching another service, a service without `secrets_egress:run` or a person asking, and a missing secret
answered as if it were empty. Every secret belongs to a team (c-509), so the route serves none; provider keys get their
own account-level store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_policy import AesGcmCipher, context_of
from ops_service_kit.settings import Settings
from ops_tools.store.secrets import SecretStore

from .conftest import Api, service_headers

MODELS = ["secrets_egress:run"]


async def _secret(engine: AsyncEngine, tenant: str, team: str, name: str, value: str) -> None:
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    blob = cipher.encrypt(value, context=context_of(tenant, name))
    assert await SecretStore(engine).create(tenant, team, name, blob, actor="Sam Adeyemi", at=datetime.now(UTC))


async def values(api: Api, names: list[str], *, scopes: list[str] | None = MODELS, **headers: str) -> dict[str, Any]:
    auth = service_headers(api.tenant, service="models", scopes=scopes) if scopes is not None else {}
    r = await api.client.post("/v1/secrets/values", json={"names": names}, headers={**auth, **headers})
    return {"status": r.status_code, **r.json()}


async def test_a_teams_secret_never_reaches_another_service(api: Api, engine: AsyncEngine) -> None:
    await _secret(engine, api.tenant, "team_fraud", "FRAUD_KEY", "k-fraud")
    got = await values(api, ["FRAUD_KEY"])
    assert got["status"] == 404 and "k-fraud" not in str(got), got
    assert not [a for a in await SecretStore(engine).audit(api.tenant, "team_fraud") if a["action"] == "used"]


async def test_only_a_service_holding_the_scope_asks(api: Api) -> None:
    unscoped = await values(api, ["OPENAI_API_KEY"], scopes=[])
    assert (unscoped["status"], unscoped["error"]["code"]) == (403, "scope_required"), unscoped
    person = await values(api, ["OPENAI_API_KEY"], scopes=None, **{"X-Dev-User": "Sam Adeyemi"})
    assert person["status"] == 401, person


async def test_a_missing_secret_is_named_not_answered_empty(api: Api) -> None:
    got = await values(api, ["NO_SUCH_KEY"])
    assert (got["status"], "NO_SUCH_KEY" in got["error"]["message"]) == (404, True), got
