"""Every service's permission checks answer what the built-in roles grant, for every membership role, area and action
(c-147), and each answer is `ops_access.can`'s (c-149). Each cell calls the check the service runs on that route,
through the adapter that turns the verified principal into that service's caller: a check that asks `can` for the wrong
area or action fails the grid comparison, and a check that decides anything itself fails when `can` is made to refuse
everyone or allow everyone. It lives at the root because it imports every service's checks.

A membership role becomes built-in roles through `builtin_roles_for`, and the comparison is per team: a member of an
ordinary team, and a member of the Security team, where egress, secrets and storage are held."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ops_access import (
    ACTIONS,
    AREAS,
    BUILTIN_ROLES,
    CHAT_USER,
    MEMBER_ROLE_TO_BUILTIN,
    SECURITY_TEAM_ACTIONS,
    Access,
    Assignment,
    Scope,
    builtin_roles_for,
    can,
    scope_in,
)
from ops_agents.api.agent_registry import require_owner_or_admin
from ops_agents.api.auth import caller_of, require_builder
from ops_agents.api.auth import principal as agents_principal
from ops_agents.api.chat_budget import _may as chat_may  # pyright: ignore[reportPrivateUsage]
from ops_agents.api.chat_threads import may_read
from ops_agents.api.routers.memories import require_memory_access
from ops_documents.app import who as documents_who
from ops_files.app import storage_admin
from ops_files.app import who as files_who
from ops_identity import Principal
from ops_kb.app import who as kb_who
from ops_kb.service import KnowledgeService
from ops_platform.store.members import Actor
from ops_platform.store.roles import Holdings
from ops_platform.teams import Members
from ops_service_kit.errors import Forbidden
from ops_tools.callers import security_admin
from ops_tools.connections.service import connection_rights
from ops_tools.modules.directory import Team
from ops_tools.modules.service import Caller
from ops_tools.modules.service import _can as tools_can  # pyright: ignore[reportPrivateUsage]
from ops_tools.secrets.routes import may_write_secret

ROLES = ("admin", "builder", "approver", "viewer")
TEAM, SECURITY, OTHER = "team_ops", "team_security", "team_other"
ME, SOMEONE = "me@bank.test", "someone@bank.test"
NOW = "2026-10-17T00:00:00.000Z"
GRIDS = {r.id: r.grants for r in BUILTIN_ROLES}
NAMES = {r.id: r.name for r in BUILTIN_ROLES}

Verdict = Callable[[Principal], Scope | None]


def person(role: str, team: str) -> Principal:
    """What ops_identity resolves from a platform token for a person acting in `team`, as every service receives it."""
    return Principal(
        kind="person",
        sub="usr_me",
        email=ME,
        name="Me",
        tenant_id="ten_bank",
        team_id=team,
        team_ids=[team],
        roles={team: role},
        scopes=[],
        auth_method="session",
    )


def run[T](coro: Awaitable[T]) -> T:
    return asyncio.run(cast(Any, coro))


def passes(check: Callable[[], object]) -> bool:
    try:
        result = check()
        if asyncio.iscoroutine(result):
            run(result)
    except Forbidden:
        return False
    return True


def own_or_all(allowed: Callable[[str], bool]) -> Scope | None:
    """`all` when the check passes on someone else's record, `own` when only on the caller's own."""
    return "all" if allowed(SOMEONE) else "own" if allowed(ME) else None


def yes(ok: bool) -> Scope | None:
    return "all" if ok else None


# Every member: no service checks a role or an owner on these. A sweep of every service's source at HEAD for owner and
# role comparisons (`.email ==`, `owned_by(`, `.role ==`, `roles.get(`, `require_admin`) finds each rule this table
# calls and no other; chat reads are owner only and are not among these.
def open_to_members(_: Principal) -> Scope | None:
    return "all"


def nobody(_: Principal) -> Scope | None:
    return None


# agents-service: definition writes (c-115) and the delete of a shared skill or guardrail. c-147's evidence
# (.codeloop/evidence/147/red-grid.txt) holds the comparison with the role checks c-148 and c-149 replaced.
def agents_builder(area: str, action: str) -> Verdict:
    def verdict(p: Principal) -> Scope | None:
        me = run(agents_principal(p))
        return yes(passes(lambda: require_builder(me, area=area, team_id=p.team_id, action=action, what="it")))

    return verdict


def agents_system_edit(p: Principal) -> Scope | None:
    """Editing an agent provisioned as `system` (c-180) needs agents.manage as well as the edit."""
    me = run(agents_principal(p))
    return yes(
        passes(
            lambda: require_builder(me, area="agents", team_id=p.team_id, action="edit", what="it", protection="system")
        )
    )


def chat_owner(p: Principal) -> Scope | None:
    """A chat thread is read by whoever started it, whatever their role (chat_threads.chat_rows, chat_row)."""
    me = run(agents_principal(p))
    return own_or_all(lambda starter: may_read({"ownerEmail": starter}, me))


def memory_editor(p: Principal) -> Scope | None:
    """Memory correct and forget (routers/memories.py): memory.edit on memories whose subject is the caller."""
    me = run(agents_principal(p))
    return own_or_all(lambda subject: passes(lambda: require_memory_access(me, owner=subject, edit=True)))


def chat_budget_admin(p: Principal) -> Scope | None:
    # chat_budget.answer and run_api_answer: who may raise a spent chat's or run thread's budget.
    me = run(agents_principal(p))
    return yes(chat_may(me, "manage", str(p.team_id)))


def case_route(action: str) -> Verdict:
    """/v1/cases opens and works a case on `can(cases, <action>)` in the case's team (c-128)."""

    def verdict(p: Principal) -> Scope | None:
        me = run(agents_principal(p))
        return yes(passes(lambda: can(caller_of(me), "cases", action, team=str(p.team_id))))

    return verdict


def agents_owner_or_admin(p: Principal) -> Scope | None:
    me = run(agents_principal(p))
    return own_or_all(
        lambda creator: passes(
            lambda: require_owner_or_admin(me, area="skills", team_id=str(p.team_id), created_by=creator, what="x")
        )
    )


# kb-service: knowledge is the team's; create, change and delete are each a cell of the grid.
def kb_create(p: Principal) -> Scope | None:
    w = run(kb_who(p))
    return yes(passes(lambda: w.require_builder(w.team_id, "create a knowledge base", "create")))


class _Bases:
    """A knowledge base of the team the caller acts in, owned by `owner`."""

    def __init__(self, team: str, owner: str) -> None:
        self.team, self.owner = team, owner

    async def base(self, tenant_id: str, kb_id: str) -> dict[str, Any]:
        return {"id": kb_id, "team_id": self.team, "owner": self.owner, "name": "Policies"}


def kb_system_edit(p: Principal) -> Scope | None:
    """Editing a knowledge base provisioned as `system` (c-180) needs knowledge.manage as well as the edit."""
    w = run(kb_who(p))
    return yes(passes(lambda: w.require_builder(w.team_id, "change a system base", "edit", protection="system")))


def kb_change(step: str) -> Verdict:
    def verdict(p: Principal) -> Scope | None:
        w = run(kb_who(p))

        def allowed(owner: str) -> bool:
            service = KnowledgeService.__new__(KnowledgeService)
            service.store = cast(Any, _Bases(str(p.team_id), owner))
            return passes(lambda: service._changeable(w, "kb_1", step))  # pyright: ignore[reportPrivateUsage]

        return own_or_all(allowed)

    return verdict


# tools-service: each module step asks `_can` for its cell (create, edit, publish, delete, run; decide for approvals).
def tools_caller(p: Principal) -> Caller:
    return Caller(
        tenant_id=p.tenant_id,
        name=p.name,
        team=Team(id=str(p.team_id), name="Ops", owner_groups=(), scope="owned"),
        roles=dict(p.roles),
        team_role=p.role,
        verified=True,
        principal=p,
    )


def tools_step(area: str, action: str) -> Verdict:
    def verdict(p: Principal) -> Scope | None:
        return yes(passes(lambda: tools_can(tools_caller(p), area, action, what="modules", security_team=SECURITY)))

    return verdict


def tools_system_edit(p: Principal) -> Scope | None:
    """Editing a tool module provisioned as `system` (c-180) needs tools.manage as well as the edit."""
    caller = tools_caller(p)
    return yes(
        passes(lambda: tools_can(caller, "tools", "edit", what="it", security_team=SECURITY, protection="system"))
    )


def tools_security_admin(p: Principal) -> Scope | None:
    return yes(passes(lambda: security_admin(SECURITY)(p)))


def tools_team_secret(action: str) -> Verdict:
    """A secret scoped to the team the person acts in: written by that team (c-186), as the secrets routes check."""

    def verdict(p: Principal) -> Scope | None:
        return yes(passes(lambda: may_write_secret(p, action, [str(p.team_id)], security_team=SECURITY)))

    return verdict


# files-service: a legal hold needs an admin of the file's team; storage settings an admin of the Security team.
def files_legal_hold(p: Principal) -> Scope | None:
    # TenantFiles.set_legal_hold reads `admin_teams`, which `who` fills from can(files, manage).
    # A person's route: `who` reads no service action from the request's state.
    request = cast(Any, SimpleNamespace(state=SimpleNamespace()))
    w = run(files_who(p, request))
    return yes(w.team in w.admin_teams)


def files_storage(p: Principal) -> Scope | None:
    request = cast(Any, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(security_team=SECURITY))))
    return yes(passes(lambda: storage_admin(p, request)))


# documents-service: a person extracts with documents.run and keeps types and corrects fields with documents.edit.
def documents_check(action: str) -> Verdict:
    def verdict(p: Principal) -> Scope | None:
        request = cast(Any, SimpleNamespace(state=SimpleNamespace(documents_action=action)))
        try:
            w = run(documents_who(p, request))
        except Forbidden:
            return None
        return yes(w.edits) if action == "edit" else "all"

    return verdict


# tools-service connections (c-330): every change and sign-in is connections.manage, admins' by default.
def tools_connections(action: str) -> Verdict:
    def verdict(p: Principal) -> Scope | None:
        return yes(passes(lambda: connection_rights(p, action, security_team=SECURITY)))

    return verdict


# platform-service: members, invites and API keys (access.manage) and the audit log (audit.view), from the role
# assignments the database holds; here the assignments a membership is mirrored to.
class _Roles:
    def __init__(self, role: str, team: str) -> None:
        self.role, self.team = role, team

    async def holdings(self, tenant_id: str, user_id: str) -> Holdings:
        ids = builtin_roles_for(self.role, security_team=self.team == SECURITY)
        return Holdings(
            teams={self.team: "Ops"}, assignments=[Assignment(r, NAMES[r], self.team, "person") for r in ids]
        )

    async def version(self, tenant_id: str) -> int:
        return 1

    async def grids(self, tenant_id: str, role_ids: list[str]) -> dict[str, list[Any]]:
        return {}


def platform_admin(area: str, action: str) -> Verdict:
    def verdict(p: Principal) -> Scope | None:
        team = str(p.team_id)

        async def security_team_of(_tenant: str) -> str:
            return SECURITY

        # The workspace's security team is a tenant setting (c-208); the fake names the deployment's.
        store = cast(Any, SimpleNamespace(security_team=SECURITY, security_team_of=security_team_of, db=None))
        members = Members(store, roles=cast(Any, _Roles(p.role or "", team)))
        actor = Actor(p.tenant_id, team, p.sub, "req_1")
        return yes(passes(lambda: members.require_admin(actor, area, action)))

    return verdict


# c-122 rules: written in the shared tree and agreed (interview Q1-Q5) but not at HEAD, where these routes check team
# membership or separation of duties only. Each is the agreed answer until c-148 calls the c-122 functions here.
def c122_decides(p: Principal) -> Scope | None:
    return yes(p.role in ("approver", "admin"))


def c122_cancel(p: Principal) -> Scope | None:
    return "all" if p.role in ("approver", "admin") else "own"


TODAY: dict[tuple[str, str], Verdict] = {
    **{(area, "view"): open_to_members for area in AREAS if area not in ("settings", "audit", "chat", "memory")},
    ("chat", "view"): chat_owner,
    ("memory", "edit"): memory_editor,
    ("chat", "manage"): chat_budget_admin,
    ("cases", "decide"): chat_budget_admin,
    # publishReview is set through platform-service's PUT /v1/policies (c-214), on its reviews.manage cell.
    ("reviews", "manage"): platform_admin("reviews", "manage"),
    **{
        (area, action): agents_builder(area, "test" if action == "run" else action)
        for area in ("agents", "workflows", "skills", "guardrails", "widgets", "deployments")
        for action in ("create", "edit", "publish", "delete", "run")
    },
    ("skills", "delete"): agents_owner_or_admin,
    ("guardrails", "delete"): agents_owner_or_admin,
    ("skills", "run"): nobody,
    ("guardrails", "run"): nobody,
    ("widgets", "run"): nobody,
    ("deployments", "publish"): nobody,
    # No route deletes a widget (retire is an edit) or a deployment (pause is an edit, poll a run) at HEAD.
    ("widgets", "delete"): nobody,
    ("deployments", "delete"): nobody,
    **{(area, "decide"): c122_decides for area in ("agents", "workflows", "skills", "guardrails", "widgets")},
    ("chat", "run"): open_to_members,
    ("chat", "decide"): c122_decides,
    ("reviews", "decide"): c122_decides,
    ("cases", "manage"): c122_cancel,
    ("cases", "create"): case_route("create"),
    ("cases", "edit"): case_route("edit"),
    ("knowledge", "create"): kb_create,
    ("knowledge", "edit"): kb_change("edit"),
    ("knowledge", "delete"): kb_change("delete"),
    **{("tools", action): tools_step("tools", action) for action in ("create", "edit", "publish", "delete", "run")},
    ("tools", "decide"): tools_step("tools", "decide"),
    # A record provisioned as `system` is changed only with the area's manage (c-180).
    ("agents", "manage"): agents_system_edit,
    ("tools", "manage"): tools_system_edit,
    ("knowledge", "manage"): kb_system_edit,
    **{("secrets_egress", action): tools_team_secret(action) for action in ("create", "edit", "delete")},
    ("secrets_egress", "manage"): tools_security_admin,
    ("secrets_egress", "decide"): tools_step("secrets_egress", "decide"),
    ("connections", "view"): tools_connections("view"),
    ("connections", "manage"): tools_connections("manage"),
    ("files", "create"): open_to_members,
    ("files", "delete"): open_to_members,
    ("files", "manage"): files_legal_hold,
    **{("documents", action): documents_check(action) for action in ("view", "edit", "run")},
    ("settings", "view"): files_storage,
    ("settings", "manage"): files_storage,
    **{("access", action): platform_admin("access", action) for action in ("create", "edit", "delete", "manage")},
    ("audit", "view"): platform_admin("audit", "view"),
}

CELLS = [(area, action) for area in AREAS for action in ACTIONS]


def granted(role: str, team: str, area: str, action: str) -> Scope | None:
    """What the built-in roles a membership maps to grant, in the team the service evaluates the action in."""
    assignments = [
        Assignment(r, NAMES[r], team, "person") for r in builtin_roles_for(role, security_team=team == SECURITY)
    ]
    where = SECURITY if (area, action) in SECURITY_TEAM_ACTIONS else team
    scope = scope_in(assignments, GRIDS, team=where, area=area, action=action, now=NOW)
    # can() caps a chat read at one's own while chatThreadsOwnerOnly is on, its default (c-186).
    return "own" if scope == "all" and (area, action) == ("chat", "view") else scope


@pytest.mark.parametrize("team", [TEAM, SECURITY])
@pytest.mark.parametrize("role", ROLES)
def test_builtin_grid_equals_todays_checks(role: str, team: str) -> None:
    """Every cell a service checks gives each role what the grid says. A cell no service checks yet is the admin's
    alone (owner, 2026-10-17: admins hold every cell), so a later check on it opens to admins first."""
    wrong: list[str] = []
    for area, action in CELLS:
        if TODAY.get((area, action), nobody) is nobody:
            if role != "admin" and granted(role, team, area, action) is not None:
                wrong.append(f"{area}.{action}: no service checks it, grid {granted(role, team, area, action)}")
            continue
        today = TODAY[(area, action)](person(role, team))
        grid = granted(role, team, area, action)
        if today != grid:
            wrong.append(f"{area}.{action}: today {today}, grid {grid}")
    assert wrong == []


def test_every_check_names_a_catalogue_cell() -> None:
    assert set(TODAY) <= set(CELLS)


def test_a_role_in_another_team_grants_nothing_in_the_security_team() -> None:
    """An admin of an ordinary team does not change egress: the check reads the Security team's role."""
    assert tools_security_admin(person("admin", OTHER)) is None
    assert granted("admin", OTHER, "secrets_egress", "manage") is None


def test_chat_user_only_chats_and_sees_its_own_threads() -> None:
    """Owner decision 2026-10-17: chat with the team's published agents (`chat.run`, which `open_to_members` allows
    every member today) and read only one's own threads; no other area, so no agents, workflows, knowledge or settings
    beyond what chat needs. Only the membership role a first SSO sign-in writes maps to it (c-188); the role
    migration's frozen mapping does not, so the migration granted it to nobody."""
    assignments = [Assignment(CHAT_USER.id, CHAT_USER.name, TEAM, "person")]
    held = {
        (area, action): scope
        for area, action in CELLS
        if (scope := scope_in(assignments, GRIDS, team=TEAM, area=area, action=action, now=NOW)) is not None
    }
    # And corrects or forgets what agents remember about them (c-206), their own memory only.
    assert held == {("chat", "view"): "own", ("chat", "run"): "all", ("memory", "edit"): "own"}
    assert TODAY[("chat", "run")](person("viewer", TEAM)) == "all"
    assert TODAY[("chat", "view")](person("admin", TEAM)) == "own"
    assert [m for m, r in MEMBER_ROLE_TO_BUILTIN.items() if r == CHAT_USER.id] == ["chat_user"]
    assert builtin_roles_for("chat_user", security_team=True) == (CHAT_USER.id,)


# Cells no service decides with a role: every member, nobody, or a c-122 rule c-186 moves onto `can`.
NOT_BY_CAN = (open_to_members, nobody, c122_decides, c122_cancel)


@pytest.mark.parametrize("answer", ["refuse", "allow"])
def test_each_check_decides_through_can(answer: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """With `can` refusing everyone an admin is refused by every check, and with it allowing everyone a viewer passes
    every check: no check decides on a role or an owner itself, before or after asking `can` (c-149)."""

    def decided(self: Access, p: Principal, area: str, action: str, **_: Any) -> Scope:
        if answer == "refuse":
            raise Forbidden("refused", code="role_required")
        return "all"

    monkeypatch.setattr(Access, "can", decided)
    who, want = (person("admin", TEAM), None) if answer == "refuse" else (person("viewer", TEAM), "all")
    wrong = [
        f"{area}.{action}: {got}"
        for (area, action), check in TODAY.items()
        if check not in NOT_BY_CAN and (got := check(who)) != want
    ]
    assert wrong == []
