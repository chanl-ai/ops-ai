"""Public API operations offered as tools on the team MCP address, beside the team's own tools.

Each entry maps one operation of a service's public API to an MCP tool: its name, what it does, its input schema and
the route it calls. The call goes to the owning service as any call between services does: a service token of this
service, naming the team. The assistant's own token is never sent on, since its audience is this MCP address alone.

The token carries the person by its scopes: of the cells an operation needs, only those the person holds in the team.
The owning service then decides with its own `can`, so a person without the create right of a template's kind is
refused there (403), exactly as in the console, and the refusal comes back as a tool error with the service's message.

Adding an operation is one entry in OPERATIONS."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, cast
from urllib.parse import quote

import httpx
import mcp_types as types

from ops_access import Access
from ops_identity import Principal, ServiceClient
from ops_policy import Ed25519Signer

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
    # The `area:action` cells the call may use, each sent only when the person holds it in the team.
    cells: tuple[str, ...] = ()


def _templates(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return "/v1/templates", {k: v for k, v in args.items() if k in ("kind", "source") and v}


def _install(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rest = {k: v for k, v in args.items() if k != "resource"}
    return f"/v1/resources/{quote(str(args.get('resource') or ''), safe=':')}/copies", rest


KINDS = ["agent", "skill", "workflow", "guardrail", "case_type", "task_type"]
# The create cell of every kind a template can be (agents-service's templates.AREAS): what list_templates shows as
# addable and what install_template is checked against.
CREATE = ("agents:create", "skills:create", "workflows:create", "guardrails:create")
SKILLS_VIEW = ("skills:view",)
ACCESS = Access()

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
        cells=CREATE,
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
        cells=CREATE,
    ),
)

BY_NAME = {o.name: o for o in OPERATIONS}


class PlatformTools:
    """Calls an operation's service for the person; `bases` maps a service to its address, `signer` is this service's
    key for service tokens."""

    def __init__(
        self, bases: dict[str, str], signer: Ed25519Signer | None, http: httpx.AsyncClient | None = None
    ) -> None:
        self.bases = {k: v.rstrip("/") for k, v in bases.items() if v} if signer is not None else {}
        self.http = http
        # Mints the token only; the call itself goes out on `http` so a refusal's body reaches the assistant.
        self.client = (
            ServiceClient(http or httpx.AsyncClient(timeout=TIMEOUT), signer, "tools", "agents")
            if signer is not None
            else None
        )

    def _headers(self, who: Principal, team: str, service: str, cells: tuple[str, ...]) -> dict[str, str]:
        """A service token for one call, naming the team and only the cells the person holds there."""
        assert self.client is not None
        held = [c for c in cells if ACCESS.may(who, *c.split(":", 1), team=team)]
        signed = replace(self.client, audience=service, scopes=held)
        return {**signed.headers(team=team, tenant=who.tenant_id), "Accept": "application/json"}

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

    async def call(self, name: str, args: dict[str, Any], *, who: Principal, team: str) -> types.CallToolResult:
        o = BY_NAME[name]
        path, rest = o.route(args)
        headers = self._headers(who, team, o.service, o.cells)
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

    async def _get(self, path: str, *, who: Principal, team: str, params: dict[str, Any] | None = None) -> Any:
        headers = self._headers(who, team, "agents", SKILLS_VIEW)
        async with _Client(self.http) as http:
            r = await http.get(f"{self.bases['agents']}{path}", headers=headers, params=params)
        r.raise_for_status()
        body: Any = r.json()
        return cast(dict[str, Any], body).get("data") if isinstance(body, dict) else body

    async def _skills(self, *, who: Principal, team: str) -> list[dict[str, Any]]:
        """The team's skills the caller can read, each with its newest content (its inputs are on the version)."""
        page: Any = await self._get("/v1/skills", who=who, team=team, params={"pageSize": 100})
        rows = cast(
            list[dict[str, Any]], cast(dict[str, Any], page).get("data") if isinstance(page, dict) else page or []
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            found: Any = await self._get(f"/v1/skills/{row['id']}", who=who, team=team)
            out.append(cast(dict[str, Any], found))
        return out

    async def prompts(self, *, who: Principal, team: str) -> list[types.Prompt]:
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
            for s in await self._skills(who=who, team=team)
        ]

    async def prompt(
        self, name: str, args: dict[str, str], *, who: Principal, team: str
    ) -> types.GetPromptResult | None:
        """The skill's instructions with the arguments given, or None when the team has no skill by that slug."""
        if "agents" not in self.bases:
            return None
        skill = next((s for s in await self._skills(who=who, team=team) if s["slug"] == name), None)
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
