"""A person's connectors: one row per app that acts as them, for Connectors (Mine), the SDK and the CLI.

A row is an app, never an account: the person's own accounts of the app are a count with a primary, so two sign-ins to
the same app are one row. Each row says what the app can do as the person in one line, built from the tools the team
switched on (a write marked when it waits for a person's approval), who it signs in as, its state, and where it is used
as counts. Its state is the app card's own `appState` for the caller (apps.py), the one answer every screen reads. An
app the install no longer loads is left out, and an installed app the team has off is listed when it signs in as each
person, so the person can ask for it; an app that only ever signs in as the team does not act as anyone and is not
listed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import Field

from ops_service_kit.errors import ServiceUnavailable
from ops_service_kit.http import Out

from .app_states import AppGroup, AppState
from .connections.service import own_key
from .modules.policy import app_ids

if TYPE_CHECKING:
    from .apps import Apps
    from .modules.service import Caller

# The order rows are listed in, by who acts next: what works, what needs the person, what needs an admin.
RANK: dict[str, int] = {"on": 0, "needs_you": 1, "needs_admin": 2}
PERSON_SIGN_INS = ("person", "person_or_team")
# The window "tool calls this week" counts.
WEEK = timedelta(days=7)
# How many tool titles the one line names before it counts the rest.
NAMED = 2


class ConnectorTool(Out):
    name: str
    title: str
    access: str
    # A write that waits for a person's approval before anything changes: its own flag or the team's policy.
    reviewed: bool = False


class ConnectorAccount(Out):
    # The team's account (a connection) the person signed in to; Connect, Test and Disconnect act on it.
    connection_id: str
    name: str
    # Whom the system says signed in, from the sign-in itself; None until it named someone.
    account: str | None = None
    state: Literal["connected", "expired", "not_connected"]
    since: str | None = None
    # The person's default account of the app (their saved one, or their only one): calls naming no account use it.
    # With two connected and none saved, no account is the default and a call asks which.
    primary: bool = False


class ConnectorUse(Out):
    agents: int = 0
    workflows: int = 0
    # Calls made as this person through the app in the last seven days.
    calls_this_week: int = 0


class MyConnector(Out):
    """One app that acts as the caller, as Connectors (Mine) lists it."""

    app_id: str
    name: str
    logo: str | None = None
    # The app card's state for the caller and why, as GET /v1/apps answers it.
    app_state: AppState
    app_state_reason: str | None = None
    app_group: AppGroup
    # What it can do as the person, in one line, from the app's switched-on tools.
    can_do: str
    tools: list[ConnectorTool]
    # The primary account: the person's chosen default, else the team's default account, else the first.
    primary_account_id: str | None = None
    account: str | None = None
    since: str | None = None
    account_count: int = 0
    accounts: list[ConnectorAccount]
    # How the person signs in: the kind's label, and what they give for a key kind (empty for a sign-in).
    method: str | None = None
    auth_kind: str | None = None
    person_fields: list[str] = Field(default_factory=list[str])
    # Where the system says how to find a key, for a kind whose person gives their own.
    docs_url: str | None = None
    # The auth config the sign-in goes through, chosen by the team's admin.
    auth_config: str | None = None
    used: ConnectorUse
    # On in a new chat: every connected connector is (owner, 8 November); a chat narrows it in its picker.
    in_chat: bool = False
    # The caller manages the team's apps, so the row offers the app's next team step (Turn on, an auth config) instead
    # of asking an admin.
    may_manage: bool = False


def listed(titles: list[str]) -> str:
    """Titles as one phrase: "A and B", or "A, B and 3 more"."""
    if len(titles) <= NAMED:
        return " and ".join(titles)
    return f"{', '.join(titles[:NAMED])} and {len(titles) - NAMED} more"


def can_do(tools: list[dict[str, Any]]) -> str:
    """The row's one line: its reads, then its writes with the ones that wait for approval said so."""
    reads = [str(t["title"]) for t in tools if t["access"] == "read"]
    writes = [t for t in tools if t["access"] != "read"]
    parts: list[str] = []
    if reads:
        parts.append(f"Reads: {listed(reads)}")
    if writes:
        if all(t["reviewed"] for t in writes):
            parts.append(f"Writes, reviewed first: {listed([str(t['title']) for t in writes])}")
        else:
            shown = [f"{t['title']} (reviewed first)" if t["reviewed"] else str(t["title"]) for t in writes]
            parts.append(f"Writes: {listed(shown)}")
    return " · ".join(parts) or "No tools switched on yet"


async def _policy(apps: Apps, who: Caller) -> tuple[bool, list[str] | None]:
    """The team's write policies, read once per page: whether every write waits, and the apps whose writes do (None
    when the list cannot be read, which counts as listed, as the gateway reads it)."""
    policy = apps.write_approvals
    if policy is None:
        return False, []
    every = await policy.all_writes(who.tenant_id, who.team.id)
    return every, [] if every else await policy.apps(who.tenant_id, who.team.id)


async def _reviewed(
    apps: Apps, who: Caller, tools: list[dict[str, Any]], policy: tuple[bool, list[str] | None]
) -> list[dict[str, Any]]:
    """Each tool with whether its write waits: its own flag, or the team's policy (every write, or this app's)."""
    every, listed_apps = policy
    out: list[dict[str, Any]] = []
    for t in tools:
        waits = bool(t["waits"]) or every
        if not waits and t["access"] != "read" and apps.write_approvals is not None:
            module = await apps.modules.get(who.tenant_id, str(t["moduleId"]))
            waits = listed_apps is None or (module is not None and bool(app_ids(module) & set(listed_apps)))
        out.append({**t, "reviewed": t["access"] != "read" and waits})
    return out


async def _used(apps: Apps, who: Caller, tools: list[dict[str, Any]], modules: list[str]) -> dict[str, int]:
    agents: set[str] = set()
    flows: set[str] = set()
    if apps.users is not None and tools:
        try:
            uses = await apps.users.of(who.tenant_id, who.team.id, [str(t["name"]) for t in tools])
        except ServiceUnavailable:
            uses = {}
        for found in uses.values():
            for u in found:
                (agents if u["kind"] == "agent" else flows).add(str(u["id"]))
    calls = 0
    email = who.principal.email if who.principal else None
    if apps.calls is not None and email:
        since = (datetime.now(UTC) - WEEK).isoformat()
        made = await apps.calls.calls.made_for(email, modules, since, tenant_id=who.tenant_id, team_id=who.team.id)
        calls = sum(made.values())
    return {"agents": len(agents), "workflows": len(flows), "callsThisWeek": calls}


def _primary(accounts: list[dict[str, Any]], team_default: str | None, saved: set[str]) -> dict[str, Any] | None:
    """The account the row's actions act on: the person's saved default, else the team's default, else the first."""
    connected = [a for a in accounts if a["state"] == "connected"] or accounts
    return (
        next((a for a in connected if a["connectionId"] in saved), None)
        or next((a for a in connected if a["connectionId"] == team_default), None)
        or (connected[0] if connected else None)
    )


async def my_connectors(apps: Apps, who: Caller) -> list[dict[str, Any]]:
    """The caller's connectors in their team, one row per app, joined here so the page makes one call."""
    cards = await apps.cards(who, listed=True, builtins=False)
    mine = await apps.connections.mine(who, every=True)
    # Which account the person saved as their default, from their own sign-ins (the gateway reads the same).
    signed = await apps.connections.store.own_sign_ins(
        who.tenant_id, own_key(who), [str(m["connectionId"]) for m in mine]
    )
    by_app: dict[str, list[dict[str, Any]]] = {}
    for m in mine:
        by_app.setdefault(str(m["appId"]), []).append(m)
    may = apps.connections.may_manage(who)
    policy = await _policy(apps, who)
    rows: list[dict[str, Any]] = []
    for card in cards:
        plugin = cast(dict[str, Any] | None, card.get("plugin"))
        if card["kind"] == "plugin" and plugin is None:
            continue  # the install no longer loads it, so nothing of it can run
        own = by_app.get(str(card["id"]), [])
        off = plugin is not None and not plugin["teamOn"]
        signs_in = set(cast(list[str], (plugin or {}).get("signIn") or []))
        if off and not signs_in & set(PERSON_SIGN_INS):
            continue
        if not off and not own:
            continue  # it signs in as the team only, so it never acts as the person
        tools = await apps_tools(apps, who, card)
        # Nothing is switched on while the app is off: say what it reads once turned on.
        tools = [t for t in tools if t["access"] == "read"] if off else [t for t in tools if t["added"]]
        tools = await _reviewed(apps, who, tools, policy)
        accounts = [] if off else own
        saved = {str(t["connection_id"]) for t in signed if t.get("pinned")}
        live = [a for a in accounts if a["state"] == "connected"]
        # The default the gateway uses: the saved one, or the only one; two and none saved is no default (it asks).
        defaults = saved & {a["connectionId"] for a in live} or ({live[0]["connectionId"]} if len(live) == 1 else set())
        first = _primary(accounts, card.get("connectionId"), saved)
        state = cast(AppState, card["appState"])
        rows.append(
            MyConnector(
                app_id=str(card["id"]),
                name=str(card["name"]),
                logo=card.get("logo"),
                app_state=state,
                app_state_reason=card.get("appStateReason"),
                app_group=card["appGroup"],
                can_do=can_do(tools),
                tools=[ConnectorTool(**{k: t[k] for k in ("name", "title", "access", "reviewed")}) for t in tools],
                primary_account_id=first["connectionId"] if first else None,
                account=first.get("account") if first else None,
                since=first.get("since") if first and first["state"] == "connected" else None,
                account_count=sum(a["state"] == "connected" for a in accounts),
                accounts=[
                    ConnectorAccount(
                        connection_id=a["connectionId"],
                        name=a["connection"],
                        account=a.get("account"),
                        state=a["state"],
                        since=a.get("since"),
                        primary=a["connectionId"] in defaults,
                    )
                    for a in accounts
                ],
                method=first["method"] if first else card.get("kindLabel"),
                auth_kind=first["authKind"] if first else card.get("authKind"),
                person_fields=list(first["personFields"]) if first else [],
                docs_url=first.get("docsUrl") if first else None,
                # Which auth config the person signs in through is for whoever manages the team's apps.
                auth_config=first.get("authConfig") if first and may else None,
                used=ConnectorUse(**await _used(apps, who, tools, list(card["moduleIds"]))),
                in_chat=card["appGroup"] == "on",
                may_manage=may,
            ).model_dump(by_alias=True)
        )
    return sorted(rows, key=lambda r: (RANK.get(r["appGroup"], 3), str(r["name"]).lower()))


async def apps_tools(apps: Apps, who: Caller, card: dict[str, Any]) -> list[dict[str, Any]]:
    from .apps import app_tools  # noqa: PLC0415 - apps imports this module's route

    return await app_tools(apps, who, card)
