"""The Ops tools (c-469): the team's default agent finds the turn's person's cases, Human Tasks, runs and the workflows
they may start, and answers with cards the console draws from the record itself.

Every tool reads through the facade its route uses, as the turn's person (`TURN_PERSON`), so team scoping and `can()`
decide exactly what the person would see on the page. The person and the team never come from a tool argument: the
tools take none, and whatever else the model passes is dropped. Each answer is `{"cards": [{type, id}], "summary"}`:
references only, never a record's field values, so a card cannot be misstated by the model. Nothing here writes;
deciding a task and starting a run are the person's own presses on the card.
"""

from __future__ import annotations

import json
from typing import Any, cast

from langgraph.config import get_config

from ops_access import can
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_contracts.chat import ChatMessage
from ops_engine.node_types import start_form
from ops_service_kit.errors import ApiError
from ops_service_kit.logging import get_logger

from ..activities.catalog import AgentDefinition
from ..graphs.common import OPS_SERVER
from ..store.cases import CaseNotFound, CaseStore
from ..store.team_defaults import TeamDefaults
from . import hitl_facade
from .agent_registry import go_live, registry, spec_from_seed
from .auth import Principal, caller_of
from .child_runs import TURN_PERSON, ChildRuns, engine_workflows
from .deps import Runtime
from .run_starts import REGISTRY
from .runs import graph_store

log = get_logger("ops_agents.ops_tools")

LIMIT = 5
# Who the registry records as having made a team's Ops Assistant: the platform, on the team's first chat.
SYSTEM = "system:ops-assistant"
# The team's Ops Assistant, made on its first chat when it has no default agent: read tools only, fixed instructions.
OPS_ASSISTANT: dict[str, Any] = {
    "name": "Ops Assistant",
    "role": "Finds your cases, Human Tasks and runs, and starts workflows",
    "version": 1,
    "instructions": [
        {
            "text": "You are Ops Assistant, the team's assistant in Ops AI. You help the person you are talking with "
            "find their cases, see the Human Tasks waiting for them, follow a workflow run and start a workflow."
        },
        {
            "text": "Use find_cases and get_case for cases, my_human_tasks and get_human_task for Human Tasks, get_run "
            "for a run, list_startable_workflows and start_workflow_form to start one. Each answers with cards the "
            "person sees under your reply, so say in one short line what you found and let the cards carry the "
            "details; never repeat a card's fields."
        },
        {
            "text": "You cannot decide a task or start a run yourself: the person does that with the buttons on the "
            "card. If they ask you to, show the card and say which button to press."
        },
    ],
    "tools": [],
    "default_kb_ids": [],
    "suggestions": ["What needs me today?", "Find a case", "Start a workflow", "What happened to my last run?"],
    "max_tool_calls": 4,
}


def ops_assistant_id(team_id: str) -> str:
    return f"ag_ops_{team_id}"


async def ensure_ops_assistant(rt: Runtime, team_id: str) -> AgentDefinition:
    """The team's Ops Assistant, made, published and set as the team's default on its first chat when the team has no
    default agent (c-469). Its id comes from the team, so two first chats at once make one: the second insert meets the
    first's row and serves it. Setting the default is recorded like a team admin's (`TeamDefaults.set_agent`, `by`)."""
    aid = ops_assistant_id(team_id)
    if (live := rt.catalog.agent(aid)) is None:
        spec = spec_from_seed(AgentDefinition.model_validate({**OPS_ASSISTANT, "id": aid}), rt.settings.model_alias)
        # False when another first chat of the team made it a moment ago; either way it is served below.
        await registry(rt).create_if_absent(spec, by=SYSTEM, team_id=team_id, agent_id=aid)
        go_live(rt, aid, 1, spec)
        live = cast(AgentDefinition, rt.catalog.agent(aid))
    await TeamDefaults(rt.db).set_agent(team_id, aid, by=SYSTEM)
    return live


_TEXT = {"type": "string", "maxLength": 200}
TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "find_cases": (
        "Find the team's cases by words in the subject or the customer's name, by status, or assigned to the person "
        "you are talking with. Answers with up to five cases as cards.",
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
}


def declared_args(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Only the arguments the tool declares: a person, email or team the model adds is dropped here."""
    declared = cast(dict[str, Any], TOOLS[tool][1].get("properties") or {})
    return {k: v for k, v in arguments.items() if k in declared}


def _answer(cards: list[dict[str, str]], summary: str) -> ToolOutcome:
    return ToolOutcome(True, {"cards": cards, "summary": summary})


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
        return [
            ToolGrant(name, OPS_SERVER, description, "read", schema) for name, (description, schema) in TOOLS.items()
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
        cards = [{"type": "case", "id": str(r["id"])} for r in rows]
        named = "; ".join(f"{r['subject']} ({r['status']})" for r in rows)
        return _answer(cards, f"{total} case(s) match; showing {len(rows)}: {named}" if rows else "No case matches.")

    async def _get_case(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        case_id = str(args["caseId"])
        try:
            row = await CaseStore(self.rt.db).get(case_id, [str(person.team_id)])
        except CaseNotFound:
            return _refused(f"There is no case {case_id} in this team.")
        return _answer([{"type": "case", "id": case_id}], f"{row['subject']} ({row['status']})")

    async def _my_human_tasks(self, person: Principal, args: dict[str, Any]) -> ToolOutcome:
        """`mine`: the open tasks waiting for the person, those assigned to them first, then the ones they may decide;
        `team`: every open task of the team; `overdue`: those past their deadline."""
        which = str(args.get("which") or "mine")
        names = frozenset(n for n in (person.email, person.name) if n)
        view = {"mine": "open", "team": "open", "overdue": "overdue"}[which]
        rows = await hitl_facade.list_reviews(self.rt, view=view, filters={}, search=None, page_no=1, size=50, me=names)
        data = cast(list[dict[str, Any]], rows["data"])
        if which == "mine":
            assigned = [r for r in data if r.get("assignee") in names]
            decidable = [
                r for r in data if r not in assigned and await hitl_facade.can_decide(self.rt, person, str(r["id"]))
            ]
            data = assigned + decidable
        data = data[:LIMIT]
        cards = [{"type": "task", "id": str(r["id"])} for r in data]
        named = "; ".join(str(r.get("title") or r["id"]) for r in data)
        return _answer(cards, f"{len(data)} Human Task(s): {named}" if data else "No Human Task is waiting.")

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
    draws its record's current state and only what the reader may see (c-469). Called on every thread read."""
    for message in messages:
        for call in message.tool_calls or []:
            raw: object = call.output
            if call.server != OPS_SERVER or not isinstance(raw, dict):
                continue
            output = cast(dict[str, Any], raw)
            cards = output.get("cards")
            if not isinstance(cards, list):
                continue
            filled = [
                await _filled(rt, me, cast(dict[str, Any], c)) for c in cast(list[Any], cards) if isinstance(c, dict)
            ]
            call.output = {**output, "cards": filled}
