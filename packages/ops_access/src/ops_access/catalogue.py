"""Roles as data: the fixed catalogue of areas and actions, the five seeded roles people are given (`SEEDED_ROLES`),
the two grids attached by rule (Security admin, Owner), and how a person's assignments add up to what they may do in
each team.

Areas and actions are fixed in code; a role is a set of (area, action, scope) rows over them, and scope `own` means only
records the person created or owns. A role is given through assignments, each in one team or in every team
(`ANY_TEAM`), to a person, a team or a group the person is in. What they may do in a team is the union of the
unexpired assignments that apply there; `all` beats `own` when two roles grant the same action. A group's assignment
never carries a privileged cell (`PRIVILEGED`, `privileged_cells`).

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
    # Saved test cases and their runs on agents, skills and workflows, and the Evals page that reads them: every team
    # role but chat user reads; `run` (save cases, run them) is the builders' and admins'.
    "evals",
    "knowledge",
    "tools",
    "secrets_egress",
    # How the platform signs in to each system: every member reads them; `manage` (create, change, set secret
    # parts, sign in) is the admins' by default.
    "connections",
    "files",
    # What documents-service reads from a file: document types, extractions, corrections. `run` extracts;
    # `edit` keeps types and corrects fields; `delete` purges what was derived from a deleted file (a workflow asks).
    "documents",
    "chat",
    # What agents remember about a person: edited (corrected or forgotten) by that person only.
    "memory",
    "reviews",
    # The team's approval rules: who answers before an agent changes an app, and whether whoever asked may also
    # decide, per area. `manage` is held in the team (a team admin by default, tickable on a custom role), inside the
    # floor the Security team sets (`approvalsFloor`).
    "approvals",
    "cases",
    "deployments",
    "settings",
    "access",
    "audit",
    # The team's activity log of tool calls: who called which tool, as whom, and what came back (tools-service
    # GET /v1/executions). It names people, so viewers do not read it; reviewers, builders and admins do.
    "activity",
    # The calls made through the team's MCP links (a link's Calls tab, tools-service GET /v1/executions?link=): every
    # member reads the calls they made themselves (`own`); builders and admins read everyone's.
    "mcp",
    # The team's webhooks (endpoint addresses and delivery history) and its usage and cost: team-admin data, held by
    # admins only by default.
    "webhooks",
    "usage",
    # The workspace itself: `manage` transfers, closes and restores it. Only Owner holds it, one person per
    # workspace, moved only by a transfer; Admin's every-cell grid leaves it out.
    "workspace",
)
ACTIONS = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
Scope = Literal["all", "own"]
SCOPES: tuple[Scope, ...] = ("all", "own")

# An assignment whose team is this applies in every team its subject belongs to.
ANY_TEAM = "*"

# These are held in the workspace's Security team (its record, named in the token) whichever team the request acts
# in: the egress list and workspace-wide secrets (`manage`), a module's security review and storage settings decide
# what every team's tools may reach, so a role in any other team grants none of them (tools-service `security_admin`,
# files-service `storage_admin`). A team's own secrets are created, edited and deleted in that team; the
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
    (area, "view", "all")
    for area in AREAS
    if area not in ("settings", "audit", "activity", "mcp", "webhooks", "usage", "chat", "memory", "workspace")
]
_DEFINITIONS = ("agents", "workflows", "skills", "guardrails", "widgets", "tools")
# Decided by a reviewer or admin of the reviewing team; a module access approval by an approver or admin of the
# acting team (tools-service `_needs_role(who, APPROVES, ...)`).
_DECIDES: list[Grant] = [(area, "decide", "all") for area in (*_DEFINITIONS, "chat", "reviews")]
# Anyone in the team uploads, deletes an unreferenced file and chats with the team's agents; the creator of a skill or
# guardrail deletes it and the starter of a run cancels it, whatever their role now.
_MEMBER: list[Grant] = [
    *_all("files", "create", "delete"),
    # Anyone in the team reads a file into fields and keeps the team's document types and samples.
    *_all("documents", "edit", "run"),
    ("chat", "run", "all"),
    ("chat", "view", "own"),
    ("memory", "edit", "own"),
    ("mcp", "view", "own"),
    ("skills", "delete", "own"),
    ("guardrails", "delete", "own"),
    ("cases", "manage", "own"),
    # Anyone in the team opens a case and works it: status, assignee, notes. Closing it is cases.manage.
    *_all("cases", "create", "edit"),
]
# Builders do everything in their team except people and access, the workspace's settings, and the team's webhooks and
# usage, which stay team-admin data (D59): connections, secrets and auth configs included, which builders read
# (`_READS`) and admins change. What agents remember about a person stays that person's to edit.
_NOT_BUILDERS = (
    "access", "settings", "workspace", "webhooks", "usage", "connections", "secrets_egress", "approvals"
)  # fmt: skip
_BUILDS: list[Grant] = [
    (area, action, "own" if (area, action) == ("memory", "edit") else "all")
    for area in AREAS
    if area not in _NOT_BUILDERS
    for action in ACTIONS
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
    # Every area and action; the description is shown to people on Access, Roles.
    "Everything in the team: every area and action. Actions held in the Security team still need a role there.",
    # Admins read the team's chat threads only where the workspace turns chatThreadsOwnerOnly off (can() caps the
    # read at their own while it is on); what agents remember about a person is that person's to edit.
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
    "Everything in the team except people and access and the workspace's settings.",
    _merge(_READS, _MEMBER, _BUILDS),
)
REVIEWER = BuiltinRole(
    "reviewer",
    "Reviewer",
    "Reads the team's work and decides its reviews; in the Security team, decides module security reviews.",
    _merge(
        _READS, _MEMBER, _DECIDES, _all("cases", "manage"), _all("secrets_egress", "decide"), _all("activity", "view")
    ),
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
        _all("activity", "view"),
    ),
)
# A person who only chats. It chats with the agents published to its team and sees only its
# own threads. It is granted on its own, or as the membership role `chat_user`, given like any other membership role:
# by a first SSO sign-in, an invite or a role change (`INVITE_ROLES`).
CHAT_USER = BuiltinRole(
    "chat_user",
    "Chat user",
    "Chats with the agents published to the team and sees only their own threads; nothing else.",
    _merge([("chat", "view", "own"), ("chat", "run", "all"), ("memory", "edit", "own")]),
)
# The workspace's one owner, assigned in every team (`ANY_TEAM`) to its first admin
# and moved only by a transfer. It holds the workspace cell and nothing else; the owner is an account admin as well.
OWNER = BuiltinRole(
    "owner",
    "Owner",
    "Transfers, closes and restores the workspace. One person holds it, and only a transfer moves it.",
    (("workspace", "manage", "all"),),
)
BUILTIN_ROLES = (ADMIN, BUILDER, REVIEWER, VIEWER, SECURITY_ADMIN, CHAT_USER, OWNER)
BUILTIN_IDS = frozenset(r.id for r in BUILTIN_ROLES)
# The roles a new workspace starts with and people are given, each editable and reset to this seed. Security admin and
# Owner are seeded too but attached by rule, never picked: Security admin comes with Admin of the Security team, Owner
# with the workspace's one owner.
SEEDED_ROLES = (ADMIN, BUILDER, REVIEWER, VIEWER, CHAT_USER)
# The built-in roles whose cells are never edited: Admin holds every cell, and Security admin and Owner, attached by
# rule, carry privileged cells (`PRIVILEGED`), so an edit could never widen them safely and emptying one would only
# hide what the seed still grants. Reset still puts any of them back to its seed.
FIXED_ROLES = frozenset({ADMIN.id, SECURITY_ADMIN.id, OWNER.id})

# Cells a group's assignment never carries, so editing a group at the identity provider never makes anyone an admin:
# changing who may do what (every `access` action but reading it, which every member holds), the workspace itself, and
# what every team may reach (the Security team's actions, and the team's secrets beyond reading the list).
# `secrets_egress.decide` (a module's security review) counts only where it grants something, in the Security team or
# every team, so a group may still give Reviewer in an ordinary team.
PRIVILEGED = frozenset(
    {
        *(("access", action) for action in ACTIONS if action != "view"),
        ("workspace", "manage"),
        ("secrets_egress", "create"),
        ("secrets_egress", "edit"),
        ("secrets_egress", "delete"),
        *SECURITY_TEAM_ACTIONS,
    }
)
_ONLY_IN_SECURITY_TEAM = frozenset({("secrets_egress", "decide")})


def privileged_cells(grants: Iterable[Grant], *, team: str, security_team: str | None) -> list[str]:
    """The privileged cells (`area.action`) a role would carry if a group were given it in `team` (a team id or
    `ANY_TEAM`); empty when a group may be given it there."""
    where_it_counts = team in (ANY_TEAM, security_team)
    return sorted(
        {
            f"{a}.{x}"
            for a, x, _ in grants
            if (a, x) in PRIVILEGED and ((a, x) not in _ONLY_IN_SECURITY_TEAM or where_it_counts)
        }
    )


# members.role to the built-in role it becomes; the stored value `approver` is shown as Reviewer.
MEMBER_ROLE_TO_BUILTIN = {
    "admin": "admin",
    "builder": "builder",
    "approver": "reviewer",
    "viewer": "viewer",
    "chat_user": "chat_user",
}
# The membership roles an invite or a role change may give: every stored value, Chat user among them.
INVITE_ROLES = tuple(MEMBER_ROLE_TO_BUILTIN)
# The membership roles by rank, lowest first. Where two rules give one person different roles in a team (sign-in group
# rules), the higher one wins; Reviewer (`approver`) outranks Builder, and admin is the highest.
MEMBER_ROLES_BY_RANK = ("chat_user", "viewer", "builder", "approver", "admin")


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
    via: Literal["person", "team", "group"]
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


# A grid as a token carries it: area to the actions it grants, one letter each, upper case for `own`, so a person's
# roles fit in the token every service reads (a full grid is about 300 characters).
_LETTER = {
    "view": "v",
    "create": "c",
    "edit": "e",
    "publish": "p",
    "delete": "d",
    "run": "r",
    "decide": "x",
    "manage": "m",
}
_ACTION_OF = {v: k for k, v in _LETTER.items()}


def encode_grid(grants: Iterable[Grant]) -> dict[str, str]:
    out: dict[str, str] = {}
    for area, action, scope in grants:
        letter = _LETTER[action]
        out[area] = out.get(area, "") + (letter.upper() if scope == "own" else letter)
    return out


def decode_grid(claim: Mapping[str, str]) -> tuple[Grant, ...]:
    """The grants an encoded grid holds; an area or letter outside the catalogue is left out."""
    out: list[Grant] = []
    for area, letters in claim.items():
        if area not in AREAS:
            continue
        for ch in str(letters):
            action = _ACTION_OF.get(ch.lower())
            if action is not None:
                out.append((area, action, "own" if ch.isupper() else "all"))
    return tuple(out)
