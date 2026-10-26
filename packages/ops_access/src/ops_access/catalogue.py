"""Roles as data: the fixed catalogue of areas and actions, the six built-in roles, and how a person's assignments add
up to what they may do in each team.

Areas and actions are fixed in code; a role is a set of (area, action, scope) rows over them, and scope `own` means only
records the person created or owns. A person holds roles through assignments, each in one team or in every team they
belong to (`ANY_TEAM`), directly or through a team they are in. What they may do in a team is the union of the
unexpired assignments that apply there; `all` beats `own` when two roles grant the same action.

platform-service stores these rows and seeds the built-in roles from here (migrations 0006-0008 keep their own frozen
copy); every service decides with `ops_access.can`, which reads this module. The built-in grid equals what the
services' own checks allowed before they called `can` (`scripts/tests/test_builtin_roles_match_checks.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

AREAS = (
    "agents",
    "workflows",
    "skills",
    "guardrails",
    "widgets",
    "knowledge",
    "tools",
    "secrets_egress",
    # How the platform signs in to each system (c-330): every member reads them; `manage` (create, change, set secret
    # parts, sign in) is the admins' by default (owner, 2026-10-19).
    "connections",
    "files",
    # What documents-service reads from a file (c-256): document types, extractions, corrections. `run` extracts;
    # `edit` keeps types and corrects fields; `delete` purges what was derived from a deleted file (a workflow asks).
    "documents",
    "chat",
    # What agents remember about a person (c-206): edited (corrected or forgotten) by that person only.
    "memory",
    "reviews",
    "cases",
    "deployments",
    "settings",
    "access",
    "audit",
    # The workspace itself (c-529): `manage` transfers, closes and restores it. Only Owner holds it, one person per
    # workspace, moved only by a transfer; Admin's every-cell grid leaves it out.
    "workspace",
)
ACTIONS = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
Scope = Literal["all", "own"]
SCOPES: tuple[Scope, ...] = ("all", "own")

# An assignment whose team is this applies in every team its subject belongs to.
ANY_TEAM = "*"

# These are held in the Security team (settings `security_team_id`) whichever team the request acts in: the egress
# list and workspace-wide secrets (`manage`), a module's security review and storage settings decide what every team's
# tools may reach, so a role in any other team grants none of them (tools-service `security_admin`, files-service
# `storage_admin`). A team's own secrets are created, edited and deleted in that team (owner, 2026-10-17); the
# `securityTeamAddsSecrets` policy moves those writes back here.
SECURITY_TEAM_ACTIONS = frozenset(
    {
        ("secrets_egress", "manage"),
        ("secrets_egress", "decide"),
        ("settings", "view"),
        ("settings", "manage"),
    }
)

Grant = tuple[str, str, Scope]


def _all(area: str, *actions: str) -> list[Grant]:
    return [(area, action, "all") for action in actions]


# Every member reads these today: no service checks a role or owner on these reads. Chat is not one of them: a chat
# thread is read by the person who started it only, admins included (agents-service `chat_threads.owned_by`).
_READS: list[Grant] = [
    (area, "view", "all") for area in AREAS if area not in ("settings", "audit", "chat", "memory", "workspace")
]
_DEFINITIONS = ("agents", "workflows", "skills", "guardrails", "widgets", "tools")
# Decided by a reviewer or admin of the reviewing team (c-122); a module access approval by an approver or admin of the
# acting team (tools-service `_needs_role(who, APPROVES, ...)`).
_DECIDES: list[Grant] = [(area, "decide", "all") for area in (*_DEFINITIONS, "chat", "reviews")]
# Anyone in the team uploads, deletes an unreferenced file and chats with the team's agents; the creator of a skill or
# guardrail deletes it and the starter of a run cancels it, whatever their role now.
_MEMBER: list[Grant] = [
    *_all("files", "create", "delete"),
    # Anyone in the team reads a file into fields and keeps the team's document types and samples (c-256).
    *_all("documents", "edit", "run"),
    ("chat", "run", "all"),
    ("chat", "view", "own"),
    ("memory", "edit", "own"),
    ("skills", "delete", "own"),
    ("guardrails", "delete", "own"),
    ("cases", "manage", "own"),
    # Anyone in the team opens a case and works it: status, assignee, notes (c-128). Closing it is cases.manage.
    *_all("cases", "create", "edit"),
]
_BUILDS: list[Grant] = [
    *_all("agents", "create", "edit", "publish", "delete", "run"),
    *_all("workflows", "create", "edit", "publish", "delete", "run"),
    *_all("skills", "create", "edit", "publish"),
    *_all("guardrails", "create", "edit", "publish"),
    # A widget is retired (an edit), never deleted; a deployment is paused (an edit) or polled (a run), never deleted.
    *_all("widgets", "create", "edit", "publish"),
    *_all("tools", "create", "edit", "publish", "delete", "run"),
    *_all("deployments", "create", "edit", "run"),
    # Knowledge is shared by its team (owner, 2026-10-17): any builder changes the team's bases and sources.
    *_all("knowledge", "create", "edit", "delete"),
    # A team's secrets are its own (owner, 2026-10-17): its builders add, change and remove them.
    *_all("secrets_egress", "create", "edit", "delete"),
]


@dataclass(frozen=True)
class BuiltinRole:
    id: str
    name: str
    description: str
    grants: tuple[Grant, ...]


def _merge(*parts: Iterable[Grant]) -> tuple[Grant, ...]:
    """One row per (area, action), `all` kept over `own`, in catalogue order."""
    best: dict[tuple[str, str], Scope] = {}
    for area, action, scope in (g for part in parts for g in part):
        if best.get((area, action)) != "all":
            best[(area, action)] = scope
    order = {(a, x): (AREAS.index(a), ACTIONS.index(x)) for a in AREAS for x in ACTIONS}
    return tuple((a, x, s) for (a, x), s in sorted(best.items(), key=lambda kv: order[kv[0]]))


ADMIN = BuiltinRole(
    "admin",
    "Admin",
    # Every area and action (owner, 2026-10-17); the description is shown to people on Access, Roles.
    "Everything in the team: every area and action. Actions held in the Security team still need a role there.",
    # Admins read the team's chat threads only where the workspace turns chatThreadsOwnerOnly off (can() caps the
    # read at their own while it is on); what agents remember about a person is that person's to edit (c-206).
    tuple(
        (area, action, "own" if (area, action) == ("memory", "edit") else "all")
        for area in AREAS
        if area != "workspace"
        for action in ACTIONS
    ),
)
BUILDER = BuiltinRole(
    "builder",
    "Builder",
    "Reads the team's work, and creates, edits, tests and publishes its definitions.",
    _merge(_READS, _MEMBER, _BUILDS),
)
REVIEWER = BuiltinRole(
    "reviewer",
    "Reviewer",
    "Reads the team's work and decides its reviews; in the Security team, decides module security reviews.",
    _merge(_READS, _MEMBER, _DECIDES, _all("cases", "manage"), _all("secrets_egress", "decide")),
)
VIEWER = BuiltinRole(
    "viewer",
    "Viewer",
    "Reads the team's work and chats with its agents.",
    _merge(_READS, _MEMBER),
)
SECURITY_ADMIN = BuiltinRole(
    "security_admin",
    "Security admin",
    "Changes egress, secrets and storage settings for every team, and decides module security reviews.",
    _merge(
        _all("secrets_egress", "view", "create", "edit", "delete", "manage", "decide"),
        _all("settings", "view", "manage"),
    ),
)
# Owner decision 2026-10-17: a person who only chats. It chats with the agents published to its team and sees only its
# own threads. It is granted on its own, or as the membership role `chat_user` that a first SSO sign-in gives a person
# new to the workspace (c-188); no invite or role change can set that membership role.
CHAT_USER = BuiltinRole(
    "chat_user",
    "Chat user",
    "Chats with the agents published to the team and sees only their own threads; nothing else.",
    _merge([("chat", "view", "own"), ("chat", "run", "all"), ("memory", "edit", "own")]),
)
# Owner decision 2026-10-23 (c-529): the workspace's one owner, assigned in every team (`ANY_TEAM`) to its first admin
# and moved only by a transfer. It holds the workspace cell and nothing else; the owner is an account admin as well.
OWNER = BuiltinRole(
    "owner",
    "Owner",
    "Transfers, closes and restores the workspace. One person holds it, and only a transfer moves it.",
    (("workspace", "manage", "all"),),
)
BUILTIN_ROLES = (ADMIN, BUILDER, REVIEWER, VIEWER, SECURITY_ADMIN, CHAT_USER, OWNER)
BUILTIN_IDS = frozenset(r.id for r in BUILTIN_ROLES)

# members.role to the built-in role it becomes; the stored value `approver` is shown as Reviewer.
MEMBER_ROLE_TO_BUILTIN = {
    "admin": "admin",
    "builder": "builder",
    "approver": "reviewer",
    "viewer": "viewer",
    "chat_user": "chat_user",
}


def builtin_roles_for(member_role: str, *, security_team: bool) -> tuple[str, ...]:
    """The built-in roles a membership grants in its team. An admin of the Security team is also Security admin there,
    since that is who tools-service and files-service let change egress, secrets and storage today."""
    role = MEMBER_ROLE_TO_BUILTIN.get(member_role)
    if role is None:
        return ()
    return (role, SECURITY_ADMIN.id) if security_team and role == ADMIN.id else (role,)


@dataclass(frozen=True)
class Assignment:
    role_id: str
    role_name: str
    team_id: str  # a team id, or ANY_TEAM
    via: Literal["person", "team"]
    expires_at: str | None = None


@dataclass
class Granted:
    scope: Scope
    roles: list[dict[str, str]] = field(default_factory=list[dict[str, str]])


def active(assignments: Iterable[Assignment], now: str) -> list[Assignment]:
    """Unexpired assignments; ISO-8601 UTC strings compare in time order."""
    return [a for a in assignments if a.expires_at is None or a.expires_at > now]


def effective(
    assignments: Iterable[Assignment], grids: Mapping[str, Iterable[Grant]], teams: Iterable[str], now: str
) -> dict[str, dict[tuple[str, str], Granted]]:
    """Per team, every (area, action) the person may take, its widest scope, and each role that grants it. `teams` are
    the teams the person belongs to; an assignment in one team counts there even when they are not a member."""
    live = active(assignments, now)
    team_ids = list(dict.fromkeys([*teams, *(a.team_id for a in live if a.team_id != ANY_TEAM)]))
    out: dict[str, dict[tuple[str, str], Granted]] = {}
    for team in team_ids:
        held: dict[tuple[str, str], Granted] = {}
        for a in live:
            if a.team_id not in (team, ANY_TEAM):
                continue
            for area, action, scope in grids.get(a.role_id, ()):
                g = held.setdefault((area, action), Granted(scope))
                if scope == "all":
                    g.scope = "all"
                role = {"id": a.role_id, "name": a.role_name, "via": a.via}
                if role not in g.roles:
                    g.roles.append(role)
        out[team] = held
    return out


def scope_in(
    assignments: Iterable[Assignment],
    grids: Mapping[str, Iterable[Grant]],
    *,
    team: str,
    area: str,
    action: str,
    now: str,
) -> Scope | None:
    """The widest scope the person holds for one action in one team, or None."""
    g = effective(assignments, grids, [team], now).get(team, {}).get((area, action))
    return g.scope if g else None
