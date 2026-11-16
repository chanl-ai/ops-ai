"""The one-route summary reads (overview, activity, team and knowledge usage, prompt variables, model aliases, health
and the Reviews list), by failure mode: a reply, status or error code changing as the routes move onto the shared
request and list contract, and a route reading only this service's rows taking a connection per store call, so one
answer mixes rows from different moments. Regenerate the pins only for an intended change: `AGENTS_REPIN=1` writes
what the routes answer now to `fixtures/reply-pins-summary-reads.json`."""

from __future__ import annotations

import asyncio
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from ops_agents.api.agent_registry import SEED_TEAM
from ops_identity import dev_service_signer, mint_service_token

from .test_reply_pins import FIXTURES, answer, compare


def service(name: str, scopes: list[str], team: str | None = SEED_TEAM) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service=name, audience="agents", tenant_id="local", scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


KB = service("kb", ["agents:view"])
PLATFORM = service("platform", ["workflows:view"])
PERSON: dict[str, str] = {}

# (name, path, caller): each answered value by value.
PINNED: list[tuple[str, str, dict[str, str]]] = [
    ("overview", "/v1/overview", PERSON),
    ("activity", "/v1/activity", PERSON),
    ("activity.pastEnd", "/v1/activity?page=999&pageSize=10", PERSON),
    ("activity.pageSizeOver", "/v1/activity?pageSize=101", PERSON),
    ("activity.badSource", "/v1/activity?source=nowhere", PERSON),
    ("activity.otherTeam", "/v1/activity?team=team_nobody", PERSON),
    ("teamUsage", "/v1/teams/usage", PLATFORM),
    ("teamUsage.noScope", "/v1/teams/usage", service("platform", [])),
    ("promptVariables", "/v1/prompts/variables", PERSON),
    ("modelAliases", "/v1/model-aliases", PERSON),
    ("knowledgeUsage", "/v1/knowledge-usage", KB),
    ("knowledgeUsage.person", "/v1/knowledge-usage", PERSON),
    ("knowledgeUsage.otherTeam", "/v1/knowledge-usage", service("kb", ["agents:view"], "team_nobody")),
    ("knowledgeUsage.noScope", "/v1/knowledge-usage", service("kb", [])),
    ("health", "/health", PERSON),
    ("reviews", "/reviews?view=all", PERSON),
    ("reviews.pastEnd", "/reviews?view=all&page=999", PERSON),
    ("reviews.badView", "/reviews?view=bogus", PERSON),
    ("reviews.badGroup", "/reviews?group=bogus", PERSON),
]


async def test_the_summary_reads_keep_every_key_value_and_error_object(client: AsyncClient) -> None:
    seen: dict[str, Any] = {}
    for name, path, headers in PINNED:
        seen[name] = answer(await client.get(path, headers=headers))
    compare(seen, FIXTURES / "reply-pins-summary-reads.json")


# (path, caller, connections the request checks out). One: the route answers in the request transaction. Zero: it
# reads nothing from the database. More: it calls another service, so each read takes and returns its own connection
# and none is held while the other service answers.
CHECKOUTS: list[tuple[str, dict[str, str], int]] = [
    ("/v1/teams/usage", PLATFORM, 5),
    ("/v1/knowledge-usage", KB, 4),
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
        for path, headers, _ in CHECKOUTS:
            counted.append(0)
            r = await client.get(path, headers=headers)
            seen.append((path, r.status_code, counted[-1]))
    finally:
        event.remove(Pool, "checkout", checked_out)
    assert seen == [(p, 200, n) for p, _, n in CHECKOUTS], seen
