"""Runs a plugin's Python tool in this process, after the gateway has decided the call (c-564).

The function gets a Context: the team's merged settings, an HTTP client and a deadline. The client is the only way out:
it sends to the module's egress hosts (rendered from the team's settings) and nowhere else, through the tenant's egress
policy, with the credential the call's sign-in setting picks, and the function never sees the token. A knowledge
listing's next-page address is sealed to the tenant, the connection and the tool before it leaves, and a cursor comes
back only if it opens for the same three, so a caller cannot choose a host the token is sent to.

A data tool that pages, builds a query or has inputs to check runs here too (c-581): each value is checked against its
manifest input and written into the query by its format (ops_plugin_sdk.formats), so a model's value cannot change the
query; then the http executor sends it. An agent's call gets one page and a sealed `next_cursor` for the next; a page
address the system answered is followed only as a GET to one of the module's hosts, carrying the connection's sign-in
and nothing of the first call."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import httpx

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ActingForPerson
from ops_plugin_sdk import BadInput, Context, NeedsReconnect, Plugin, PluginError, RateLimited, Response
from ops_plugin_sdk import EgressDenied as PluginEgressDenied
from ops_plugin_sdk import paging as paged
from ops_plugin_sdk.formats import InputRefused
from ops_plugin_sdk.manifest import Tool

from ..auth import AuthFailed, Prepared
from ..egress import EgressDenied, for_tenant
from ..executor import scrubbed_values
from ..graph_mailbox import CursorRefused, CursorSeal
from ..secrets import scrub

if TYPE_CHECKING:
    from ..executor import HttpExecutor
    from .host import PluginHost

OURS = "ours"
DEADLINE_S = 30.0


def _failure(code: str, message: str, status: int | None = None, side: str | None = None) -> ToolOutcome:
    error: dict[str, Any] = {"code": code, "message": message}
    if status is not None:
        error["status"] = status
    if side is not None:
        error["side"] = side
    return ToolOutcome(False, {"error": error})


class PluginExecutor:
    def __init__(self, host: PluginHost, http: HttpExecutor, cursor_key: bytes) -> None:
        self.host = host
        self.http = http
        self.cursor_key = cursor_key

    def _seal(self, module: Mapping[str, Any], tool: str) -> CursorSeal:
        return CursorSeal(self.cursor_key, str(module["tenant_id"]), str(module.get("connection_id") or ""), tool)

    async def run(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        *,
        actor: str,
        environment: str | None,
        acting_for: ActingForPerson | None,
    ) -> ToolOutcome:
        plugin = self.host.by_module(module)
        if plugin is None:
            return _failure("PLUGIN_DISABLED", f"{module['display_name']} is not installed on this service.")
        name = str(op["name"]).removeprefix(f"{plugin.manifest.short}_")
        tool = plugin.manifest.tool(name)
        if tool is not None and tool.request is not None:
            return await self._data(tool, module, op, args, actor=actor, environment=environment, acting_for=acting_for)
        if tool is None or tool.function is None:
            return _failure("PLUGIN_FAILED", f"{op['name']} has no Python function in {plugin.manifest.id}.")
        try:
            prepared = await self.http._signed_in(module, op, environment, actor, acting_for=acting_for)  # pyright: ignore[reportPrivateUsage]
        except AuthFailed as e:
            return ToolOutcome(False, {"error": {"code": e.code, "message": str(e), "side": OURS}})
        # A Python tool sees what the system answers, and a system may repeat the request's sign-in back; nothing it
        # returns or raises may carry the connection's credential, as the http executor's answers never do (c-588).
        used = scrubbed_values({f"connection:{n}": v for n, v in enumerate(prepared.values if prepared else [])})
        outcome = await self._python(plugin, tool, module=module, op=op, args=args, prepared=prepared)
        return replace(outcome, output=scrub(outcome.output, used))

    async def _python(
        self,
        plugin: Plugin,
        tool: Tool,
        *,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        prepared: Prepared | None,
    ) -> ToolOutcome:
        """One Python tool's call through the SDK's context, its requests sent signed in as `prepared`."""
        name = tool.name
        allowed = list(module.get("egress_hosts") or [])
        loop = asyncio.get_running_loop()
        policy = self.http.policy
        client = self.http.client
        tenant = str(module["tenant_id"])

        async def request(method: str, url: str, params: Mapping[str, Any] | None, body: Any) -> Response:
            if policy is None:
                raise PluginEgressDenied("This gateway has no egress policy, so it calls no external system.")
            try:
                await policy.check_url(tenant, url)
            except EgressDenied as e:
                raise PluginEgressDenied(str(e)) from e
            headers = dict(prepared.headers) if prepared else {}
            query = {**(dict(params or {})), **(dict(prepared.params) if prepared else {})}
            r = await client.request(
                method,
                url,
                params=query or None,
                json=body,
                headers=headers,
                timeout=DEADLINE_S,
                extensions=for_tenant(tenant, prepared.certificate if prepared else None),
            )
            if r.status_code == 401:
                raise NeedsReconnect(f"{urlsplit(url).hostname} refused the connection's sign-in.")
            if r.status_code == 429:
                raise RateLimited(f"{urlsplit(url).hostname} answered 429: its rate limit was reached.")
            return Response(r.status_code, r.text, dict(r.headers))

        def send(method: str, url: str, params: Mapping[str, Any] | None, body: Any) -> Response:
            host = urlsplit(url).hostname
            # Checked here, before the request is built: the module's hosts are the plugin's, from the team's settings.
            if host not in allowed:
                raise PluginEgressDenied(f"{host} is not one of {plugin.manifest.title}'s hosts.")
            return asyncio.run_coroutine_threadsafe(request(method, url, params, body), loop).result(DEADLINE_S)

        given = dict(args)
        seal = self._seal(module, op["name"]) if tool.knowledge == "list_items" else None
        if seal is not None and given.get("cursor"):
            try:
                given["cursor"] = seal.open(str(given["cursor"]))
            except CursorRefused as e:
                return _failure("INVALID_INPUT", str(e), 422, OURS)
        fn = plugin.function(name)
        accepted = set(inspect.signature(fn).parameters) - {"ctx"}
        unknown = sorted(set(given) - accepted)
        if unknown:
            return _failure("INVALID_INPUT", f"{op['name']} takes no {', '.join(unknown)}.", 422, OURS)
        ctx = Context.of(dict(module.get("plugin_settings") or {}), send, timeout_s=DEADLINE_S)
        try:
            output = await asyncio.to_thread(fn, ctx, **given)
        except PluginEgressDenied as e:
            return _failure("EGRESS_DENIED", str(e), side=OURS)
        except NeedsReconnect as e:
            return _failure("AUTH_EXPIRED", str(e), 401)
        except RateLimited as e:
            return _failure("RATE_LIMITED", str(e), 429)
        except BadInput as e:
            return _failure("INVALID_INPUT", str(e), 422, OURS)
        except PluginError as e:
            return _failure(e.code, str(e))
        except httpx.HTTPError as e:
            return _failure("UPSTREAM_UNREACHABLE", f"{type(e).__name__} reaching {plugin.manifest.title}.")
        except Exception as e:  # the plugin's own bug: reported as its failure, never as the gateway's
            return _failure("PLUGIN_FAILED", f"{plugin.manifest.id} {name} failed: {type(e).__name__}: {e}")
        if seal is not None and isinstance(output, dict):
            page = cast(dict[str, Any], output)
            if page.get("next_cursor"):
                output = {**page, "next_cursor": seal.close(str(page["next_cursor"]))}
        return ToolOutcome(True, output)

    async def _data(
        self,
        tool: Tool,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        *,
        actor: str,
        environment: str | None,
        acting_for: ActingForPerson | None,
    ) -> ToolOutcome:
        req = tool.request
        assert req is not None
        paging = req.paging
        seal = self._seal(module, op["name"])
        given = dict(args)
        state: dict[str, Any] | None = None
        # A paged tool's cursor is the platform's, sealed here, even where the manifest declares it as an input.
        cursor = given.pop("cursor", None) if paging is not None else None
        if cursor:
            try:
                state = cast(dict[str, Any], json.loads(seal.open(str(cursor))))
            except (CursorRefused, ValueError) as e:
                return _failure("INVALID_INPUT", str(e), 422, OURS)
            # Every page after the first reads the query the first page was asked with, whatever this call says.
            given = dict(state.get("args") or {})
        # A first page needs the tool's required inputs; a next page reads them from its cursor.
        missing = [n for n, f in tool.input.items() if f.required and n != "cursor" and given.get(n) in (None, "")]
        if state is None and missing:
            return _failure("INVALID_INPUT", f"{op['name']} needs {', '.join(missing)}.", 422, OURS)
        try:
            sent = paged.arguments(tool, given, state)
        except InputRefused as e:
            return _failure("INVALID_INPUT", str(e), 422, OURS)
        target, call = module, op
        if state is not None and paging is not None and paging.rule == "link":
            followed = paged.follow(str(module["endpoint"]), str(state.get("link") or ""))
            if followed is None:
                return _failure("INVALID_INPUT", "This cursor holds no page address this plugin can follow.", 422, OURS)
            target, call = (
                {**module, "endpoint": followed[0]},
                {**op, "method": "GET", "path": followed[1], "body": None},
            )
            sent = {}
        offset = int(sent.get(paging.offset_param, 0)) if paging is not None and paging.rule == "offset" else 0
        found: dict[str, Any] = {}

        def on_answer(answer: Any) -> Any:
            shown, nxt = paged.next_page(paging, answer, offset)
            found.update(nxt)
            return shown

        out = await self.http.run(
            target, call, sent, actor=actor, environment=environment, acting_for=acting_for, on_answer=on_answer
        )
        if not out.ok or not found:
            return out
        sealed = seal.close(json.dumps({**found, "args": given}))
        assert sealed is not None
        return ToolOutcome(True, paged.with_next(out.output, sealed))
