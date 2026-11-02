"""A member removed from a team is reported to the services that hold their records there (c-616 S14), by failure mode:
the removal reports nothing, so tools-service keeps their own accounts on the team's apps; the report is written apart
from the removal, so one can commit without the other; and the relay sends it to a service that does not act on it, or
to none, or under another tenant or team than the removal's."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ops_platform.store.event_relay import sender
from ops_platform.store.tables import platform_outbox
from ops_platform.store.tenancy import ROLE
from ops_store.outbox import Relay

from .conftest import Platform, SignInRig
from .test_members import as_admin, join, member_rows


async def test_a_removal_reports_member_removed_with_the_person_and_team(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    builder = await join(platform, admin, "builder")
    [row] = await member_rows(platform, h, role="builder")
    r = await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [row["id"]]})
    assert r.json()["data"]["updated"] == [row["id"]], r.text
    async with platform.engine.connect() as c:
        found = (
            await c.execute(sa.select(platform_outbox).where(platform_outbox.c.tenant_id == admin.tenant_id))
        ).mappings()
        events = [dict(e) for e in found]
    assert [(e["name"], e["team_id"], e["payload"]) for e in events] == [
        ("member.removed", h["X-Team-Id"], {"personId": builder.user_id})
    ], events


class Client:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any], str, str]] = []

    async def post(self, path: str, body: dict[str, Any], *, tenant: str, team: str) -> dict[str, Any]:
        self.sent.append((path, body, tenant, team))
        return {}


async def test_the_relay_sends_each_event_to_the_services_that_act_on_it_in_its_tenant_and_team() -> None:
    tools, agents = Client(), Client()
    send = sender({"tools": tools, "agents": agents})  # pyright: ignore[reportArgumentType]
    body = {"name": "member.removed", "key": "mem_1:t", "teamId": "team_ops", "payload": {"personId": "usr_1"}}
    await send({"tenantId": "t_1", "body": body})
    await send({"tenantId": "t_1", "body": {**body, "name": "team.renamed"}})
    assert tools.sent == [("/v1/platform-events", body, "t_1", "team_ops")]
    assert agents.sent == []


async def test_the_relay_reads_the_outbox_as_this_service_and_delivers_the_removal(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    await join(platform, admin, "builder")
    [row] = await member_rows(platform, h, role="builder")
    await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [row["id"]]})
    tools = Client()
    delivered = await Relay(platform.engine, platform_outbox, sender({"tools": tools}), role=ROLE).once()  # pyright: ignore[reportArgumentType]
    assert delivered >= 1 and [s[1]["name"] for s in tools.sent if s[2] == admin.tenant_id] == ["member.removed"]


async def created(rig: SignInRig) -> set[str]:
    async with rig.engine.connect() as c:
        q = sa.select(platform_outbox.c.team_id).where(
            platform_outbox.c.tenant_id == rig.tenant, platform_outbox.c.name == "team.created"
        )
        return {str(t) for t in (await c.execute(q)).scalars()}


async def test_a_new_team_reports_team_created_in_the_transaction_that_makes_it(signin: SignInRig) -> None:
    # PV2 (c-616): each service writes the new team's defaults when it hears this; the relay sends it to tools-service
    # and agents-service.
    before = await created(signin)
    lead = f"lead@{signin.zone}"
    await signin.person(lead)
    made = await signin.public.post(
        "/v1/settings/teams", json={"name": "Claims desk", "admin": lead}, headers=signin.admin
    )
    assert made.status_code == 201, made.text
    team = str(made.json()["data"]["id"])
    assert await created(signin) - before == {team}
    tools, agents = Client(), Client()
    send = sender({"tools": tools, "agents": agents})  # pyright: ignore[reportArgumentType]
    await send({"tenantId": signin.tenant, "body": {"name": "team.created", "key": team, "teamId": team}})
    assert [s[3] for s in tools.sent] == [team] and [s[3] for s in agents.sent] == [team]
