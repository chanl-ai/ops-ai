"""A case assembled for its page (c-291, the approved case page design section 5): who owns it, its clocks, what it
waits on and the actions drafted there, its fields in its case type's order, what it links to, its newest activity and
what the caller may do. The console renders it and joins nothing. Every block reads in one query, or a capped number
of review views, whatever the case holds; nothing in here knows a use case."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote

from ops_access import can
from ops_engine.store import RunStore
from ops_service_kit.errors import Forbidden

from ..case_fields import fields_view, specs_of
from ..store.activity import Activity, Filters
from ..store.case_links import CaseLinks
from ..store.case_types import CaseTypeNotFound
from ..store.engine import EngineTransactions
from .actors import actors
from .auth import Principal, caller_of
from .case_type_seeds import seeded_case_types
from .deps import Runtime
from .engine_reviews import titles_by_run, view
from .routers.activity import scope_of
from .routers.engine import files_in

# Review views read the operations their calls name, so a case reads at most this many.
REVIEWS_CAP = 10
RECENT = 5


def _left(due: str, now: datetime) -> int:
    return int((datetime.fromisoformat(due.replace("Z", "+00:00")) - now).total_seconds())


def _clock(due: str, met_at: str | None, paused: str | None, now: datetime) -> dict[str, Any]:
    if met_at:
        return {"state": "met", "dueAt": due, "leftS": None, "metAt": met_at}
    if paused:
        return {"state": "paused", "dueAt": due, "leftS": None, "metAt": None}
    left = _left(due, now)
    return {"state": "breached" if left < 0 else "running", "dueAt": due, "leftS": left, "metAt": None}


def sla(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    done = row["status"] in ("resolved", "closed")
    return {
        "response": _clock(row["response_due_at"], row["responded_at"], row["paused_since"], now),
        "resolution": _clock(row["resolution_due_at"], row["updated_at"] if done else None, row["paused_since"], now),
        "pausedSince": row["paused_since"],
    }


def _may(me: Principal, action: str, team: str, **kw: Any) -> bool:
    try:
        can(caller_of(me), "cases", action, team=team, what="this case", **kw)
    except Forbidden:
        return False
    return True


async def _type_fields(rt: Runtime, row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    values = cast(dict[str, Any], row.get("fields") or {})
    if not row.get("type_id"):
        return None, fields_view(None, values, set())
    try:
        n, record = await (await seeded_case_types(rt.db)).published(str(row["type_id"]), row.get("type_version"))
    except CaseTypeNotFound:
        return None, fields_view(None, values, set())
    kind = {"id": row["type_id"], "version": n, "name": record.get("name") or row["type_id"]}
    return kind, fields_view(specs_of(record.get("fields") or []), values, set())


async def _reviews(rt: Runtime, case_id: str, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Human Tasks of the case's runs as review views: the waiting ones, then the newest decided, capped."""
    decisions = await RunStore(EngineTransactions(rt.db)).resumes([str(r["id"]) for r in runs])
    titles = await titles_by_run(rt, runs)
    out: list[dict[str, Any]] = []
    for run in runs:
        if run["status"] == "waiting" and run.get("waiting") and len(out) < REVIEWS_CAP:
            out.append(await view(rt, run, case_id=case_id, titles=titles[str(run["id"])]))
    for run in runs:
        for decided in reversed(decisions.get(str(run["id"]), [])):
            if len(out) >= REVIEWS_CAP:
                return out
            out.append(await view(rt, run, decided, case_id=case_id, titles=titles[str(run["id"])]))
    return out


def _href(review: dict[str, Any]) -> str:
    """The task's own page (c-291), its id encoded as the console's Open link encodes it."""
    return f"/reviews/{quote(str(review['id']), safe='')}"


def _deciding(review: dict[str, Any]) -> str | None:
    """The team that decides the task, by name, else id: the same team its task page and the quick view name."""
    team = cast(dict[str, Any], review.get("decidingTeam") or {})
    return cast(str | None, team.get("name") or team.get("id"))


def waiting_of(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "taskId": r["id"],
            "title": r.get("question") or r["title"],
            "assignee": {"name": r["assignee"]} if r.get("assignee") else None,
            "group": _deciding(r),
            "openedAt": r["createdAt"],
            "dueAt": r.get("dueAt"),
            "href": _href(r),
        }
        for r in reviews
        if r["status"] == "pending"
    ]


def actions_of(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A Human Task that would call something is a drafted action, decided on its task page (interview Q2)."""
    return [
        {
            "id": r["id"],
            "taskId": r["id"],
            "label": r.get("proposal") or r["title"],
            "kind": "reply" if r.get("reply") else "tool",
            "status": r["status"],
            "approvalsGiven": len(r.get("approvals") or []),
            "approvalsNeeded": 2 if r["policy"]["fourEyes"] else 1,
            "summary": r.get("consequence"),
            "href": _href(r),
        }
        for r in reviews
        if r.get("actionTool")
    ]


async def assembled(rt: Runtime, me: Principal, row: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    case_id, team = str(row["id"]), str(row["team_id"])
    links = CaseLinks(rt.db)
    runs = await links.runs(case_id, team)
    reviews = await _reviews(rt, case_id, runs)
    waiting = waiting_of(reviews)
    case_type, typed = await _type_fields(rt, row)
    emails = await links.emails([str(r["id"]) for r in runs])
    related = await links.related(row)
    opener = str(row["created_by"]) if str(row["created_by"]).startswith("run:") else ""
    first = next((r for r in runs if f"run:{r['id']}" == opener), None)
    files: dict[str, str | None] = {f["fileId"]: None for f in typed if f["fileId"]}
    for r in runs:
        for f in files_in(r.get("input")):
            files[f["id"]] = files.get(f["id"]) or f["name"]
    # The Activity router's scope rules, so a case's recent lines are the ones Activity would show the caller.
    recent = await Activity(rt.db).page(scope_of(me, team), Filters(case=(case_id, team)), page=1, page_size=RECENT)
    who = await actors(
        rt, [str(a["actor"] or "") for a in recent.rows] + ([row["assignee"]] if row["assignee"] else [])
    )
    names = rt.team_names
    return {
        "caseType": case_type,
        "owner": {"email": row["assignee"], "name": (who.get(row["assignee"]) or {}).get("name") or row["assignee"]}
        if row["assignee"]
        else None,
        "team": {"id": team, "name": (await names.name(team) if names is not None else None) or team},
        "customer": {
            "id": row["customer_id"],
            "name": row["customer_name"] or row["customer_id"],
            "href": f"/cases?customer={row['customer_id']}",
        }
        if row["customer_id"]
        else None,
        "sla": sla(row, now),
        "nextAction": {
            "kind": "human_task",
            "label": waiting[0]["title"],
            "owner": waiting[0]["group"],
            "dueAt": waiting[0]["dueAt"],
            "href": waiting[0]["href"],
        }
        if waiting
        else None,
        "typedFields": typed,
        "waiting": waiting,
        "waitingAllHref": f"/reviews?case={case_id}",
        "actions": actions_of(reviews),
        "links": {
            "files": [{"fileId": i, "name": n or i, "viewerHref": f"/files?file={i}"} for i, n in files.items()],
            "runs": [
                {
                    "id": r["id"],
                    "workflowName": r["workflow_name"],
                    "state": r["status"],
                    "href": f"/workflows/runs/{r['id']}",
                }
                for r in runs
            ],
            "emails": [
                {
                    "id": e["id"],
                    "subject": e["subject"] or "(no subject)",
                    "direction": "in",
                    "at": e["recorded_at"],
                    "href": f"/activity?case={case_id}&kind=email",
                }
                for e in emails
            ],
            "cases": [
                {
                    "id": c["id"],
                    "subject": c["subject"],
                    "status": c["status"],
                    "relation": c["relation"],
                    "href": f"/cases/{c['id']}",
                }
                for c in related
            ],
            "allHrefs": {
                "runs": f"/activity?case={case_id}&kind=workflow_run",
                "emails": f"/activity?case={case_id}&kind=email",
                "cases": f"/cases?customer={row['customer_id']}" if row["customer_id"] else None,
            },
        },
        "workflow": {
            "id": first["workflow_id"],
            "name": first["workflow_name"],
            "href": f"/workflows/definitions/{first['workflow_id']}",
        }
        if first
        else None,
        "activity": {
            "recent": [
                {
                    "at": a["at"],
                    "actorName": (who.get(str(a["actor"] or "")) or {}).get("name") or str(a["actor"] or ""),
                    "text": a["title"],
                    "href": f"/workflows/runs/{a['ref_id']}" if a["ref_kind"] == "run" else None,
                }
                for a in recent.rows
            ],
            "total": recent.total,
            "allHref": f"/activity?case={case_id}",
        },
        "permissions": {
            "assign": _may(me, "edit", team),
            "changeStatus": _may(me, "edit", team),
            # Closing or reopening is a person's, and cases.manage (an admin, or whoever opened it under `own`).
            "close": caller_of(me).kind == "person" and _may(me, "manage", team, owner=row["created_by"]),
            "note": _may(me, "edit", team),
        },
    }
