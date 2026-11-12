"""Public API operations offered as tools on the team MCP address, beside the team's own tools.

Each entry maps one operation of a service's public API to an MCP tool: its name, what it does, its input schema and
the route it calls. The call goes to the owning service as any call between services does: a service token of this
service, naming the team. The assistant's own token is never sent on, since its audience is this MCP address alone.
An operation that makes a record also sends an acting-for token for the person (X-Acting-For), so the record names
them as its maker.

The token carries the person by its scopes: of the cells an operation needs, only those the person holds in the team.
The owning service then decides with its own `can`, so a person without the create right of a template's kind is
refused there (403), exactly as in the console, and the refusal comes back as a tool error with the service's message.

Adding an operation is one entry in OPERATIONS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, cast
from urllib.parse import quote

import httpx
import mcp_types as types

from ops_access import Access
from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ACTING_FOR_HEADER, ActingForTokens, Principal, ServiceClient
from ops_policy import Ed25519Signer
from ops_service_kit.errors import ApiError

from .registry import Resolved

TIMEOUT = 15.0
# How the gateway runs an operation of this file (GatewayCalls.call with `run`); no registry module holds them.
PLATFORM = "platform"
# Skills read for prompts, one list call per page; a team past MAX_PAGES * PAGE skills is cut there.
PAGE, MAX_PAGES = 200, 20


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
    # The gateway's rate window for the operation, per tenant and minute.
    rate_limit_per_min: int = 60
    # A write that only makes a draft, which still needs its publish review: it does not wait as other MCP writes do.
    draft: bool = False


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
        draft=True,
    ),
)

BY_NAME = {o.name: o for o in OPERATIONS}

# prompts/list and prompts/get as gateway calls: reads named by their MCP method, never offered as tools.
PROMPTS = {
    n: Operation(
        name=n,
        description=d,
        input_schema={"type": "object"},
        service="agents",
        method="GET",
        route=lambda _a: ("/v1/skills", {}),
        read_only=True,
        cells=SKILLS_VIEW,
        rate_limit_per_min=120,
    )
    for n, d in (("prompts/list", "The team's skills as prompts."), ("prompts/get", "One skill as a prompt."))
}


class PlatformTools:
    """Calls an operation's service for the person; `bases` maps a service to its address, `signer` is this service's
    key for service tokens. Every call reaches here through GatewayCalls.call (mcp_server.py), which keeps its call log
    row and rate window and decides whether a write waits for a person; `resolved` is what the gateway decides by."""

    def __init__(
        self,
        bases: dict[str, str],
        signer: Ed25519Signer | None,
        http: httpx.AsyncClient | None = None,
        *,
        people: ActingForTokens | None = None,
    ) -> None:
        self.people = people
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

    async def _acting_for(self, who: Principal, team: str) -> dict[str, str]:
        """The person a write acts for, as a token platform-service signs, so the record it makes names them as its
        maker rather than this service; none for a caller who is not a person."""
        if self.people is None or who.kind != "person" or not who.email:
            return {}
        token = await self.people.token(tenant_id=who.tenant_id, email=who.email, team_id=team)
        return {ACTING_FOR_HEADER: token}

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

    def resolved(self, name: str) -> Resolved:
        """The operation as the gateway decides it: its access class and a rate window of its own per tenant. It is no
        module's operation, so no agent can be granted it and no module setting applies; the team's rule does."""
        o = BY_NAME.get(name) or PROMPTS[name]
        access = "read" if o.read_only else "write"
        return Resolved(
            access,
            PLATFORM,
            operation={"name": o.name, "access": access, "rate_limit_per_min": o.rate_limit_per_min, "draft": o.draft},
        )

    async def run(self, name: str, args: dict[str, Any], *, who: Principal, team: str) -> ToolOutcome:
        """One operation for the person: its answer, or {error: {code, message, status}} when the service refused it
        or could not be reached."""
        o = BY_NAME[name]
        path, rest = o.route(args)
        get = o.method == "GET"
        try:
            headers = self._headers(who, team, o.service, o.cells)
            if not o.read_only:
                headers.update(await self._acting_for(who, team))
            async with _Client(self.http) as http:
                r = await http.request(
                    o.method,
                    f"{self.bases[o.service]}{path}",
                    headers=headers,
                    params=rest if get else None,
                    json=None if get else rest,
                )
        except (httpx.HTTPError, ApiError) as e:
            # Minting the acting-for token or reaching the service failed: nothing was made.
            return _failed("SERVICE_UNAVAILABLE", 503, f"{o.service}-service did not answer: {type(e).__name__}")
        raw: Any = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        body = cast(dict[str, Any], raw) if isinstance(raw, dict) else {"data": raw}
        if r.is_success:
            out: Any = body.get("data", body)
            return ToolOutcome(
                True,
                {o.wrap: out} if o.wrap else (cast(dict[str, Any], out) if isinstance(out, dict) else {"result": out}),
            )
        err = cast(dict[str, Any], body.get("error") or {})
        return _failed(str(err.get("code") or r.status_code), r.status_code, str(err.get("message") or r.reason_phrase))

    async def _get(self, path: str, *, who: Principal, team: str, params: dict[str, Any] | None = None) -> Any:
        headers = self._headers(who, team, "agents", SKILLS_VIEW)
        async with _Client(self.http) as http:
            r = await http.get(f"{self.bases['agents']}{path}", headers=headers, params=params)
        r.raise_for_status()
        body: Any = r.json()
        return cast(dict[str, Any], body).get("data") if isinstance(body, dict) else body

    async def _skills(self, *, who: Principal, team: str) -> list[dict[str, Any]]:
        """The team's published skills the caller can read, one call per page; each row describes its published
        version, with its inputs and parts, so no draft or retired skill is offered."""
        out: list[dict[str, Any]] = []
        for n in range(1, MAX_PAGES + 1):
            params: dict[str, Any] = {"page": n, "pageSize": PAGE, "view": "published"}
            page: Any = await self._get("/v1/skills", who=who, team=team, params=params)
            body = cast(dict[str, Any], page) if isinstance(page, dict) else {}
            rows = cast(list[dict[str, Any]], body.get("data") or [])
            out.extend(rows)
            total = body.get("total")
            if len(rows) < PAGE or (isinstance(total, int) and len(out) >= total):
                break
        return out

    async def prompts(self, *, who: Principal, team: str) -> ToolOutcome:
        """Each published skill as an MCP prompt named by its slug, or one prompt per part named `<skill>-<part>`, its
        inputs as the prompt's arguments; none when the person may not read skills or agents-service does not
        answer."""
        if "agents" not in self.bases:
            return ToolOutcome(True, {"prompts": []})
        try:
            skills = await self._skills(who=who, team=team)
        except (httpx.HTTPError, ApiError) as e:
            return _failed("SKILLS_UNREADABLE", _status(e), f"The team's skills could not be read: {type(e).__name__}")
        return ToolOutcome(
            True,
            {
                "prompts": [
                    types.Prompt(
                        name=name,
                        title=title,
                        description=use_when,
                        arguments=[
                            types.PromptArgument(
                                name=str(i["name"]),
                                description=str(i.get("description") or ""),
                                required=bool(i.get("required")),
                            )
                            for i in inputs
                        ],
                    ).model_dump(mode="json", by_alias=True, exclude_none=True)
                    for name, (_, _, title, use_when, inputs) in _prompt_names(skills).items()
                ]
            },
        )

    async def prompt(self, name: str, args: dict[str, str], *, who: Principal, team: str) -> ToolOutcome:
        """The published skill's text, or one part's, with the arguments filled in by agents-service's render (the
        one owner of that step). A failed outcome when the team has no published prompt by that name, or render
        refuses it (a required argument missing, an argument the skill does not take)."""
        if "agents" not in self.bases:
            return _failed("NOT_FOUND", 404, f"No skill named {name} in this team.")
        try:
            found = _prompt_names(await self._skills(who=who, team=team)).get(name)
            if found is None:
                return _failed("NOT_FOUND", 404, f"No published skill named {name} in this team.")
            skill_id, part, title, _, _ = found
            headers = self._headers(who, team, "agents", SKILLS_VIEW)
            async with _Client(self.http) as http:
                r = await http.post(
                    f"{self.bases['agents']}/v1/skills/{skill_id}/render",
                    headers=headers,
                    json={"part": part, "inputs": args},
                )
        except (httpx.HTTPError, ApiError) as e:
            return _failed("SKILLS_UNREADABLE", _status(e), f"The team's skills could not be read: {type(e).__name__}")
        raw: Any = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        body = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
        if not r.is_success:
            err = cast(dict[str, Any], body.get("error") or {})
            return _failed(
                str(err.get("code") or r.status_code), r.status_code, str(err.get("message") or r.reason_phrase)
            )
        rendered = cast(dict[str, Any], body.get("data") or {})
        return ToolOutcome(
            True,
            types.GetPromptResult(
                description=title,
                messages=[
                    types.PromptMessage(
                        role="user", content=types.TextContent(type="text", text=str(rendered.get("text") or ""))
                    )
                ],
            ).model_dump(mode="json", by_alias=True, exclude_none=True),
        )


def _prompt_names(
    skills: list[dict[str, Any]],
) -> dict[str, tuple[str, str | None, str, str, list[dict[str, Any]]]]:
    """Prompt name -> (skill id, part slug, title, use-when, inputs): the skill's slug, or `<skill>-<part>` per part
    (MCP clients accept letters, digits and hyphens; agents-service refuses a part name that is another skill's)."""
    out: dict[str, tuple[str, str | None, str, str, list[dict[str, Any]]]] = {}
    for s in skills:
        slug, title = str(s["slug"]), str(s.get("name") or s["slug"])
        parts = cast(list[dict[str, Any]], s.get("parts") or [])
        if not parts:
            inputs = cast(list[dict[str, Any]], s.get("inputs") or [])
            out[slug] = (str(s["id"]), None, title, str(s.get("useWhen") or ""), inputs)
        for p in parts:
            out[f"{slug}-{p['slug']}"] = (
                str(s["id"]),
                str(p["slug"]),
                f"{title} · {p['name']}",
                str(p.get("useWhen") or ""),
                cast(list[dict[str, Any]], p.get("inputs") or []),
            )
    return out


def _failed(code: str, status: int, message: str) -> ToolOutcome:
    return ToolOutcome(False, {"error": {"code": code, "status": status, "message": message}})


def _status(e: Exception) -> int:
    return e.response.status_code if isinstance(e, httpx.HTTPStatusError) else 503


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
