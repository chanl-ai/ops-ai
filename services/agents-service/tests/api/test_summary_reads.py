"""The one-route summary reads (overview, activity, team and knowledge usage, prompt variables, model aliases, health
and the Reviews list), by failure mode: a reply, status or error code changing as the routes move onto the shared
request and list contract, and a route reading only this service's rows taking a connection per store call, so one
answer mixes rows from different moments. Regenerate the pins only for an intended change: `AGENTS_REPIN=1` writes
what the routes answer now to `fixtures/reply-pins-summary-reads.json`."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from ops_agents.api.agent_registry import SEED_TEAM
from ops_agents.api.deps import Runtime
from ops_identity import dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S

from .test_graphs import thread
from .test_hitl_facade import paused_dispute, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_reply_pins import FIXTURES, answer, compare

# A service caller as (service, scopes, team); None is the dev person.
Caller = tuple[str, tuple[str, ...], str] | None
KB: Caller = ("kb", ("agents:view",), SEED_TEAM)
PLATFORM: Caller = ("platform", ("workflows:view",), SEED_TEAM)
PERSON: Caller = None


def headers(caller: Caller) -> dict[str, str]:
    """Minted when the request is sent, so a long parallel run never sends an expired token."""
    if caller is None:
        return {}
    name, scopes, team = caller
    token = mint_service_token(
        dev_service_signer(),
        service=name,
        audience="agents",
        tenant_id="local",
        scopes=list(scopes),
        team_id=team,
        ttl_s=TEST_TOKEN_TTL_S,
    )
    return {"Authorization": f"Bearer {token}"}


# (name, path, caller): each answered value by value.
PINNED: list[tuple[str, str, Caller]] = [
    ("overview", "/v1/overview", PERSON),
    ("activity", "/v1/activity", PERSON),
    ("activity.pastEnd", "/v1/activity?page=999&pageSize=10", PERSON),
    ("activity.pageSizeOver", "/v1/activity?pageSize=101", PERSON),
    ("activity.badSource", "/v1/activity?source=nowhere", PERSON),
    ("activity.otherTeam", "/v1/activity?team=team_nobody", PERSON),
    ("teamUsage", "/v1/teams/usage", PLATFORM),
    ("teamUsage.noScope", "/v1/teams/usage", ("platform", (), SEED_TEAM)),
    ("promptVariables", "/v1/prompts/variables", PERSON),
    ("modelAliases", "/v1/model-aliases", PERSON),
    ("knowledgeUsage", "/v1/knowledge-usage", KB),
    ("knowledgeUsage.ids", "/v1/knowledge-usage?ids=kb_legal&ids=kb_nowhere", KB),
    ("knowledgeUsage.person", "/v1/knowledge-usage", PERSON),
    ("knowledgeUsage.otherTeam", "/v1/knowledge-usage", ("kb", ("agents:view",), "team_nobody")),
    ("knowledgeUsage.noScope", "/v1/knowledge-usage", ("kb", (), SEED_TEAM)),
    ("health", "/health", PERSON),
    ("reviews", "/reviews?view=all", PERSON),
    ("reviews.pastEnd", "/reviews?view=all&page=999", PERSON),
    ("reviews.badView", "/reviews?view=bogus", PERSON),
    ("reviews.badGroup", "/reviews?group=bogus", PERSON),
]


async def test_the_summary_reads_keep_every_key_value_and_error_object(client: AsyncClient) -> None:
    seen: dict[str, Any] = {}
    for name, path, caller in PINNED:
        seen[name] = answer(await client.get(path, headers=headers(caller)))
    compare(seen, FIXTURES / "reply-pins-summary-reads.json")


# (path, caller, connections the request checks out). One: the route answers in the request transaction. Zero: it
# reads nothing from the database. More: it calls another service, so each read takes and returns its own connection
# and none is held while the other service answers.
CHECKOUTS: list[tuple[str, Caller, int]] = [
    ("/v1/teams/usage", PLATFORM, 1),
    ("/v1/knowledge-usage", KB, 1),
    ("/v1/activity", PERSON, 3),
    ("/v1/model-aliases", PERSON, 0),
    ("/v1/prompts/variables", PERSON, 0),
    ("/health", PERSON, 1),
]


async def test_each_summary_read_checks_out_the_connections_it_should(client: AsyncClient) -> None:
    request_task = asyncio.current_task()
    counted: list[int] = []

    def checked_out(*_: object) -> None:
        # The app's loops check out connections too; only the request's own task counts.
        if asyncio.current_task() is request_task:
            counted[-1] += 1

    event.listen(Pool, "checkout", checked_out)
    seen: list[tuple[str, int, int]] = []
    try:
        for path, caller, _ in CHECKOUTS:
            counted.append(0)
            r = await client.get(path, headers=headers(caller))
            seen.append((path, r.status_code, counted[-1]))
    finally:
        event.remove(Pool, "checkout", checked_out)
    assert seen == [(p, 200, n) for p, _, n in CHECKOUTS], seen


async def test_the_reviews_list_reads_at_most_its_cap_from_a_source(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list merges its sources before paging, so an unbounded source would read every review a team ever had; and
    the cap keeps open reviews, so newer threads waiting on nobody never push one off."""
    client, rt = stack
    for _ in range(3):
        await paused_dispute(client)
    for _ in range(2):
        await thread(client, "complex_workflow")
    monkeypatch.setattr(rt, "settings", rt.settings.model_copy(update={"review_list_rows_per_source": 2}))
    r = await client.get("/reviews?view=all")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["pagination"]["total"] == 2, r.text
