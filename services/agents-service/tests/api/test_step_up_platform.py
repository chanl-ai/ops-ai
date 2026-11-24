"""require_step_up under platform sign-in, by failure mode: a step-up platform-service issued for the deciding person
is accepted beside this service's own; one for someone else, an expired or stale one, a session token presented as a
step-up, and one under a key the shared Auth does not hold are each refused with the reason the console shows."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_agents.api.auth import require_step_up, step_up_ref, step_up_signer
from ops_agents.api.deps import Runtime
from ops_agents.store.tenancy import tenant_scope
from ops_identity.jwks import JwksCache
from ops_policy import Ed25519Signer, mint, mint_step_up
from ops_service_kit.errors import StepUpRequired
from ops_service_kit.settings import Settings
from tests.api.test_chat import new_thread, send
from tests.conftest import step_up

PLATFORM = Ed25519Signer.generate("platform-test")
MAYA = "m.okafor@harborpine.example"


def platform_step_up(email: str, *, now: float | None = None, ttl_s: int = 300, **extra: Any) -> str:
    """What platform-service's POST /v1/auth/step-up mints (ops_platform.auth.Auth.step_up)."""
    claims: dict[str, Any] = {
        "sub": "usr_approver",
        "sid": "ses_1",
        "email": email,
        "tenant_id": "local",
        "kind": "step_up",
        "typ": "step_up",
        "aud": ["platform", "agents"],
    }
    return mint(claims | extra, PLATFORM, ttl_s=ttl_s, now=now)


async def runtime(signer: Ed25519Signer = PLATFORM) -> Runtime:
    """A Runtime holding the key set as the shared Auth caches it after the caller's own token was verified."""

    async def jwks() -> dict[str, Any]:
        return {"keys": [signer.public_jwk()]}

    keys = JwksCache(jwks, "agents")
    assert await keys.verifier(signer.kid) is not None
    return cast(Runtime, SimpleNamespace(settings=Settings(database_url="sqlite+aiosqlite://"), platform_keys=keys))


@pytest.fixture(autouse=True)
def local_tenant():
    with tenant_scope("local"):
        yield


async def test_a_platform_step_up_for_the_deciding_person_is_accepted() -> None:
    rt = await runtime()
    require_step_up(rt, MAYA, platform_step_up(MAYA))


async def test_this_services_own_step_up_is_still_accepted() -> None:
    rt = await runtime()
    require_step_up(rt, MAYA, mint_step_up(MAYA, step_up_signer(rt)))


async def test_a_platform_step_up_for_someone_else_is_refused() -> None:
    rt = await runtime()
    with pytest.raises(StepUpRequired, match="someone else"):
        require_step_up(rt, MAYA, platform_step_up("n.petrov@harborpine.example"))


async def test_a_platform_step_up_from_another_tenant_is_refused() -> None:
    rt = await runtime()
    with pytest.raises(StepUpRequired, match="someone else"):
        require_step_up(rt, MAYA, platform_step_up(MAYA, tenant_id="other"))


async def test_an_expired_or_stale_platform_step_up_is_refused() -> None:
    rt = await runtime()
    with pytest.raises(StepUpRequired, match="expired"):
        require_step_up(rt, MAYA, platform_step_up(MAYA, now=time.time() - 301))
    with pytest.raises(StepUpRequired, match="older than 5 minutes"):
        require_step_up(rt, MAYA, platform_step_up(MAYA, now=time.time() - 301, ttl_s=3600))


async def test_a_platform_session_token_is_not_a_step_up() -> None:
    rt = await runtime()
    session = mint(
        {"sub": "usr_approver", "email": MAYA, "tenant_id": "local", "kind": "person", "aud": ["agents"]},
        PLATFORM,
        ttl_s=900,
    )
    with pytest.raises(StepUpRequired, match="not a step-up"):
        require_step_up(rt, MAYA, session)


async def test_a_step_up_under_a_key_the_service_does_not_hold_is_refused() -> None:
    rt = await runtime(Ed25519Signer.generate("platform-other"))
    with pytest.raises(StepUpRequired, match="not issued by the identity service"):
        require_step_up(rt, MAYA, platform_step_up(MAYA))
    with pytest.raises(StepUpRequired, match="not issued by the identity service"):
        require_step_up(
            cast(Runtime, SimpleNamespace(settings=rt.settings, platform_keys=None)), MAYA, platform_step_up(MAYA)
        )


async def approval_widget(client: AsyncClient, content: str) -> tuple[str, str, dict[str, Any]]:
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": content})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    return thread["id"], url, widget


async def test_a_money_decision_records_the_fingerprint_of_its_step_up(client: AsyncClient) -> None:
    tid, url, widget = await approval_widget(client, "Place a 24-hour hold on wire W-88213")
    assert widget["stepUp"] is True
    token = await step_up(client)
    approved = await client.post(url, json={"type": "approve", "stepUpToken": token})
    assert approved.status_code == 200, approved.text
    review = (await client.get(f"/reviews/{tid}")).json()["data"]
    assert review["status"] == "approved"
    assert review["stepUpRef"] == step_up_ref(token)
    assert review["stepUpRef"] is not None and token not in review["stepUpRef"]


async def test_a_decision_that_needed_no_step_up_records_none(client: AsyncClient) -> None:
    tid, url, _ = await approval_widget(client, "Place a 24-hour hold on wire W-88213")
    rejected = await client.post(url, json={"type": "reject", "reason": "Not this one."})
    assert rejected.status_code == 200, rejected.text
    review = (await client.get(f"/reviews/{tid}")).json()["data"]
    assert review["status"] == "rejected" and review["stepUpRef"] is None
