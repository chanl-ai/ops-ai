"""Agent lifecycle, chat and test over the generated agents operations."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from ._io import Definition, load_definition
from ._transport import iter_pages, iter_pages_async, iter_rows, iter_rows_async
from .errors import NotFound, OpsError

_BACKGROUND: set[asyncio.Task[None]] = set()

PLANNED = "This command is planned; the public API for it is not shipped."


def _agent_graph(id: str) -> str:
    """A published agent's graph is `agent:<id>`; the public chat call takes the agent id."""
    return id if id.startswith("agent:") else f"agent:{id}"


CREATE_KEYS = ("name", "role", "instructions", "model", "channels", "protection", "templateId")
UPDATE_KEYS = (
    "name",
    "role",
    "instructions",
    "model",
    "channels",
    "toolIds",
    "collections",
    "limits",
    "guardrails",
    "memory",
    "brief",
    "promptMode",
    "patterns",
)


def _agent_body(source: Definition) -> dict[str, Any]:
    data = load_definition(source)
    return {key: data[key] for key in CREATE_KEYS if key in data and data[key] is not None}


def _update_body(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data[key] for key in UPDATE_KEYS if key in data}


def based(fields: dict[str, Any], read: dict[str, Any]) -> dict[str, Any]:
    """`fields` naming the copy they were made on: the `version` and `digest` of the agent or skill as `read`. The
    service refuses a save made from an older copy (`stale_base`), so it never writes over a change saved since."""
    return {**fields, "baseVersion": read["version"], "baseDigest": read["digest"]}


def _read(base: dict[str, Any] | None) -> bool:
    # A list row carries no digest, so it cannot name a copy.
    return bool(base and base.get("digest"))


def _eval_body(cases: Any, trigger: str | None) -> dict[str, Any]:
    """The eval-run body: no cases runs the saved ones, so `cases` is left out rather than sent empty."""
    body: dict[str, Any] = {}
    if cases is not None:
        body["cases"] = cases["cases"] if isinstance(cases, dict) and "cases" in cases else cases
    if trigger is not None:
        body["trigger"] = trigger
    return body


class Agents:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, **query: Any) -> Iterator[Any]:
        return iter_pages(self._raw.agents.agents_list_agents, **query)

    def get(self, id: str) -> Any:
        return self._raw.agents.agents_get_agent(id)

    def create(self, body: Any) -> Any:
        return self._raw.agents.agents_create_agent(body)

    def validate(self, definition: Definition) -> dict[str, Any]:
        """Local required-field checks. The service validates again on apply."""
        data = load_definition(definition)
        missing = [key for key in ("name", "role") if not data.get(key)]
        checks = [
            {
                "code": "missing_field",
                "field": key,
                "message": f"{key} is required",
                "level": "error",
            }
            for key in missing
        ]
        return {"ok": not checks, "checks": checks}

    def _named(self, name: str) -> Any:
        try:
            for agent in self.list(search=name, page_size=50):
                if agent.get("name") == name:
                    return agent
        except (NotFound, OpsError):
            return None
        return None

    def update(self, id: str, fields: dict[str, Any], *, base: dict[str, Any] | None = None) -> Any:
        """Saves `fields` on the agent's draft. `base` is the agent as last read, naming the copy the change was made
        on; left out, the agent is read first. A save from an older copy is refused with `stale_base`."""
        return self._raw.agents.agents_update_agent(id, based(fields, base if _read(base) else self.get(id)))

    def apply(self, definition: Definition) -> Any:
        data = load_definition(definition)
        current = None
        wanted = data.get("id") or data.get("slug")
        if wanted:
            try:
                current = self.get(str(wanted))
            except NotFound:
                current = None
        if current is None and data.get("name"):
            current = self._named(str(data["name"]))
        if current:
            return self.update(str(current["id"]), _update_body(data), base=current)
        created = self._raw.agents.agents_create_agent(_agent_body(definition))
        extra = _update_body(data)
        extra = {key: extra[key] for key in extra if key not in CREATE_KEYS}
        if extra and created.get("id"):
            return self.update(str(created["id"]), extra, base=created)
        return created

    def publish(self, id: str, *, note: str = "", version: int | None = None) -> Any:
        agent = self.get(id)
        pin = version if version is not None else agent.get("version")
        return self._raw.agents.agents_request_publish(id, {"note": note, "version": pin})

    def tool_options(self, search: str | None = None) -> list[dict[str, Any]]:
        """The operations an agent may be granted: published ones, as the agent page's picker lists them."""
        return list(iter_rows(self._raw.agents.agents_tool_options, search=search, limit=50))

    def grant_tools(self, id: str, tools: list[str]) -> Any:
        """Adds tools (their ids from `tool_options`) to the agent's draft, keeping the ones it holds. Publish it
        for the grant to take effect."""
        agent = self.get(id)
        held = list(agent.get("toolIds") or [])
        wanted = held + [t for t in tools if t not in held]
        return self.update(id, {"toolIds": wanted}, base=agent)

    def references(self, search: str = "", *, for_agent: str, **query: Any) -> Any:
        """What the agent's brief can mention with @, grouped by kind; each item says whether the agent holds it.
        `ids` (`kind:id` each) answers the labels of what a saved text names."""
        asked = {k: v for k, v in {"search": search or None, **query}.items() if v is not None}
        return self._raw.agents.agents_references_search(for_agent=for_agent, **asked)

    def add_reference(self, id: str, kind: str, ref_id: str) -> Any:
        """Grants the agent a tool, knowledge base, skill, agent or workflow its brief mentions, as a new draft. A
        skill brings the tools and knowledge bases it names. `added` is empty when the agent already held it."""
        return self._raw.agents.agents_add_reference(id, {"kind": kind, "id": ref_id})

    def publish_check(self, id: str, *, version: int | None = None) -> Any:
        """What stops the agent's newest draft from being published, each problem with the field it is in."""
        pin = version if version is not None else self.get(id).get("version")
        return self._raw.agents.agents_publish_check(id, version=pin)

    def instruction_sections(self) -> dict[str, Any]:
        """The workspace's instruction section list: the stored one, or the default. Any signed-in person reads it."""
        return self._raw.agents.agents_get_instruction_sections()  # type: ignore[no-any-return]

    def set_instruction_sections(self, listing: dict[str, Any]) -> dict[str, Any]:
        """Replaces the list (needs settings.manage). The server holds up to 8 presets per section and 40 sections."""
        return self._raw.agents.agents_put_instruction_sections(listing)  # type: ignore[no-any-return]

    def reset_instruction_sections(self) -> dict[str, Any]:
        """Brings the default list back and returns it (needs settings.manage)."""
        return self._raw.agents.agents_reset_instruction_sections()  # type: ignore[no-any-return]

    def pause(self, id: str) -> Any:
        return self._raw.agents.agents_set_paused(id, {"paused": True})

    def resume(self, id: str) -> Any:
        return self._raw.agents.agents_set_paused(id, {"paused": False})

    def export(self, id: str) -> Any:
        return self.get(id)

    def chat(self, id: str, message: str, *, thread_id: str | None = None) -> Any:
        """Starts or continues a chat thread on the published agent and returns the collected reply."""
        return self.run(id, message, mode="wait", thread_id=thread_id)

    def run(
        self,
        id: str,
        message: str,
        *,
        mode: str = "wait",
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> Any:
        """Starts the published agent on the existing thread routes. wait drains the stream, stream keeps events,
        background returns a run id and drains in another thread so the caller can re-attach."""
        if thread_id is None:
            created = self._raw.agents.threads_create_thread({"graph": _agent_graph(id)})
            thread_id = created.get("threadId") or created.get("id")
        rid = run_id or f"run_{uuid.uuid4().hex[:16]}"
        body = {"input": {"message": message}, "runId": rid}
        if mode == "background":
            threading.Thread(
                target=lambda: list(self._raw.agents.threads_stream_run(str(thread_id), body)),
                daemon=True,
            ).start()
            return {"threadId": str(thread_id), "runId": rid, "mode": "background"}
        events = list(self._raw.agents.threads_stream_run(str(thread_id), body))
        collected = _collect_chat(events, str(thread_id))
        collected["runId"] = rid
        collected["mode"] = mode
        collected["chunks"] = events
        return collected

    def eval(self, id: str, cases: Any = None, *, trigger: str | None = None) -> Any:
        """With `cases=None` runs the agent's saved cases on its newest version and keeps the run; the reply carries
        `gate` (`blocked`, `steps`) and `costUsd`. With cases it scores them and keeps nothing. `trigger` (manual or
        cli) says what started a kept run."""
        return self._raw.agents.agents_create_eval_run(id, _eval_body(cases, trigger))

    def eval_cases(self, id: str) -> Any:
        """The agent's saved eval cases."""
        return self._raw.agents.assurance_agent_cases(id)

    def add_eval_cases(self, id: str, cases: Any) -> Any:
        """Adds cases to the agent's saved ones; `cases` is a list or `{"cases": [...]}`."""
        return self._raw.agents.assurance_add_agent_cases(id, _eval_body(cases, None))

    def eval_runs(self, id: str, *, page: int = 1, page_size: int = 25) -> Any:
        """The agent's kept runs, newest first, as rows without the case results."""
        return self._raw.agents.assurance_agent_eval_runs(id, page=page, page_size=page_size)

    def eval_run(self, run_id: str) -> Any:
        """One kept run with its case results."""
        return self._raw.agents.assurance_eval_run(run_id)

    def schedule(self, id: str, message: str, *, due_at: str | None = None, key: str = "job") -> Any:
        """Arm one due tick on the existing timer clock. A repeated key is one run."""
        op = {
            "method": "POST",
            "path": "/v1/agents/{agent_id}/jobs",
            "pathParams": ["agent_id"],
            "query": [],
            "headers": [],
            "body": "json",
            "stream": False,
        }
        return self._raw.agents._t.call(
            "agents", op, {"agent_id": id}, {}, {}, {"message": message, "dueAt": due_at, "key": key}
        )

    def test(self, id: str, message: str) -> Any:
        return self._raw.agents.agents_test_agent(id, {"message": message})

    def trace(self, id: str, *, limit: int = 20) -> Any:
        return self._raw.agents.agents_recent_runs(id, limit=limit)


class AsyncAgents:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def list(self, **query: Any) -> AsyncIterator[Any]:
        return iter_pages_async(self._raw.agents.agents_list_agents, **query)

    async def get(self, id: str) -> Any:
        return await self._raw.agents.agents_get_agent(id)

    async def create(self, body: Any) -> Any:
        return await self._raw.agents.agents_create_agent(body)

    async def validate(self, definition: Definition) -> dict[str, Any]:
        data = load_definition(definition)
        missing = [key for key in ("name", "role") if not data.get(key)]
        checks = [
            {
                "code": "missing_field",
                "field": key,
                "message": f"{key} is required",
                "level": "error",
            }
            for key in missing
        ]
        return {"ok": not checks, "checks": checks}

    async def _named(self, name: str) -> Any:
        try:
            async for agent in self.list(search=name, page_size=50):
                if agent.get("name") == name:
                    return agent
        except (NotFound, OpsError):
            return None
        return None

    async def update(self, id: str, fields: dict[str, Any], *, base: dict[str, Any] | None = None) -> Any:
        read = base if _read(base) else await self.get(id)
        return await self._raw.agents.agents_update_agent(id, based(fields, read))

    async def apply(self, definition: Definition) -> Any:
        data = load_definition(definition)
        current = None
        wanted = data.get("id") or data.get("slug")
        if wanted:
            try:
                current = await self.get(str(wanted))
            except NotFound:
                current = None
        if current is None and data.get("name"):
            current = await self._named(str(data["name"]))
        if current:
            return await self.update(str(current["id"]), _update_body(data), base=current)
        created = await self._raw.agents.agents_create_agent(_agent_body(definition))
        extra = _update_body(data)
        extra = {key: extra[key] for key in extra if key not in CREATE_KEYS}
        if extra and created.get("id"):
            return await self.update(str(created["id"]), extra, base=created)
        return created

    async def publish(self, id: str, *, note: str = "", version: int | None = None) -> Any:
        agent = await self.get(id)
        pin = version if version is not None else agent.get("version")
        return await self._raw.agents.agents_request_publish(id, {"note": note, "version": pin})

    async def tool_options(self, search: str | None = None) -> list[dict[str, Any]]:
        """The operations an agent may be granted: published ones, as the agent page's picker lists them."""
        return [row async for row in iter_rows_async(self._raw.agents.agents_tool_options, search=search, limit=50)]

    async def grant_tools(self, id: str, tools: list[str]) -> Any:
        """Adds tools (their ids from `tool_options`) to the agent's draft, keeping the ones it holds. Publish it
        for the grant to take effect."""
        agent = await self.get(id)
        held = list(agent.get("toolIds") or [])
        wanted = held + [t for t in tools if t not in held]
        return await self.update(id, {"toolIds": wanted}, base=agent)

    async def references(self, search: str = "", *, for_agent: str, **query: Any) -> Any:
        asked = {k: v for k, v in {"search": search or None, **query}.items() if v is not None}
        return await self._raw.agents.agents_references_search(for_agent=for_agent, **asked)

    async def add_reference(self, id: str, kind: str, ref_id: str) -> Any:
        return await self._raw.agents.agents_add_reference(id, {"kind": kind, "id": ref_id})

    async def publish_check(self, id: str, *, version: int | None = None) -> Any:
        pin = version if version is not None else (await self.get(id)).get("version")
        return await self._raw.agents.agents_publish_check(id, version=pin)

    async def instruction_sections(self) -> dict[str, Any]:
        """The workspace's instruction section list: the stored one, or the default. Any signed-in person reads it."""
        return await self._raw.agents.agents_get_instruction_sections()  # type: ignore[no-any-return]

    async def set_instruction_sections(self, listing: dict[str, Any]) -> dict[str, Any]:
        """Replaces the list (needs settings.manage). The server holds up to 8 presets per section and 40 sections."""
        return await self._raw.agents.agents_put_instruction_sections(listing)  # type: ignore[no-any-return]

    async def reset_instruction_sections(self) -> dict[str, Any]:
        """Brings the default list back and returns it (needs settings.manage)."""
        return await self._raw.agents.agents_reset_instruction_sections()  # type: ignore[no-any-return]

    async def pause(self, id: str) -> Any:
        return await self._raw.agents.agents_set_paused(id, {"paused": True})

    async def resume(self, id: str) -> Any:
        return await self._raw.agents.agents_set_paused(id, {"paused": False})

    async def export(self, id: str) -> Any:
        return await self.get(id)

    async def chat(self, id: str, message: str, *, thread_id: str | None = None) -> Any:
        return await self.run(id, message, mode="wait", thread_id=thread_id)

    async def run(
        self,
        id: str,
        message: str,
        *,
        mode: str = "wait",
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> Any:
        if thread_id is None:
            created = await self._raw.agents.threads_create_thread({"graph": _agent_graph(id)})
            thread_id = created.get("threadId") or created.get("id")
        rid = run_id or f"run_{uuid.uuid4().hex[:16]}"
        body = {"input": {"message": message}, "runId": rid}
        if mode == "background":
            events = await self._raw.agents.threads_stream_run(str(thread_id), body)
            if hasattr(events, "__aiter__"):

                async def _drain() -> None:
                    async for _ in events:
                        pass

                _BACKGROUND.add(task := asyncio.create_task(_drain()))
                task.add_done_callback(_BACKGROUND.discard)
            return {"threadId": str(thread_id), "runId": rid, "mode": "background"}
        events = await self._raw.agents.threads_stream_run(str(thread_id), body)
        items = [event async for event in events] if hasattr(events, "__aiter__") else list(events)
        collected = _collect_chat(items, str(thread_id))
        collected["runId"] = rid
        collected["mode"] = mode
        collected["chunks"] = items
        return collected

    async def eval(self, id: str, cases: Any = None, *, trigger: str | None = None) -> Any:
        return await self._raw.agents.agents_create_eval_run(id, _eval_body(cases, trigger))

    async def eval_cases(self, id: str) -> Any:
        return await self._raw.agents.assurance_agent_cases(id)

    async def add_eval_cases(self, id: str, cases: Any) -> Any:
        return await self._raw.agents.assurance_add_agent_cases(id, _eval_body(cases, None))

    async def eval_runs(self, id: str, *, page: int = 1, page_size: int = 25) -> Any:
        return await self._raw.agents.assurance_agent_eval_runs(id, page=page, page_size=page_size)

    async def eval_run(self, run_id: str) -> Any:
        return await self._raw.agents.assurance_eval_run(run_id)

    async def schedule(self, id: str, message: str, *, due_at: str | None = None, key: str = "job") -> Any:
        op = {
            "method": "POST",
            "path": "/v1/agents/{agent_id}/jobs",
            "pathParams": ["agent_id"],
            "query": [],
            "headers": [],
            "body": "json",
            "stream": False,
        }
        return await self._raw.agents._t.call(
            "agents", op, {"agent_id": id}, {}, {}, {"message": message, "dueAt": due_at, "key": key}
        )

    async def test(self, id: str, message: str) -> Any:
        return await self._raw.agents.agents_test_agent(id, {"message": message})

    async def trace(self, id: str, *, limit: int = 20) -> Any:
        return await self._raw.agents.agents_recent_runs(id, limit=limit)


def _reply_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    for key in ("reply", "content", "text"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    nested = data.get("data")
    return _reply_text(nested) if nested is not None and nested is not data else ""


def _unwrap_event(event: Any) -> tuple[str, Any]:
    """Chat and graph streams both become (kind, payload). Graph frames nest `{data: {event, data}}`."""
    if not isinstance(event, dict):
        return "", event
    inner = event.get("data")
    if isinstance(inner, dict) and inner.get("event") and "runId" in inner:
        return str(inner.get("event") or ""), inner.get("data")
    return str(event.get("event") or ""), inner if "data" in event else event


def _collect_chat(events: Any, thread_id: str) -> dict[str, Any]:
    items = list(events) if not isinstance(events, dict) else [events]
    parts: list[str] = []
    reply = ""
    citations: list[Any] = []
    tool_calls: list[Any] = []
    seen: set[str] = set()
    for event in items:
        kind, data = _unwrap_event(event)
        if kind == "text" and isinstance(data, str):
            parts.append(data)
            continue
        if kind == "citation" and isinstance(data, list):
            citations = list(data)
            continue
        text = _reply_text(data)
        if text:
            reply = text
        if isinstance(data, dict) and data.get("citations"):
            citations = list(data["citations"])
        payload = data.get("call") if isinstance(data, dict) else None
        call = payload if isinstance(payload, dict) else data if isinstance(data, dict) else {}
        name = str(call.get("name") or call.get("tool") or "")
        if (
            name
            and name not in seen
            and (kind in {"tool_call", "tool_start", "tool_end"} or call.get("name") or call.get("tool"))
        ):
            seen.add(name)
            tool_calls.append({**call, "name": name})
    if isinstance(events, dict) and not reply and not parts:
        reply = _reply_text(events)
    return {
        "threadId": thread_id,
        "reply": "".join(parts) or reply,
        "text": "".join(parts) or reply,
        "events": items,
        "citations": citations,
        "toolCalls": tool_calls,
    }


def agent_file(source: str | Path) -> Path:
    path = Path(source)
    if path.is_dir():
        for name in ("resources/agent.yaml", "agent.yaml"):
            candidate = path / name
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"{path} has no resources/agent.yaml or agent.yaml")
    return path
