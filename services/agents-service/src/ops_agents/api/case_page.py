"""A case assembled for its page (the approved case page design section 5): who owns it, its clocks, what it
waits on and the actions drafted there, its fields in its case type's order, what it links to, its newest activity and
what the caller may do. The console renders it and joins nothing. Every block reads in one query, or a capped number
of review views, whatever the case holds; nothing in here knows a use case."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote

from ops_access import can
from ops_engine.store import RunStore
from ops_service_kit.errors import Forbidden
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import an_object, entries

from ..case_fields import fields_view, specs_of
from ..store.case_links import CaseEmail, CaseLinks, RelatedCase
from ..store.case_types import CaseTypeNotFound
from ..store.cases import CaseRecord
from ..store.engine import EngineTransactions
from . import case_story
from .actors import ActorReads, NamedActors, actor_reads, named_actors
from .ai_steps_gate import people_see_masked
from .auth import Principal, caller_of, key_scope
from .case_story import CaseFeed, CaseOrigin, FeedReads, OriginReads
from .case_type_seeds import seeded_case_types
from .deps import Runtime
from .engine_reviews import Titles, ask_policies, titles_by_run, tools_of, view
from .file_names import named
from .review_sla import sla_hours
from .review_text import operations
from .run_story import FileRef, files_in, masked_story
from .team_names import deciding_team

# Review views read the operations their calls name, so a case reads at most this many.
REVIEWS_CAP = 10


def _left(due: str, now: datetime) -> int:
    return int((datetime.fromisoformat(due.replace("Z", "+00:00")) - now).total_seconds())


def _clock(due: str, met_at: str | None, paused: str | None, now: datetime) -> Json:
    if met_at:
        return {"state": "met", "dueAt": due, "leftS": None, "metAt": met_at}
    if paused:
        return {"state": "paused", "dueAt": due, "leftS": None, "metAt": None}
    left = _left(due, now)
    return {"state": "breached" if left < 0 else "running", "dueAt": due, "leftS": left, "metAt": None}


def sla(row: CaseRecord, now: datetime) -> Json:
    done = row.status in ("resolved", "closed")
    return {
        "response": _clock(row.response_due_at, row.responded_at, row.paused_since, now),
        "resolution": _clock(row.resolution_due_at, row.updated_at if done else None, row.paused_since, now),
        "pausedSince": row.paused_since,
    }


def _may(me: Principal, action: str, team: str, **kw: Any) -> bool:
    try:
        can(caller_of(me), "cases", action, team=team, what="this case", **kw)
    except Forbidden:
        return False
    return True


async def _type_fields(rt: Runtime, row: CaseRecord) -> tuple[Json | None, list[Json], tuple[str, str] | None]:
    """The case's type, its fields in the type's order, and the type's deadline field as (key, label)."""
    values = row.fields or {}
    if not row.type_id:
        return None, fields_view(None, values, set()), None
    try:
        types = await seeded_case_types(rt.db, str(row.team_id))
        n, record = await types.published(str(row.type_id), row.type_version)
    except CaseTypeNotFound:
        return None, fields_view(None, values, set()), None
    kind: Json = {"id": row.type_id, "version": n, "name": record.get("name") or row.type_id}
    # Checked by `specs_of` below, which refuses fields that are not a list.
    specs = record.get("fields") or []
    key = record.get("deadline")
    label = (
        next(
            (
                str(field.get("label") or key)
                for f in entries(specs)
                if (field := an_object(f, "a case type field")).get("key") == key
            ),
            None,
        )
        if key
        else None
    )
    return kind, fields_view(specs_of(specs), values, set()), (str(key), label) if key and label else None


# A date as a document writes it ("October 27, 2026", "27 Oct 2026"), the way a read leaves a deadline field.
WRITTEN_DATES = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")


def _end_of(value: Any) -> datetime | None:
    """A deadline field's value as the moment it passes: a date, ISO or written out, is due at the end of that day
    (UTC); anything that is not a date or a time reads as no deadline."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for form in WRITTEN_DATES:
        try:
            return datetime.strptime(text, form).replace(hour=23, minute=59, second=59, tzinfo=UTC)
        except ValueError:
            pass
    try:
        if len(text) == 10:
            return datetime.fromisoformat(text).replace(hour=23, minute=59, second=59, tzinfo=UTC)
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def timer(row: CaseRecord, deadline: tuple[str, str] | None, resolution: Json, now: datetime) -> Json:
    """The case's one timer: its type's deadline field when it holds a date, labelled as the field is; met once
    the case is resolved or closed, breached past the date, never paused (a court date does not move while the bank
    waits on the customer). Otherwise the resolution clock."""
    due = _end_of((row.fields or {}).get(deadline[0])) if deadline else None
    if deadline is None or due is None:
        return {
            "label": "Resolution",
            "dueAt": resolution["dueAt"],
            "state": resolution["state"],
            "leftS": resolution["leftS"],
        }
    if row.status in ("resolved", "closed"):
        return {"label": deadline[1], "dueAt": due.isoformat(), "state": "met", "leftS": None}
    left = int((due - now).total_seconds())
    return {
        "label": deadline[1],
        "dueAt": due.isoformat(),
        "state": "breached" if left < 0 else "running",
        "leftS": left,
    }


def _review_steps(runs: list[Json], decisions: dict[str, list[Json]]) -> list[tuple[Json, Json | None]]:
    """The Human Tasks of the case's runs a page shows: the waiting ones, then the newest decided, capped; each as the
    run and its decision (None for the one the run waits on)."""
    out: list[tuple[Json, Json | None]] = []
    for run in runs:
        if run["status"] == "waiting" and run.get("waiting") and len(out) < REVIEWS_CAP:
            out.append((run, None))
    for run in runs:
        for decided in reversed(decisions.get(str(run["id"]), [])):
            if len(out) >= REVIEWS_CAP:
                return out
            out.append((run, decided))
    return out


async def _reviews(rt: Runtime, case_id: str, reads: CaseReads) -> list[Json]:
    """The Human Tasks of the case's runs as review views, built from what `case_reads` read. The page's readers take
    each as the JSON reply it is (`waiting_of`, `actions_of`)."""
    return [
        cast(Json, await view(rt, run, decided, case_id=case_id, titles=reads.titles[str(run["id"])]))
        for run, decided in _review_steps(reads.runs, reads.decisions)
    ]


def _href(review: Json) -> str:
    """The task's own page, its id encoded as the console's Open link encodes it."""
    return f"/reviews/{quote(str(review['id']), safe='')}"


def _deciding(review: Json) -> str | None:
    """The team that decides the task, by name, else id: the same team its task page and the quick view name."""
    team = an_object(review.get("decidingTeam") or {}, "the review's deciding team")
    return cast(str | None, team.get("name") or team.get("id"))


def waiting_of(reviews: list[Json]) -> list[Json]:
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


def _called_step(review: Json) -> str | None:
    """The engine step key (run:node:iteration:attempt) of the call an approval sent, as the decide route records it."""
    resume = an_object(review.get("resume") or {}, "the review's resume")
    for part in ("call", "approval"):
        step = an_object(resume.get(part) or {}, "the resumed call").get("step")
        if step:
            return str(step)
    return None


async def failed_calls(rt: Runtime, runs: list[Json]) -> set[str]:
    """The step keys of the case's runs' calls that answered an error, read in one query for every run; an attempt a
    Redrive set aside (`redriven`) answered one too."""
    steps = await RunStore(EngineTransactions(rt.db)).steps_of([str(r["id"]) for r in runs])
    return {s.key for rows in steps.values() for s in rows if s.status in ("error", "redriven")}


def actions_of(reviews: list[Json], failed: set[str]) -> list[Json]:
    """A Human Task that would call something is a drafted action, decided on its task page. An approved
    action whose call the other side refused reads `refused`: the approval alone does not mean it was done."""
    return [
        {
            "id": r["id"],
            "taskId": r["id"],
            "label": r.get("proposal") or r["title"],
            "kind": "reply" if r.get("reply") else "tool",
            "status": "refused" if r["status"] == "approved" and _called_step(r) in failed else r["status"],
            "approvalsGiven": len(entries(r.get("approvals"))),
            "approvalsNeeded": 2 if an_object(r["policy"], "the review's policy")["fourEyes"] else 1,
            "summary": r.get("consequence"),
            "href": _href(r),
        }
        for r in reviews
        if r.get("actionTool")
    ]


# Statuses a person may resolve a case from, and run statuses that mean automation is still working on it.
UNRESOLVED = ("open", "waiting_on_us", "waiting_on_customer")
IN_FLIGHT = ("queued", "running", "waiting")


def whats_left(
    waiting: Sequence[Mapping[str, JsonValue]],
    actions: Sequence[Mapping[str, JsonValue]],
    runs: Sequence[Mapping[str, JsonValue]],
    row: CaseRecord,
    *,
    team_name: str,
    due: str | None,
    may_edit: bool,
) -> Json:
    """What is left on the case: each open Human Task, who it waits on (its assignee, else the team that
    decides it) and by when (its own due time, else the case's), and each approved action the bank's system refused,
    which waits for a new decision. `resolvable` when nothing is left, no linked run is still working, the case is not
    resolved or closed, and the caller may change its status (cases.edit, the rule PATCH applies)."""
    items: list[Json] = [
        {
            "kind": "task",
            "who": an_object(w.get("assignee") or {}, "the task's assignee").get("name") or w.get("group") or team_name,
            "what": w["title"],
            "dueAt": w.get("dueAt") or due,
            "href": w["href"],
        }
        for w in waiting
    ]
    # A task's id is the review's string id (waiting_of).
    open_tasks = {cast(str, w["taskId"]) for w in waiting}
    items += [
        {
            "kind": "action",
            "who": team_name,
            "what": f"{a['label']}: refused by the bank's system, decide again",
            "dueAt": due,
            "href": a["href"],
        }
        for a in actions
        if a["status"] == "refused" and a["taskId"] not in open_tasks
    ]
    busy = any(str(r.get("status")) in IN_FLIGHT for r in runs)
    resolvable = not items and not busy and row.status in UNRESOLVED and may_edit
    return {"items": [*items], "resolvable": resolvable}


@dataclass(frozen=True)
class CaseReads:
    """Everything a case page is told from the database, read in one transaction: `ask_case` then asks the other
    services what the page words it with, and `assembled` builds it."""

    runs: list[Json]
    decisions: dict[str, list[Json]]
    titles: dict[str, Titles]
    case_type: Json | None
    typed: list[Json]
    deadline: tuple[str, str] | None
    emails: list[CaseEmail]
    related: list[RelatedCase]
    failed: set[str]
    origin: OriginReads
    feed: FeedReads
    known: ActorReads


@dataclass(frozen=True)
class CaseAsked:
    """What the other services answered: each actor's name, the masking policy and the team's name."""

    who: NamedActors
    masking: bool
    team_name: str


def _files_of(typed: list[Json], runs: list[Json]) -> list[FileRef]:
    """The files the page names, as `named` takes them: those of the type's file fields, then those the runs took in."""
    # A file field's `fileId` is the file's id (case_fields.fields_view).
    files: dict[str, str | None] = {cast(str, f["fileId"]): None for f in typed if f["fileId"]}
    for r in runs:
        for f in files_in(r.get("input")):
            files[f["id"]] = files.get(f["id"]) or f["name"]
    return [{"id": i, "name": n} for i, n in files.items()]


async def case_reads(rt: Runtime, me: Principal, row: CaseRecord) -> CaseReads:
    """The database reads of `assembled`, all local, for the route's transaction. Who the page names is read here too
    (`actor_reads`), so `ask_case` asks platform-service with none open."""
    case_id, team = str(row.id), str(row.team_id)
    links = CaseLinks(rt.db)
    runs = await links.runs(case_id, team)
    decisions = await RunStore(EngineTransactions(rt.db)).resumes([str(r["id"]) for r in runs])
    titles = await titles_by_run(rt, runs)
    case_type, typed, deadline = await _type_fields(rt, row)
    emails = await links.emails([str(r["id"]) for r in runs])
    related = await links.related(row)
    failed = await failed_calls(rt, runs)
    origin = await case_story.origin_reads(rt, row)
    feed = await case_story.feed_reads(rt, row, runs, scope=key_scope(me))
    raws = [*([str(row.assignee)] if row.assignee else []), *origin.raws(), *feed.raws()]
    known = await actor_reads(rt, raws)
    return CaseReads(runs, decisions, titles, case_type, typed, deadline, emails, related, failed, origin, feed, known)


async def ask_case(rt: Runtime, row: CaseRecord, reads: CaseReads) -> CaseAsked:
    """Asks the other services what the page words it with, with nothing open: people's names, the masking policy, the
    team's name, file names, and for each Human Task the tools-service policy of its calls, the review deadline, the
    tool directory and the deciding team (each kept for the request, so building the views asks none of them)."""
    team = str(row.team_id)
    who = await named_actors(rt, reads.known)
    masking = await people_see_masked(rt, team)
    names = getattr(rt, "team_names", None)
    team_name = (await names.name(team) if names is not None else None) or team
    await named(rt, team, _files_of(reads.typed, reads.runs))
    shown = _review_steps(reads.runs, reads.decisions)
    await ask_policies(rt, tools_of(shown))
    if shown:
        await sla_hours(rt)
        for t in sorted({str(run["team_id"]) for run, _ in shown if run.get("team_id")}):
            await deciding_team(rt, t)
    if shown or reads.feed.calls:
        await operations(rt)
    return CaseAsked(who, masking, team_name)


async def assembled(
    rt: Runtime, me: Principal, row: CaseRecord, reads: CaseReads, asked: CaseAsked
) -> dict[str, JsonValue | CaseOrigin | CaseFeed]:
    """The case page from `reads` and `asked`. Only the Human Task views read the database here (a connect wait's first
    run), so a caller holds a transaction for this call."""
    now = datetime.now(UTC)
    case_id, team = str(row.id), str(row.team_id)
    runs, case_type, typed, deadline = reads.runs, reads.case_type, reads.typed, reads.deadline
    reviews = await _reviews(rt, case_id, reads)
    waiting = waiting_of(reviews)
    clock = timer(row, deadline, an_object(sla(row, now)["resolution"], "the resolution clock"), now)
    emails, related = reads.emails, reads.related
    opener = str(row.created_by) if str(row.created_by).startswith("run:") else ""
    first = next((r for r in runs if f"run:{r['id']}" == opener), None)
    linked = await named(rt, team, _files_of(typed, runs))
    file_names = {str(f["id"]): f["name"] for f in linked if f["name"]}
    # A file field reads as the file's name; its id stays in `fileId` for the link.
    typed = [f | {"display": file_names.get(cast(str, f["fileId"]), f["display"])} if f["fileId"] else f for f in typed]
    who, masking, team_name = asked.who, asked.masking, asked.team_name
    drafted = actions_of(reviews, reads.failed)
    # JSON, with the origin and the feed as case_story names them.
    page: dict[str, JsonValue | CaseOrigin | CaseFeed] = {
        "caseType": case_type,
        "owner": {"email": row.assignee, "name": (who.get(row.assignee) or {}).get("name") or row.assignee}
        if row.assignee
        else None,
        "team": {"id": team, "name": team_name},
        "customer": {
            "id": row.customer_id,
            "name": row.customer_name or row.customer_id,
            "href": f"/cases?customer={row.customer_id}",
        }
        if row.customer_id
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
        "typedFields": [*typed],
        "waiting": [*waiting],
        "waitingAllHref": f"/reviews?case={case_id}",
        "actions": [*drafted],
        "links": {
            "files": [{"fileId": f["id"], "name": f["name"], "viewerHref": f"/files?file={f['id']}"} for f in linked],
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
                    "id": e.id,
                    "subject": e.subject or "(no subject)",
                    "direction": "in",
                    "at": e.recorded_at,
                    "href": f"/activity?case={case_id}&kind=email",
                }
                for e in emails
            ],
            "cases": [
                {
                    "id": c.id,
                    "subject": c.subject,
                    "status": c.status,
                    "relation": c.relation,
                    "href": f"/cases/{c.id}",
                }
                for c in related
            ],
            "allHrefs": {
                "runs": f"/activity?case={case_id}&kind=workflow_run",
                "emails": f"/activity?case={case_id}&kind=email",
                "cases": f"/cases?customer={row.customer_id}" if row.customer_id else None,
            },
        },
        "workflow": {
            "id": first["workflow_id"],
            "name": first["workflow_name"],
            "href": f"/workflows/definitions/{first['workflow_id']}",
        }
        if first
        else None,
        "permissions": {
            "assign": _may(me, "edit", team),
            "changeStatus": _may(me, "edit", team),
            # Closing or reopening is a person's, and cases.manage (an admin, or whoever opened it under `own`).
            "close": caller_of(me).kind == "person" and _may(me, "manage", team, owner=row.created_by),
            "note": _may(me, "edit", team),
        },
        "whatsLeft": whats_left(
            waiting,
            drafted,
            runs,
            row,
            team_name=team_name,
            due=cast(str | None, clock["dueAt"]),
            may_edit=_may(me, "edit", team),
        ),
        "timer": clock,
        "origin": case_story.origin_view(reads.origin, who),
        "feed": await case_story.feed_view(rt, reads.feed, who=who, team_name=team_name, masking=masking),
    }
    if masking:
        # The acting team's setting, which is the case's team; ids, links and enum words stay as they are. The feed
        # masked itself, keeping where an email came from as the run page does.
        page |= {k: masked_story(page[k]) for k in ("typedFields", "waiting", "actions", "whatsLeft")}
    return page
