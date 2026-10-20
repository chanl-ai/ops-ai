"""`can` by failure mode (c-148): a role a person does not hold in the record's team passing; a record of another
team passing because the person holds the role there; a Security team action passing for an admin of another team, or
refused to a Security admin acting in another team; `own` scope passing on someone else's record; an API key doing
more than start a live run and cancel its own; a service token without the scope; the requester deciding; a token
issued before the `access` claim losing its access; a custom role's grid fetched on every check or kept past a new
version. Principals come from real tokens through `ops_identity`, not built by hand."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from ops_access import Access, Grant, Grids, check_value, publish_mode, require_provisioner
from ops_identity import Identity, Principal, ServiceAuth, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.errors import Forbidden

ISSUER = Ed25519Signer.generate("platform-1")
SERVICES = Ed25519Signer.generate("services-1")
ACCESS = Access(security_team="team_security")


class _Request:
    method = "POST"


async def person(team: str = "team_a", **claims: Any) -> Principal:
    """What a service gets from a platform token, resolved by ops_identity as every service resolves it."""
    body: dict[str, Any] = {
        "sub": "usr_1",
        "email": "a@bank.test",
        "name": "Ana",
        "tenant_id": "ten_a",
        "team_ids": ["team_a", "team_security"],
        "roles": {"team_a": "builder"},
        "kind": "person",
        "auth_method": "session",
        "aud": ["agents"],
        **claims,
    }
    token = mint(body, ISSUER, ttl_s=TEST_TOKEN_TTL_S)

    async def jwks() -> dict[str, Any]:
        return {"keys": [ISSUER.public_jwk()]}

    async def no_keys(_key: str) -> dict[str, Any] | None:
        return None

    identity = Identity(audience="agents", jwks=jwks, introspect=no_keys)
    return await identity.principal(_Request(), authorization=f"Bearer {token}", x_team_id=team)  # pyright: ignore[reportArgumentType]


def refused(code: str, fn: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(Forbidden) as e:
        fn(*args, **kwargs)
    assert e.value.code == code, e.value.message


async def test_a_role_is_held_in_the_records_team_only() -> None:
    p = await person(access={"team_a": ["builder"]}, perm_version=3)
    assert p.access == {"team_a": ["builder"]} and p.permission_version == 3
    assert ACCESS.can(p, "agents", "edit", team="team_a") == "all"
    refused("role_required", ACCESS.can, p, "agents", "decide", team="team_a")
    refused("team_forbidden", ACCESS.can, p, "agents", "edit", team="team_b")


async def test_security_team_actions_are_held_in_the_security_team() -> None:
    admin_elsewhere = await person(access={"team_a": ["admin"]})
    refused("role_required", ACCESS.can, admin_elsewhere, "secrets_egress", "manage")
    security_admin = await person(access={"team_a": ["viewer"], "team_security": ["admin", "security_admin"]})
    # Acting in team_a, the Security admin still changes egress: the action is held in the Security team.
    assert security_admin.team_id == "team_a"
    assert ACCESS.can(security_admin, "secrets_egress", "manage") == "all"
    reviewer_elsewhere = await person(access={"team_a": ["reviewer"]})
    refused("role_required", ACCESS.can, reviewer_elsewhere, "secrets_egress", "decide")


async def test_own_scope_passes_on_the_callers_record_only() -> None:
    p = await person(access={"team_a": ["builder"]})
    # chat.view is own-scope for every built-in role: a person reads the threads they started.
    assert ACCESS.can(p, "chat", "view", team="team_a", owner="A@bank.test") == "own"
    refused("role_required", ACCESS.can, p, "chat", "view", team="team_a", owner="someone@bank.test")


async def test_the_requester_does_not_decide() -> None:
    p = await person(access={"team_a": ["reviewer"]})
    assert ACCESS.can(p, "reviews", "decide", team="team_a", not_by=["b@bank.test"]) == "all"
    refused("own_request", ACCESS.can, p, "reviews", "decide", team="team_a", not_by=[None, "a@bank.test"])


async def test_the_requester_decides_unless_the_tenant_switched_requester_may_decide_off() -> None:
    open_ = await person(access={"team_a": ["reviewer"]})
    assert ACCESS.can(open_, "reviews", "decide", team="team_a", requested_by=["a@bank.test"]) == "all"
    strict = await person(access={"team_a": ["reviewer"]}, policies={"requesterMayDecide": False})
    assert ACCESS.can(strict, "reviews", "decide", team="team_a", requested_by=["b@bank.test"]) == "all"
    refused("own_request", ACCESS.can, strict, "reviews", "decide", team="team_a", requested_by=["a@bank.test"])
    refused("own_request", ACCESS.can, strict, "reviews", "decide", team="team_a", requested_by=[None, "usr_1"])
    dev = Principal(
        kind="person",
        sub="usr_dev",
        email="dana@bank.test",
        name="Dana",
        tenant_id="local",
        team_id="team_ops",
        team_ids=["team_ops"],
        roles={},
        scopes=[],
        auth_method="dev",
        policies={"requesterMayDecide": False},
    )
    refused("own_request", ACCESS.can, dev, "reviews", "decide", requested_by=["dana@bank.test"])


async def test_a_token_without_the_access_claim_maps_its_membership_roles() -> None:
    p = await person(roles={"team_a": "approver"})
    assert p.access == {}
    assert ACCESS.can(p, "reviews", "decide", team="team_a") == "all"
    refused("role_required", ACCESS.can, p, "agents", "edit", team="team_a")
    admin = await person(team="team_security", roles={"team_security": "admin"})
    assert ACCESS.can(admin, "secrets_egress", "manage") == "all"


def key(team: str = "team_a") -> Principal:
    return Principal(
        kind="api_key",
        sub="usr_1",
        email="ci@bank.test",
        name="ci",
        tenant_id="ten_a",
        team_id=team,
        team_ids=[team],
        roles={},
        scopes=["write"],
        auth_method="api_key",
    )


def test_an_api_key_starts_live_runs_and_cancels_its_own_only() -> None:
    k = key()
    assert ACCESS.can(k, "workflows", "run", team="team_a") == "all"
    assert ACCESS.can(k, "cases", "manage", team="team_a", owner="ci@bank.test") == "own"
    refused("role_required", ACCESS.can, k, "cases", "manage", team="team_a", owner="ana@bank.test")
    refused("role_required", ACCESS.can, k, "workflows", "edit", team="team_a")
    refused("role_required", ACCESS.can, k, "reviews", "decide", team="team_a")
    refused("team_forbidden", ACCESS.can, k, "workflows", "run", team="team_b")


async def test_a_service_needs_the_scope_its_token_lists() -> None:
    auth = ServiceAuth(
        audience="kb",
        verifiers={SERVICES.kid: (SERVICES.verifier("kb"), "agents")},
        scopes={"agents": ["knowledge:view"]},
    )
    token = mint_service_token(
        SERVICES, service="agents", audience="kb", tenant_id="ten_a", scopes=["knowledge:view"], team_id="team_a"
    )
    svc = await auth.principal(authorization=f"Bearer {token}")
    assert svc.scopes == ["knowledge:view"] and svc.team_id == "team_a"
    assert ACCESS.can(svc, "knowledge", "view", team="team_a") == "all"
    refused("scope_required", ACCESS.can, svc, "knowledge", "edit", team="team_a")
    refused("team_forbidden", ACCESS.can, svc, "knowledge", "view", team="team_b")


async def test_a_custom_roles_grid_is_fetched_once_per_version() -> None:
    calls: list[tuple[str, int, list[str]]] = []

    async def fetch(tenant: str, version: int, role_ids: list[str]) -> dict[str, Iterable[Grant]]:
        calls.append((tenant, version, role_ids))
        return {"role_ops_lead": [("agents", "decide", "all")] if version == 1 else []}

    access = Access(grids=Grids(fetch=fetch))
    p1 = await person(access={"team_a": ["role_ops_lead"]}, perm_version=1)
    await access.grids.load(p1.tenant_id, p1.permission_version, access.roles_in(p1, "team_a"))
    await access.grids.load(p1.tenant_id, p1.permission_version, access.roles_in(p1, "team_a"))
    assert access.can(p1, "agents", "decide", team="team_a") == "all"
    assert len(calls) == 1
    p2 = await person(access={"team_a": ["role_ops_lead"]}, perm_version=2)
    refused("role_required", access.can, p2, "agents", "decide", team="team_a")
    await access.grids.load(p2.tenant_id, p2.permission_version, access.roles_in(p2, "team_a"))
    assert len(calls) == 2
    refused("role_required", access.can, p2, "agents", "decide", team="team_a")


def test_an_unknown_area_or_action_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        ACCESS.can(key(), "agent", "edit")


async def test_a_decision_reads_the_role_in_the_reviewing_team_from_any_team() -> None:
    p = await person(access={"team_a": ["viewer"], "team_security": ["reviewer"]})
    assert p.team_id == "team_a"
    refused("team_forbidden", ACCESS.can, p, "reviews", "decide", team="team_security")
    assert ACCESS.can(p, "reviews", "decide", team="team_security", from_any_team=True) == "all"
    refused("role_required", ACCESS.can, p, "reviews", "decide", team="team_a", from_any_team=True)


async def test_a_service_token_with_no_team_acts_on_no_teams_record() -> None:
    auth = ServiceAuth(
        audience="files",
        verifiers={SERVICES.kid: (SERVICES.verifier("files"), None)},
        scopes={"scanner": ["files:decide"]},
    )
    token = mint_service_token(
        SERVICES, service="scanner", audience="files", tenant_id="ten_a", scopes=["files:decide"]
    )
    scanner = await auth.principal(authorization=f"Bearer {token}")
    assert scanner.team_id is None
    assert ACCESS.can(scanner, "files", "decide") == "all"
    refused("team_required", ACCESS.can, scanner, "files", "decide", team="team_a")


async def _provisioner(scopes: list[str]) -> Principal:
    auth = ServiceAuth(
        audience="agents",
        verifiers={SERVICES.kid: (SERVICES.verifier("agents"), "platform")},
        scopes={"platform": ["agents:provision", "agents:edit", "agents:delete"]},
    )
    token = mint_service_token(
        SERVICES, service="platform", audience="agents", tenant_id="ten_a", scopes=scopes, team_id="team_a"
    )
    return await auth.principal(authorization=f"Bearer {token}")


async def test_a_system_record_is_changed_by_an_admin_or_the_provisioner_not_a_builder() -> None:
    builder = await person(access={"team_a": ["builder"]})
    refused("system_record", ACCESS.can, builder, "agents", "edit", team="team_a", protection="system")
    refused("system_record", ACCESS.can, builder, "agents", "delete", team="team_a", protection="system")
    assert ACCESS.can(builder, "agents", "view", team="team_a", protection="system") == "all"
    assert ACCESS.can(builder, "agents", "edit", team="team_a", protection="managed") == "all"
    admin = await person(access={"team_a": ["admin"]})
    assert ACCESS.can(admin, "agents", "edit", team="team_a", protection="system") == "all"
    assert ACCESS.can(admin, "agents", "delete", team="team_a", protection="system") == "all"
    svc = await _provisioner(["agents:edit", "agents:delete"])
    assert ACCESS.can(svc, "agents", "edit", team="team_a", protection="system") == "all"


async def test_only_a_provisioner_sets_template_fields() -> None:
    refused("provisioner_only", require_provisioner, await person(access={"team_a": ["admin"]}), "agents")
    refused("provisioner_only", require_provisioner, await _provisioner(["agents:edit"]), "agents")
    require_provisioner(await _provisioner(["agents:provision"]), "agents")


async def test_may_answers_from_the_same_grid_as_can() -> None:
    builder = await person(access={"team_a": ["builder"]})
    assert ACCESS.may(builder, "agents", "edit", team="team_a") is True
    assert ACCESS.may(builder, "access", "manage", team="team_a") is False
    # A role held in every team (`*`) answers in a team where the person holds nothing else.
    admin = await person(access={"*": ["admin"]})
    assert ACCESS.may(admin, "agents", "delete", team="team_a") is True


async def test_security_actions_are_held_in_the_workspaces_own_security_team() -> None:
    """A workspace whose security team is not the deployment's (c-202): the token names it, and only a role there
    holds the Security team's actions."""
    teams = {"team_ops": ["admin"], "team_sec2": ["admin"]}
    p = await person("team_ops", team_ids=["team_ops", "team_sec2"], access=teams, security_team="team_sec2")
    assert ACCESS.can(p, "settings", "manage") == "all"
    deployments_team = await person(
        "team_ops",
        team_ids=["team_ops", "team_security"],
        access={"team_ops": ["admin"], "team_security": ["admin"]},
        security_team="team_sec2",
    )
    refused("role_required", ACCESS.can, deployments_team, "settings", "manage")


async def test_a_role_that_reads_all_chats_reads_its_own_while_the_workspace_keeps_them_private() -> None:
    """chatThreadsOwnerOnly (on by default) caps a chat read at one's own whatever the grid grants; off, the grid
    decides (c-186)."""

    async def fetch(_t: str, _v: int, _ids: list[str]) -> dict[str, Iterable[Grant]]:
        return {"chat_reader": [("chat", "view", "all")]}

    access = Access(grids=Grids(fetch=fetch))
    private = await person(access={"team_a": ["chat_reader"]}, perm_version=1)
    await access.grids.load(private.tenant_id, private.permission_version, ["chat_reader"])
    assert access.can(private, "chat", "view", team="team_a", owner="a@bank.test") == "own"
    refused("role_required", access.can, private, "chat", "view", team="team_a", owner="someone@bank.test")
    shared = await person(access={"team_a": ["chat_reader"]}, perm_version=1, policies={"chatThreadsOwnerOnly": False})
    assert access.can(shared, "chat", "view", team="team_a", owner="someone@bank.test") == "all"


def test_a_publish_mode_is_read_per_team_and_defaults_to_major() -> None:
    modes = {"team_a": {"agents": "always"}}
    assert publish_mode(modes, "team_a", "agents") == "always"
    assert publish_mode(modes, "team_a", "skills") == "major"
    assert publish_mode(modes, "team_b", "agents") == "major"
    assert publish_mode({}, "team_a", "agents") == "major"
    assert check_value("publishReview", {"agents": "never"}) == {"agents": "never"}
    for bad in ({"agents": "sometimes"}, {"cases": "always"}, ["always"]):
        with pytest.raises(ValueError, match="publishReview"):
            check_value("publishReview", bad)
