"""The publish check on account names: each account a workflow step or an agent names must be one of its team's live
accounts of that app. Names are compared by tools-service (`GET /v1/apps/{app}/accounts?usable=1&name=`), never here,
so the rule for what counts as the same name has one owner. A rename in tools-service never rewrites a definition: a
published version keeps its name and is refused at the call (ACCOUNT_NOT_FOUND) until its next publish, which this
check stops until the name is changed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from ops_engine.store import DefinitionStore
from ops_service_kit.errors import Unprocessable

from ..activities.tool_directory import ToolsUnavailable
from ..store.engine import EngineTransactions
from .agent_registry import registry as agent_registry
from .deps import Runtime

# The engine's tool step, whose `accounts` parameter names an account per app.
TOOL_STEP = "ops.action.tool"


def step_names(definition: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(step label or id, app id, account name) for each account the definition's tool steps name."""
    out: list[tuple[str, str, str]] = []
    for node in cast(list[dict[str, Any]], definition.get("nodes") or []):
        if str(node.get("type") or "").split("@")[0] != TOOL_STEP:
            continue
        params = cast(dict[str, Any], node.get("parameters") or {})
        where = str(node.get("label") or node.get("name") or node.get("id") or "a step")
        for app, name in cast(dict[str, Any], params.get("accounts") or {}).items():
            if isinstance(name, str) and name.strip():
                out.append((where, str(app), name.strip()))
    return out


async def require_team_accounts(rt: Runtime, team: str, named: Iterable[tuple[str, str, str]]) -> None:
    """Refuses (422 account_name_unknown, naming each step) when any account named is not one of the team's live
    accounts of its app. While tools-service cannot answer the publish is refused rather than let through unchecked."""
    wanted = list(named)
    if not wanted:
        return
    if rt.app_states is None:
        raise Unprocessable("Accounts cannot be checked without the tools service.", code="accounts_unchecked")
    unknown: list[dict[str, str]] = []
    for where, app, name in wanted:
        try:
            found = await rt.app_states.accounts(None, team, app, usable=True, name=name)
        except ToolsUnavailable as e:
            raise Unprocessable(
                "The tools service cannot be reached, so the accounts this names cannot be checked.",
                code="accounts_unchecked",
            ) from e
        if not found:
            unknown.append({"step": where, "appId": app, "account": name})
    if unknown:
        first = unknown[0]
        more = f" and {len(unknown) - 1} more" if len(unknown) > 1 else ""
        raise Unprocessable(
            f"{first['step']} names {first['account']}, which is not one of the team's accounts of that app{more}. "
            "Pick another account, or rename the step's account to the new name.",
            code="account_name_unknown",
            details={"accounts": unknown},
        )


def uses_of(definitions: Iterable[tuple[str, Mapping[str, Any]]], app: str, name: str) -> list[str]:
    """The ids among `definitions` (id, definition) whose steps name `name` for `app`, compared trimmed and
    case-folded as tools-service compares them, for the rename warning's count."""
    key = name.strip().casefold()
    return [i for i, d in definitions if any(a == app and n.casefold() == key for _, a, n in step_names(d))]


async def account_uses_in(rt: Runtime, team: str, app: str, name: str) -> dict[str, Any]:
    """The team's workflow drafts and published versions, and agents, that name the account `name` of `app`: the
    counts and ids a rename warns with and a delete is refused with. Names compare trimmed and case-folded, as calls
    compare them."""
    store = DefinitionStore(EngineTransactions(rt.db))
    drafts = published = 0
    workflows: list[str] = []
    for row in await store.summaries(team=team):
        wid = str(row["workflow_id"])
        latest = uses_of([(wid, cast(dict[str, Any], row.get("definition") or {}))], app, name)
        live_version = row.get("current_version")
        live = await store.get(wid, int(live_version), team=team) if live_version else None
        named_live = bool(live and uses_of([(wid, cast(dict[str, Any], live["definition"]))], app, name))
        drafts += int(bool(latest) and row.get("stage") == "draft")
        published += int(named_live)
        if latest or named_live:
            workflows.append(wid)
    agents: list[str] = []
    reg = agent_registry(rt)
    key = name.strip().casefold()
    for a in await reg.rows():
        if a.get("team_id") != team:
            continue
        for v in await reg.versions(str(a["id"])):
            named = cast(dict[str, str], cast(dict[str, Any], v.get("spec") or {}).get("accounts") or {})
            if str(named.get(app) or "").strip().casefold() != key:
                continue
            is_live = a.get("published_version") is not None and int(v["version"]) <= int(a["published_version"])
            published += int(is_live)
            drafts += int(not is_live)
            if str(a["id"]) not in agents:
                agents.append(str(a["id"]))
    return {"drafts": drafts, "published": published, "workflows": workflows, "agents": agents}
