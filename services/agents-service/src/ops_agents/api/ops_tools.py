"""The Ops tools: the team's default agent finds the turn's person's cases, Human Tasks, runs and the workflows
they may start, and answers with cards the console draws from the record itself.

Every tool reads through the facade its route uses, as the turn's person (`TURN_PERSON`), so team scoping and `can()`
decide exactly what the person would see on the page. The person and the team never come from a tool argument: the
tools take none, and whatever else the model passes is dropped. Each answer is `{"cards": [{type, id}], "summary"}`:
references only, never a record's field values, so a card cannot be misstated by the model. Nothing here writes;
deciding a task and starting a run are the person's own presses on the card.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from langgraph.config import get_config

from ops_access import can
from ops_access.platform_events import TEAM_CREATED, Handler
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_contracts.chat import ChatMessage
from ops_engine.node_types import start_form
from ops_service_kit.errors import ApiError
from ops_service_kit.logging import get_logger
from ops_store import isolation

from ..activities.catalog import AgentDefinition
from ..activities.gateway import carded
from ..graphs.common import OPS_SERVER
from ..store.cases import CaseNotFound, CaseStore
from ..store.team_defaults import TeamDefaults
from ..store.tenancy import ASSISTANT_CATCH_UP
from . import hitl_facade
from .agent_registry import SEED_FIELDS, go_live, registry, seed_agent_version, spec_from_seed
from .auth import Principal, caller_of, reader_teams
from .child_runs import TURN_PERSON, ChildRuns, engine_workflows
from .deps import Runtime
from .run_starts import REGISTRY
from .runs import graph_store

log = get_logger("ops_agents.ops_tools")

LIMIT = 5
# From this many matching cases, find_cases answers with one table instead of a card each: a list reads as rows, and a
# stack of large cards pushes the answer off screen.
TABLE_FROM = 3
# Who the registry records as having made a team's Ops Assistant: the platform.
SYSTEM = "system:ops-assistant"
# The built-in read tools tools-service provisions in every team (its BUILT_IN apps): the assistant is granted
# them like any other tool, through the team's tool gateway.
BUILT_IN_READS = ("search_knowledge", "read_file", "read_document")
# The team's Ops Assistant, the team default agents-service provisions: read tools only, fixed instructions.
# `version` rises with any change here; a team's assistant nobody changed takes it at the next start or first chat.
# The core names no app, team, record type or scenario (tests/unit/test_ops_assistant_prompt.py): what a team can reach
# comes to each turn as data, its apps and the skills their plugins ship, never as a rule written here.
ASSISTANT_FRAGMENTS: dict[str, str] = {
    "identity": "You are the team's assistant in Ops AI. You work for the person you are talking with, as them: you "
    "read only what they may see, and a change you propose waits for a person's approval before it happens.",
    "act-first": "Act before asking: look things up with the tools you have, with sensible defaults (the person's own, "
    "open, recent) instead of asking which. Make independent reads together in one step. Before using an app, "
    "load the listed skill whose description fits the ask. Ask one short question only before a change, when "
    "nothing you can reach holds the answer, or when two readings would lead to different work, and ask for "
    "one thing at a time, giving its likely answers as followUps with present. Never ask for a token, "
    "password or address, and never give command-line or API steps. If an app you need is off or not "
    "installed, say so in one line and who can help; when you need a sign-in a Connect card appears: say in "
    "one line that you carry on once they connect, never that they should ask again; after it you go on with the "
    'same ask. On "again", repeat the last call with the same arguments.',
    "answer-style": "Answer like a colleague: the answer first, then up to four short points. Cite each fact from "
    "knowledge with its [n]. Call a record by a natural name, never its id or a tool's name. Say only what a tool "
    "result or passage holds; never invent records, buttons or apps, and never tell the person which control to "
    "press. When a call failed, say in plain words what happened and the next step. End on a full sentence.",
    "plan": "When an ask needs a chain of lookups (a later one depends on an earlier result), two or more apps, or a "
    "change, keep a short checklist with plan, mark each step as you go in the same step as its reads, and answer once "
    "at the end; never plan one lookup, and do not stop to ask between steps.",
}
OPS_ASSISTANT: dict[str, Any] = {
    "name": "Ops Assistant",
    "role": "Answers from the apps and knowledge your team has, as you, and drafts changes for your approval",
    "version": 6,
    "instructions": [{"text": text} for text in ASSISTANT_FRAGMENTS.values()],
    "tools": list(BUILT_IN_READS),
    "default_kb_ids": [],
    "suggestions": ["What needs me today?", "What can you reach?", "Start a workflow"],
    # Independent reads go together in one step, and the last step is kept for the answer (kernel max_steps).
    "max_tool_calls": 6,
    # Its own alias (models-service seeds it), so the assistant's model moves without moving every other agent's.
    "model_alias": "assistant",
}


def ops_assistant_id(team_id: str) -> str:
    return f"ag_ops_{team_id}"


def _declared(rt: Runtime, aid: str) -> dict[str, Any]:
    return spec_from_seed(AgentDefinition.model_validate({**OPS_ASSISTANT, "id": aid}), rt.settings.model_alias)


async def follow_declared(rt: Runtime, team_id: str) -> None:
    """Brings the team's Ops Assistant to the declared one (OPS_ASSISTANT) as a new version, when its published version
    is still the platform's; once a person has published a version the assistant is the team's and is left alone."""
    aid = ops_assistant_id(team_id)
    reg = registry(rt)
    row = await reg.row(aid)
    if row["published_version"] is None:
        return
    published = await reg.version(aid, int(row["published_version"]))
    if published["saved_by"] != SYSTEM:
        return
    # The caps and the model too: the published version is the platform's, so nothing a person chose is replaced.
    want = {k: v for k, v in _declared(rt, aid).items() if k in (*SEED_FIELDS, "guardrails", "model")}
    if all(published["spec"].get(k) == v for k, v in want.items()):
        return

    async def change(s: dict[str, Any]) -> dict[str, Any]:
        return {**s, **want}

    await seed_agent_version(rt, aid, change, f"Ops Assistant {OPS_ASSISTANT['version']}", by=SYSTEM)


async def ensure_ops_assistant(rt: Runtime, team_id: str) -> AgentDefinition:
    """The team's Ops Assistant, made, published and set as the team's default on its first chat when the team has no
    default agent, as the declared one. Its id comes from the team, so two first chats at once make one:
    the second insert meets the first's row and serves it. Setting the default is recorded like a team admin's
    (`TeamDefaults.set_agent`, `by`)."""
    aid = ops_assistant_id(team_id)
    if (live := rt.catalog.agent(aid)) is None:
        spec = _declared(rt, aid)
        # False when another first chat of the team made it a moment ago; either way it is served below.
        if not await registry(rt).create_if_absent(spec, by=SYSTEM, team_id=team_id, agent_id=aid):
            await follow_declared(rt, team_id)
        if rt.catalog.agent(aid) is None:
            go_live(rt, aid, 1, spec)
        live = cast(AgentDefinition, rt.catalog.agent(aid))
    await TeamDefaults(rt.db).set_agent(team_id, aid, by=SYSTEM)
    return live


async def catch_up_assistants(rt: Runtime) -> int:
    """At start: every team whose default agent is its Ops Assistant gets the declared one, if nobody changed it; a
    failure in one tenant is logged and the rest go on. Returns how many teams were looked at."""
    seen = 0
    for tenant_id, team_id, agent_id in await TeamDefaults(rt.db).on_agents(ops_assistant_id("")):
        if agent_id != ops_assistant_id(team_id):
            continue
        seen += 1
        try:
            with isolation.tenant_wide(ASSISTANT_CATCH_UP, tenant_id=tenant_id):
                await follow_declared(rt, team_id)
        except Exception as e:  # one tenant's failure must not stop the others, nor the service's start
            log.warning("ops_assistant_catch_up_failed", tenant=tenant_id, error=type(e).__name__)
    return seen


_TEXT = {"type": "string", "maxLength": 200}
# The card for an app the team has off: offered only while the team has one (apps_line: installed, off).
REQUEST_APP = "request_app"
APP_OFF = "APP_OFF_FOR_TEAM"

TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "find_cases": (
        "Find the team's cases by words in the subject or the customer's name, by status, or assigned to the person "
        "you are talking with. Answers with up to five cases, as cards or, from three, as one table.",
        {
            "type": "object",
            "properties": {
                "search": _TEXT,
                "status": {"type": "string", "enum": ["open", "waiting_on_customer", "resolved", "closed"]},
                "assignedToMe": {
                    "type": "boolean",
                    "description": "Only cases assigned to the person you are talking with",
                },
                "overdue": {"type": "boolean"},
            },
        },
    ),
    "get_case": (
        "Show one case as a card, by its id.",
        {"type": "object", "properties": {"caseId": _TEXT}, "required": ["caseId"]},
    ),
    "my_human_tasks": (
        "The Human Tasks waiting for the person you are talking with (mine), for their team (team), or past their "
        "deadline (overdue). Answers with up to five tasks as cards they can decide from.",
        {"type": "object", "properties": {"which": {"type": "string", "enum": ["mine", "team", "overdue"]}}},
    ),
    "get_human_task": (
        "Show one Human Task as a card, by its id.",
        {"type": "object", "properties": {"taskId": _TEXT}, "required": ["taskId"]},
    ),
    "list_startable_workflows": (
        "The workflows the person you are talking with may start by hand, by id and name.",
        {"type": "object", "properties": {}},
    ),
    "start_workflow_form": (
        "Show a workflow's start form as a card the person fills in and starts themselves, by the workflow's id.",
        {"type": "object", "properties": {"workflowId": _TEXT}, "required": ["workflowId"]},
    ),
    "get_run": (
        "Show one workflow run as a card with its steps, by its id.",
        {"type": "object", "properties": {"runId": _TEXT}, "required": ["runId"]},
    ),
    REQUEST_APP: (
        "When the ask needs an app the apps list says is installed but off for this team, call this with the app's "
        "name instead of answering that it is off: it shows the person a card to ask a team admin to turn it on. It "
        "reads nothing and changes nothing.",
        {"type": "object", "properties": {"app": _TEXT}, "required": ["app"]},
    ),
}


def declared_args(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Only the arguments the tool declares: a person, email or team the model adds is dropped here."""
    declared = cast(dict[str, Any], TOOLS[tool][1].get("properties") or {})
    return {k: v for k, v in arguments.items() if k in declared}


def _answer(cards: list[dict[str, str]], summary: str) -> ToolOutcome:
    return ToolOutcome(True, {"cards": cards, "summary": summary})


def _brief(row: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """One case for the model to answer from: subject and status, customer, when it is due, and its notes in order, so
    a "prep me" names the client and the points the case holds instead of making them up."""
    notes = [str(e["detail"].get("text")) for e in events if e.get("kind") == "note" and e["detail"].get("text")]
    parts = [f"{row['subject']} ({row['status']})"]
    if row.get("customer_name"):
        parts.append(f"customer {row['customer_name']}")
    if row.get("resolution_due_at"):
        parts.append(f"due {str(row['resolution_due_at'])[:16].replace('T', ' ')}")
    parts.append("notes: " + " | ".join(notes) if notes else "no notes")
    return "; ".join(parts)


def _case_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The cases as one table part: subject first, the id last, which the chat's table keeps behind its View menu."""
    data = [
        {
            "subject": r["subject"],
            "customer": r.get("customer_name") or "",
            "status": str(r["status"]).replace("_", " "),
            "due": str(r.get("resolution_due_at") or "")[:10],
            "id": r["id"],
        }
        for r in rows
    ]
    return {"type": "widget", "id": "", "shape": "rows", "data": data, "hint": {"title": "Cases"}}


def _refused(message: str) -> ToolOutcome:
    return ToolOutcome(False, {"error": message})


class OpsReads:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def offers(self, agent_id: str) -> list[ToolGrant]:
        """The Ops tools when `agent_id` is its team's default agent (the Ops Assistant while the team has set none) and
        the turn has a person; none otherwise."""
        try:
            thread_id = str((get_config().get("configurable") or {}).get("thread_id") or "")
        except RuntimeError:
            return []  # not inside a graph run, so there is no turn to offer them to
        return await self.offers_in(agent_id, thread_id)

    async def offers_in(self, agent_id: str, thread_id: str) -> list[ToolGrant]:
        """The Ops tools for `agent_id` on a turn of `thread_id`, for the turn's person."""
        if TURN_PERSON.get() is None:
            return []
        thread = await graph_store(self.rt).thread(thread_id) if thread_id else None
        if thread is None or await TeamDefaults(self.rt.db).agent(str(thread["team_id"])) != agent_id:
            return []
        offered = (
            TOOLS
            if await self._off_apps(str(thread["team_id"]))
            else {k: v for k, v in TOOLS.items() if k != REQUEST_APP}
        )
        return [
            ToolGrant(name, OPS_SERVER, description, "read", schema) for name, (description, schema) in offered.items()
        ]

    async def _off_apps(self, team: str) -> list[dict[str, Any]]:
        """The installed apps the team has off, as the apps line reads them for the turn's person; none when that list
        cannot be read, so the card is never offered for an app nobody can see."""
        person = TURN_PERSON.get()
        apps_line = self.rt.apps_line
        if person is None or not person.email or apps_line is None or self.rt.app_states is None:
            return []
        cards = cast(list[dict[str, Any]], await apps_line.cards(team, person.email) or [])
        return [
            c
            for c in cards
            # Off for the team (with or without an auth config yet): a team admin turns it on.
            if c.get("appGroup") == "needs_admin"
            and not cast(dict[str, Any], c.get("plugin") or {}).get("teamOn")
            and c.get("name")
        ]

    async def run(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome:
        person = TURN_PERSON.get()
        if person is None:
            return _refused("This conversation's person is not known to this turn; ask again.")
        if tool not in TOOLS:
            return _refused(f"There is no Ops tool named {tool}.")
        args = declared_args(tool, arguments)
        required = cast(list[str], TOOLS[tool][1].get("required") or [])
        if missing := [k for k in required if not args.get(k)]:
            return _refused(f"{tool} needs {', '.join(missing)}.")
        try:
            return await getattr(self, f"_{tool}")(person, args)
        except ApiError as e:
            return _refused(str(e))

    async def _find_cases(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        rows, total = await CaseStore(self.rt.db).list(
            [str(person.team_id)],
            status=[args["status"]] if args.get("status") else [],
            priority=[],
            assignee=(person.email or person.sub) if args.get("assignedToMe") else None,
            customer_id=None,
            overdue=bool(args.get("overdue")),
            search=args.get("search"),
            page=1,
            size=LIMIT,
        )
        named = "; ".join(f"{r['subject']} ({r['status']})" for r in rows)
        summary = f"{total} case(s) match; showing {len(rows)}: {named}" if rows else "No case matches."
        if len(rows) == 1:
            # The one match is the case asked about: its brief saves a get_case call.
            events = await CaseStore(self.rt.db).events(str(rows[0]["id"]))
            summary = f"1 case matches: {_brief(rows[0], events)}"
        if len(rows) >= TABLE_FROM:
            # The table is drawn in place of the cards, so the cases are shown once.
            return ToolOutcome(True, {"cards": [], "summary": summary}, {"part": _case_rows(rows)})
        return _answer([{"type": "case", "id": str(r["id"])} for r in rows], summary)

    async def _get_case(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        case_id = str(args["caseId"])
        try:
            row = await CaseStore(self.rt.db).get(case_id, [str(person.team_id)])
        except CaseNotFound:
            return _refused(f"There is no case {case_id} in this team.")
        events = await CaseStore(self.rt.db).events(case_id)
        return _answer([{"type": "case", "id": case_id}], _brief(row, events))

    async def _my_human_tasks(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        """`mine`: the open tasks assigned to the person; when none is, the open tasks they may decide. `team`: every
        open task of the team; `overdue`: those past their deadline. The answer states the counts Human Tasks shows
        (Assigned to me, All open), so what the agent says always agrees with that page."""
        which = str(args.get("which") or "mine")
        names = frozenset(n for n in (person.email, person.name) if n)
        view = {"mine": "open", "team": "open", "overdue": "overdue"}[which]
        rows = await hitl_facade.list_reviews(
            self.rt, view=view, filters={}, search=None, page_no=1, size=50, me=names, teams=reader_teams(person)
        )
        counts = cast(dict[str, int], rows["viewCounts"])
        data = cast(list[dict[str, Any]], rows["data"])
        mine, open_ = counts.get("mine", 0), counts.get("open", 0)
        if which == "mine":
            assigned = [r for r in data if r.get("assignee") in names]
            if assigned:
                data = assigned
                lead = f"{mine} assigned to you; {open_} open in your team."
            else:
                data = [r for r in data if await hitl_facade.can_decide(self.rt, person, str(r["id"]))]
                lead = f"Nothing is assigned to you; {open_} open in your team" + (
                    ", these you may decide." if data else "."
                )
        elif which == "team":
            lead = f"{open_} open in your team."
        else:
            lead = f"{counts.get('overdue', 0)} past their deadline."
        data = data[:LIMIT]
        cards = [{"type": "task", "id": str(r["id"])} for r in data]
        named = "; ".join(str(r.get("title") or r["id"]) for r in data)
        return _answer(cards, f"{lead} {named}".strip() if data else lead)

    async def _get_human_task(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        task_id = str(args["taskId"])
        review = await hitl_facade.get_review(self.rt, task_id)
        return _answer([{"type": "task", "id": task_id}], str(review.get("title") or task_id))

    async def _startable(self, person: Principal) -> list[dict[str, Any]]:
        runner = ChildRuns(self.rt)
        out: list[dict[str, Any]] = []
        for row in await engine_workflows(self.rt):
            if start_form(cast(dict[str, Any], row["definition"] or {}), REGISTRY) is None:
                continue  # started only by its source (a mailbox, a schedule), not by hand
            if await runner.refused_for_person(str(row["workflow_id"]), row.get("team_id")) is None:
                out.append(row)
        return out

    async def _list_startable_workflows(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        rows = await self._startable(person)
        named = "; ".join(
            f"{r['workflow_id']} ({cast(dict[str, Any], r['definition'] or {}).get('name') or r['workflow_id']})"
            for r in rows
        )
        return _answer(
            [], f"Workflows you may start: {named}" if rows else "There is no workflow you may start by hand."
        )

    async def _start_workflow_form(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        workflow = str(args["workflowId"])
        if workflow not in {str(r["workflow_id"]) for r in await self._startable(person)}:
            return _refused(f"{workflow} is not a workflow you may start by hand.")
        return _answer([{"type": "start", "id": workflow}], f"The start form of {workflow}.")

    async def _request_app(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        """The refusal a call on an app the team has off gets at the gateway, so chat draws the same card: the app, its
        id and the team, which the card's Ask an admin names."""
        asked = str(args["app"]).strip().lower()
        team = str(person.team_id)
        card = next((c for c in await self._off_apps(team) if str(c["name"]).lower() == asked), None)
        if card is None:
            return _refused(
                f"No app named {args['app']} is installed and off for this team; use its tools if it is on."
            )
        name = str(card["name"])
        error = {
            "code": APP_OFF,
            "message": f"{name} is off for this team; a team admin turns it on.",
            "details": {"app": name, "appId": str(card["id"]), "teamId": team},
        }
        return ToolOutcome(False, {"error": error}, for_model=carded({"error": error}))

    async def _get_run(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        from .routers.engine import visible_run  # noqa: PLC0415 - the router imports this module's neighbours

        run_id = str(args["runId"])
        run = await visible_run(self.rt, run_id)
        return _answer([{"type": "run", "id": run_id}], f"Run {run_id} of {run['workflow_id']}: {run['status']}")


def _data(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(bytes(response.body))["data"])


async def _filled(rt: Runtime, me: Principal, card: dict[str, Any]) -> dict[str, Any]:
    """One card reference with its record's view as `me` reads it on the record's own page; `missing` when the record
    is gone or out of `me`'s reach, so the card says so and offers nothing."""
    from .routers import case_records, reviews  # noqa: PLC0415 - the routers import this module's neighbours
    from .routers import engine as engine_routes  # noqa: PLC0415

    kind, ref = str(card.get("type") or ""), str(card.get("id") or "")
    try:
        if kind == "case":
            view = _data(await case_records.get_case(rt=rt, me=me, case_id=ref))
        elif kind == "task":
            view = _data(await reviews.get_review(rt=rt, me=me, thread_id=ref))
        elif kind == "run":
            view = _data(await engine_routes.get_engine_run(rt=rt, me=me, run_id=ref))
        elif kind == "start":
            definition = await engine_routes.definition_view(rt, ref)
            can(caller_of(me), "workflows", "run", team=definition.get("teamId"), what=f"workflow {ref}")
            view = definition
        else:
            return {"type": kind, "id": ref, "missing": True}
    except ApiError as e:
        log.info("ops_card_missing", card=kind, ref=ref, status=e.status, reason=str(e))
        return {"type": kind, "id": ref, "missing": True}
    return {"type": kind, "id": ref, "view": view}


async def fill_cards(rt: Runtime, me: Principal, messages: list[ChatMessage]) -> None:
    """Fills each Ops tool call's card references in place as `me`, the person reading the thread, so a card always
    draws its record's current state and only what the reader may see. Called on every thread read."""
    for message in messages:
        # A record drawn once in a reply is not drawn again when a later call there returns it too (find_cases, then
        # get_case on the same case).
        drawn: set[tuple[str, str]] = set()
        for call in message.tool_calls or []:
            raw: object = call.output
            if call.server != OPS_SERVER or not isinstance(raw, dict):
                continue
            output = cast(dict[str, Any], raw)
            cards = output.get("cards")
            if not isinstance(cards, list):
                continue
            refs = [cast(dict[str, Any], c) for c in cast(list[Any], cards) if isinstance(c, dict)]
            fresh = [c for c in refs if (str(c.get("type")), str(c.get("id"))) not in drawn]
            drawn |= {(str(c.get("type")), str(c.get("id"))) for c in fresh}
            call.output = {**output, "cards": [await _filled(rt, me, c) for c in fresh]}


def team_created_handlers(runtime: Callable[[], Runtime]) -> dict[str, Handler]:
    """A team platform-service just made gets its Ops Assistant as its default agent, unless the team
    already has a default (a repeat delivery after a team admin chose another), which is left as it is."""

    async def provision(_tenant: str, team_id: str, _payload: dict[str, Any]) -> int:
        rt = runtime()
        if await TeamDefaults(rt.db).agent(team_id) is not None:
            return 0
        await ensure_ops_assistant(rt, team_id)
        return 1

    return {TEAM_CREATED: Handler("agents", "create", provision)}
