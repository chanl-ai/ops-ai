"""Public API operations offered as tools on the team MCP address, beside the team's own tools.

Each entry maps one operation of a service's public API to an MCP tool: its name, what it does, its input schema and
the route it calls. The call goes to the owning service with the assistant's own credential and team, so the
service's checks decide it exactly as for the console or the SDK (installing a template needs the create right of
its kind). Nothing is decided here: a refusal comes back as a tool error with the service's message.

Adding an operation is one entry in OPERATIONS."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote

import httpx
import mcp_types as types

TIMEOUT = 15.0


@dataclass(frozen=True)
class Operation:
    name: str
    description: str
    input_schema: dict[str, Any]
    service: str
    method: str
    # The route for the arguments, and the arguments it does not take into its path, sent as query (GET) or body.
    route: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]
    read_only: bool
    # The structured answer's key for a list, which MCP needs as an object.
    wrap: str | None = None


def _templates(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return "/v1/templates", {k: v for k, v in args.items() if k in ("kind", "source") and v}


def _install(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rest = {k: v for k, v in args.items() if k != "resource"}
    return f"/v1/resources/{quote(str(args.get('resource') or ''), safe=':')}/copies", rest


KINDS = ["agent", "skill", "workflow", "guardrail", "case_type", "task_type"]

OPERATIONS: tuple[Operation, ...] = (
    Operation(
        name="list_templates",
        description="List the templates this team can start from (agents, skills, workflows, guardrails, case types "
        "and task types from the packs and apps that are on), each with whether you may add it.",
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": KINDS, "description": "Keep one kind."},
                "source": {"type": "string", "description": "Keep one pack or app, as plugin:<id>."},
            },
            "additionalProperties": False,
        },
        service="agents",
        method="GET",
        route=_templates,
        read_only=True,
        wrap="templates",
    ),
    Operation(
        name="install_template",
        description="Add a template to this team as the team's own copy, as you: refused unless you may create that "
        "kind. Name it <source>:<id>, as list_templates shows.",
        input_schema={
            "type": "object",
            "required": ["resource"],
            "properties": {
                "resource": {"type": "string", "description": "The template, as <source>:<id>."},
                "name": {"type": "string", "description": "A name for the team's copy."},
            },
            "additionalProperties": False,
        },
        service="agents",
        method="POST",
        route=_install,
        read_only=False,
    ),
)

BY_NAME = {o.name: o for o in OPERATIONS}


class PlatformTools:
    """Calls an operation's service as the assistant; `bases` maps a service to its address."""

    def __init__(self, bases: dict[str, str], http: httpx.AsyncClient | None = None) -> None:
        self.bases = {k: v.rstrip("/") for k, v in bases.items() if v}
        self.http = http

    def tools(self) -> list[types.Tool]:
        return [
            types.Tool(
                name=o.name,
                description=o.description,
                input_schema=o.input_schema,
                annotations=types.ToolAnnotations(title=o.name, read_only_hint=o.read_only, open_world_hint=False),
            )
            for o in OPERATIONS
            if o.service in self.bases
        ]

    def offers(self, name: str) -> bool:
        o = BY_NAME.get(name)
        return o is not None and o.service in self.bases

    async def call(self, name: str, args: dict[str, Any], *, authorization: str, team: str) -> types.CallToolResult:
        o = BY_NAME[name]
        path, rest = o.route(args)
        headers = {"Authorization": authorization, "X-Team-Id": team, "Accept": "application/json"}
        url = f"{self.bases[o.service]}{path}"
        get = o.method == "GET"
        async with _Client(self.http) as http:
            r = await http.request(
                o.method, url, headers=headers, params=rest if get else None, json=None if get else rest
            )
        raw: Any = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        body = cast(dict[str, Any], raw) if isinstance(raw, dict) else {"data": raw}
        if r.is_success:
            out: Any = body.get("data", body)
            structured: dict[str, Any] = (
                {o.wrap: out} if o.wrap else (cast(dict[str, Any], out) if isinstance(out, dict) else {"result": out})
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(out, default=str))],
                structured_content=structured,
                is_error=False,
            )
        err = cast(dict[str, Any], body.get("error") or {})
        code, message = str(err.get("code") or r.status_code), str(err.get("message") or r.reason_phrase)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"{code}: {message}")],
            structured_content={"code": code, "status": r.status_code, "message": message},
            is_error=True,
        )

    async def _get(self, path: str, *, authorization: str, team: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": authorization, "X-Team-Id": team, "Accept": "application/json"}
        async with _Client(self.http) as http:
            r = await http.get(f"{self.bases['agents']}{path}", headers=headers, params=params)
        r.raise_for_status()
        body: Any = r.json()
        return cast(dict[str, Any], body).get("data") if isinstance(body, dict) else body

    async def _skills(self, *, authorization: str, team: str) -> list[dict[str, Any]]:
        """The team's skills the caller can read, each with its newest content (its inputs are on the version)."""
        page: Any = await self._get("/v1/skills", authorization=authorization, team=team, params={"pageSize": 100})
        rows = cast(
            list[dict[str, Any]], cast(dict[str, Any], page).get("data") if isinstance(page, dict) else page or []
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            found: Any = await self._get(f"/v1/skills/{row['id']}", authorization=authorization, team=team)
            out.append(cast(dict[str, Any], found))
        return out

    async def prompts(self, *, authorization: str, team: str) -> list[types.Prompt]:
        """Each of the team's skills as an MCP prompt named by its slug, its inputs as the prompt's arguments."""
        if "agents" not in self.bases:
            return []
        return [
            types.Prompt(
                name=str(s["slug"]),
                title=str(s.get("name") or s["slug"]),
                description=str(_content(s).get("useWhen") or ""),
                arguments=[
                    types.PromptArgument(
                        name=str(i["name"]),
                        description=str(i.get("description") or ""),
                        required=bool(i.get("required")),
                    )
                    for i in cast(list[dict[str, Any]], _content(s).get("inputs") or [])
                ],
            )
            for s in await self._skills(authorization=authorization, team=team)
        ]

    async def prompt(
        self, name: str, args: dict[str, str], *, authorization: str, team: str
    ) -> types.GetPromptResult | None:
        """The skill's instructions with the arguments given, or None when the team has no skill by that slug."""
        if "agents" not in self.bases:
            return None
        skill = next((s for s in await self._skills(authorization=authorization, team=team) if s["slug"] == name), None)
        if skill is None:
            return None
        content = cast(dict[str, Any], skill.get("content") or {})
        text = str(content.get("instructions") or "")
        for k, v in args.items():
            text = text.replace("{{" + k + "}}", v)
        given = [f"- {k}: {v}" for k, v in args.items() if v]
        if given:
            text += "\n\nInputs:\n" + "\n".join(given)
        return types.GetPromptResult(
            description=str(skill.get("name") or name),
            messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))],
        )


def _content(skill: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], skill.get("content") or {})


class _Client:
    """The shared client when one was given (tests), else one per call."""

    def __init__(self, http: httpx.AsyncClient | None) -> None:
        self.given, self.made = http, None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self.given is not None:
            return self.given
        self.made = httpx.AsyncClient(timeout=TIMEOUT)
        return self.made

    async def __aexit__(self, *_: object) -> None:
        if self.made is not None:
            await self.made.aclose()


__all__ = ["OPERATIONS", "Operation", "PlatformTools"]
