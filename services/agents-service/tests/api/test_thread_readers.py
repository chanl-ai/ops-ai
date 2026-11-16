"""Who sees which thread on GET /v1/threads (`may_read_thread`), through the route on PostgreSQL: one row per reader
case the rule tells apart, with the exact thread ids each reader is shown. Holds the rule while it moves from Python
into the list's SQL: a scoped key reaches its own agent or workflow only; a chat thread (the chat graph) that names a
person, by `ownerEmail`, `startedFor` holding an email, `chat` or a legacy `owner` name, is read under chat.view (its
person, or a role holding chat.view at `all` when the workspace turns the owner-only policy off); any other thread
by the team rule. A service token is refused on the route."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_access import DEFAULT, Grant, Grids
from ops_agents.store.graphs import graph_threads
from ops_agents.store.tenancy import tenant_tx
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_service_kit.settings import Settings
from ops_store import isolation
from tests.api.test_action_roles import REVIEWER, introspect
from tests.conftest import SEED, FakeGraphModels, empty_engine, started
from tests.engine.test_lifecycle_rights import ADMIN, PLATFORM, TENANT, VIEWER, jwks, person

CHAT = "agent_wrapper"
VERA, OTTO = "vera@harborpine.example", "otto@harborpine.example"
KEY_EMAIL = "case-system@harborpine.example"
AT = "2026-11-16T09:00:00.000Z"

# id -> (graph, team, meta)
THREADS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "th_workflow": ("refunds", "team_ops", {"ownerEmail": VERA}),
    "th_other_workflow": ("payouts", "team_ops", {}),
    "th_agent": ("agent:ag_branch", "team_ops", {"ownerEmail": OTTO}),
    "th_chat_vera": (CHAT, "team_ops", {"chat": True, "ownerEmail": VERA, "owner": "vera"}),
    # Before chat reads became owner only, a chat named its owner by name alone.
    "th_chat_otto_by_name": (CHAT, "team_ops", {"chat": True, "owner": "otto"}),
    # An agent's call made for a person: the person it ran for owns it.
    "th_call_for_vera": (CHAT, "team_ops", {"startedFor": VERA}),
    # A run-API thread of the chat graph naming nobody is the team's; so is one whose startedFor is no email.
    "th_chat_nobody": (CHAT, "team_ops", {}),
    "th_chat_not_an_email": (CHAT, "team_ops", {"startedFor": "intake-bot"}),
    "th_chat_key": (CHAT, "team_ops", {"chat": True, "ownerEmail": KEY_EMAIL}),
    # One term alone makes a chat-graph thread a person's: `chat` names nobody, `owner` names otto.
    "th_chat_flag_only": (CHAT, "team_ops", {"chat": True}),
    "th_owner_name_only": (CHAT, "team_ops", {"owner": "otto"}),
    # ownerEmail wins over startedFor.
    "th_vera_started_for_otto": (CHAT, "team_ops", {"ownerEmail": VERA, "startedFor": OTTO}),
    # startedFor is not server-owned metadata, so a caller may store any JSON there; this one holds an @.
    "th_started_for_list": (CHAT, "team_ops", {"startedFor": [VERA]}),
    "th_lending": ("refunds", "team_lending", {"ownerEmail": "lena@harborpine.example"}),
}
TEAM_ROWS = ["th_workflow", "th_other_workflow", "th_agent", "th_chat_nobody", "th_chat_not_an_email"]


def chat_reader(policies: dict[str, Any] | None) -> dict[str, str]:
    """rita in team_ops on a custom role holding chat.view at `all`."""
    claims: dict[str, Any] = {
        "sub": "rita",
        "email": "rita@harborpine.example",
        "name": "rita",
        "kind": "person",
        "security_team": "team_security",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": ["team_ops"],
        "access": {"team_ops": ["chat_reader"]},
        "perm_version": 1,
        **({"policies": policies} if policies is not None else {}),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


def service(team: str) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="worker",
        audience="agents",
        tenant_id=TENANT,
        scopes=["cases:view"],
        team_id=team,
        ttl_s=TEST_TOKEN_TTL_S,
    )
    return {"Authorization": f"Bearer {token}"}


def key(name: str) -> dict[str, str]:
    return {"X-API-Key": f"ok_ops.{name}", "X-Team-Id": "team_ops"}


@pytest.fixture(autouse=True)
async def chat_reader_role(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch(_t: str, _v: int, _ids: list[str]) -> dict[str, Iterable[Grant]]:
        return {"chat_reader": [("chat", "view", "all")]}

    monkeypatch.setattr(DEFAULT, "grids", Grids(fetch=fetch))
    await DEFAULT.grids.load(TENANT, 1, ["chat_reader"])


@pytest.fixture
async def c(database_url: str) -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url=database_url, seed_dir=SEED)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes),
    )
    async with empty_engine(database_url) as engine:
        for thread_id, (graph, team, meta) in THREADS.items():
            with isolation.scope(TENANT, team):
                async with tenant_tx(engine) as conn:
                    await conn.execute(
                        graph_threads.insert().values(
                            id=thread_id,
                            graph=graph,
                            meta=meta,
                            team_id=team,
                            owner=meta.get("ownerEmail"),
                            created_at=AT,
                            updated_at=AT,
                            status="idle",
                        )
                    )
        async with started(engine, settings, FakeGraphModels(), auth=auth) as (_, client):
            yield client


READERS: list[tuple[str, dict[str, str], int, list[str]]] = [
    ("owner", VIEWER, 200, [*TEAM_ROWS, "th_chat_vera", "th_call_for_vera", "th_vera_started_for_otto"]),
    ("teammate", person("otto", "team_ops", "viewer"), 200, [*TEAM_ROWS, "th_chat_otto_by_name", "th_owner_name_only"]),
    ("admin", ADMIN, 200, TEAM_ROWS),
    ("reviewer", REVIEWER, 200, TEAM_ROWS),
    ("another team", person("lena", "team_lending", "admin"), 200, ["th_lending"]),
    # The owner-only policy is on unless the workspace turns it off.
    ("chat.view at all", chat_reader(None), 200, TEAM_ROWS),
    (
        "chat.view at all, owner-only policy off",
        chat_reader({"chatThreadsOwnerOnly": False}),
        200,
        [
            *TEAM_ROWS,
            "th_chat_vera",
            "th_chat_otto_by_name",
            "th_call_for_vera",
            "th_chat_key",
            "th_chat_flag_only",
            "th_owner_name_only",
            "th_vera_started_for_otto",
            # Its person is the list's text, which matches no one's email, so only a reader of every chat sees it.
            "th_started_for_list",
        ],
    ),
    ("key for a workflow", key("wf"), 200, ["th_workflow"]),
    ("key for an agent", key("agent"), 200, ["th_agent"]),
    ("unscoped key", key("k1"), 200, TEAM_ROWS),
    # The thread routes take people and keys; a service token is refused before the list is read.
    ("service of the team", service("team_ops"), 401, []),
]


async def test_each_reader_sees_exactly_the_threads_the_rule_gives_it(c: AsyncClient) -> None:
    seen: dict[str, tuple[int, list[str]]] = {}
    for name, headers, _, _ in READERS:
        r = await c.get("/v1/threads", headers=headers)
        body: Any = r.json().get("data") if r.status_code == 200 else None
        # A bare array today; the list contract's page once the list pages.
        rows = cast(list[dict[str, Any]], body["data"] if isinstance(body, dict) else body or [])
        seen[name] = (r.status_code, sorted(str(t["threadId"]) for t in rows))
    assert seen == {name: (status, sorted(ids)) for name, _, status, ids in READERS}
