"""Approval policies for an agent's changes to an app, through the policy routes, by failure mode: a new team asking
before anyone switched it on, or a switch saved without who answers; a reviewer answer nobody can give; the old keys
(toolWritesNeedApproval, appWritesNeedApproval, appsChangeWithoutAsking) drifting from the new ones during the release
they stay readable; a builder loosening an app below the team; and a team moved to the new default keeping an old
policy it never chose, or losing one a person saved."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from alembic import command

from ops_service_kit.ids import new_id, now_iso

from .conftest import SignInRig, alembic_config
from .test_policies import _team_admin, audit  # pyright: ignore[reportPrivateUsage]
from .test_role_migration import _rows, _run  # pyright: ignore[reportPrivateUsage]

SALESFORCE = "plugin:opsai.salesforce"
ZENDESK = "plugin:opsai.zendesk"


async def put(signin: SignInRig, key: str, value: Any, who: dict[str, str]) -> Any:
    return await signin.public.put(f"/v1/policies/{key}", json={"value": value}, headers=who)


async def get(signin: SignInRig, key: str, who: dict[str, str]) -> Any:
    r = await signin.public.get(f"/v1/policies/{key}", headers=who)
    assert r.status_code == 200, r.text
    return r.json()["data"]["value"]


async def test_a_new_team_asks_nobody_and_a_saved_switch_keeps_who_answers_and_is_audited(signin: SignInRig) -> None:
    team, admin = signin.admin["X-Team-Id"], signin.admin
    assert not any(v.get("ask") for v in (await get(signin, "appChanges", admin)).values())
    saved = await put(signin, "appChanges", {"ask": True, "answer": "person"}, admin)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["value"] == {
        team: {"ask": True, "answer": "person", "reviewerRole": None, "testAccountsNeverAsk": True}
    }
    assert [a for a in await audit(signin.engine, signin.tenant) if a[:2] == ("policy.set", "appChanges")], "no audit"


async def test_a_reviewer_answer_needs_a_role_that_can_approve(signin: SignInRig) -> None:
    admin = signin.admin
    none = await put(signin, "appChanges", {"ask": True, "answer": "reviewer", "reviewerRole": None}, admin)
    cannot = await put(signin, "appChanges", {"ask": True, "answer": "reviewer", "reviewerRole": "viewer"}, admin)
    assert [(r.status_code, r.json()["error"]["code"]) for r in (none, cannot)] == [
        (400, "reviewer_role_required"),
        (400, "role_cannot_approve"),
    ], (none.text, cannot.text)


async def test_the_old_keys_read_what_the_new_ones_say_and_their_writes_land_in_the_new_ones(signin: SignInRig) -> None:
    team, admin = signin.admin["X-Team-Id"], signin.admin
    # An old write becomes the new policy: on means a reviewer answers; off puts it back to the person, never to off.
    assert (await put(signin, "toolWritesNeedApproval", True, admin)).status_code == 200
    on = (await get(signin, "appChanges", admin))[team]
    assert (on["ask"], on["answer"]) == (True, "reviewer"), on
    assert (await put(signin, "toolWritesNeedApproval", False, admin)).status_code == 200
    back = (await get(signin, "appChanges", admin))[team]
    assert (back["ask"], back["answer"]) == (True, "person"), back
    # A new write shows in the old lists, which are derived from it.
    entries = {SALESFORCE: {"answer": "none"}, ZENDESK: {"answer": "reviewer", "reviewerRole": "reviewer"}}
    assert (await put(signin, "appChangesByApp", entries, admin)).status_code == 200
    assert (await get(signin, "appsChangeWithoutAsking", admin))[team] == [SALESFORCE]
    assert (await get(signin, "appWritesNeedApproval", admin))[team] == [ZENDESK]


async def test_a_builder_cannot_loosen_an_app_below_the_team(signin: SignInRig) -> None:
    team, admin = signin.admin["X-Team-Id"], signin.admin
    _, builder = await _team_admin(signin, "bea", role="builder")
    assert (await put(signin, "appChanges", {"ask": True, "answer": "person"}, admin)).status_code == 200
    loosened = await put(signin, "appChangesByApp", {SALESFORCE: {"answer": "none"}}, builder)
    assert loosened.status_code == 403, loosened.text
    assert (await put(signin, "appChangesByApp", {SALESFORCE: {"answer": "none"}}, admin)).status_code == 200
    assert (await get(signin, "appChangesByApp", admin))[team] == {SALESFORCE: {"answer": "none"}}


def test_a_team_moves_to_the_new_default_and_keeps_only_a_policy_a_person_saved(database_url: str) -> None:
    saved, untouched = new_id("ten"), new_id("ten")
    ops, desk = new_id("team"), new_id("team")
    now = now_iso()
    command.downgrade(alembic_config(), "0032_webhooks_usage_cells")
    try:
        tenant = (
            "INSERT INTO tenants (id, name, status, allowed_domains, created_at) VALUES (:t, :t, 'active', '[]', :now)"
        )
        team = "INSERT INTO teams (id, tenant_id, name, name_key, owner_groups, scope, created_at) "
        policy = (
            "INSERT INTO policies (tenant_id, key, value, updated_by, updated_at) "
            "VALUES (:t, :k, cast(:v as json), :by, :now)"
        )
        asyncio.run(
            _run(
                database_url,
                [
                    (tenant, {"t": saved, "now": now}),
                    (tenant, {"t": untouched, "now": now}),
                    (team + "VALUES (:id, :t, 'Ops', :id, '[]', 'owned', :now)", {"id": ops, "t": saved, "now": now}),
                    (
                        team + "VALUES (:id, :t, 'Desk', :id, '[]', 'owned', :now)",
                        {"id": desk, "t": untouched, "now": now},
                    ),
                    (
                        policy,
                        {
                            "t": saved,
                            "k": "toolWritesNeedApproval",
                            "v": json.dumps({ops: True}),
                            "by": "ada@x.example",
                            "now": now,
                        },
                    ),
                ],
            )
        )
    finally:
        command.upgrade(alembic_config(), "head")
    rows = asyncio.run(
        _rows(
            database_url,
            "SELECT tenant_id, key, value FROM policies WHERE key = 'appChanges' AND tenant_id IN (:a, :b)",
            {"a": saved, "b": untouched},
        )
    )
    by_tenant = {r[0]: r[2] for r in rows}
    assert by_tenant == {
        saved: {ops: {"ask": True, "answer": "reviewer", "reviewerRole": None, "testAccountsNeverAsk": True}}
    }
