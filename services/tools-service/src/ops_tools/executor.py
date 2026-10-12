"""Runs an allowed call: input checked against the operation's schema first, then the operation's executor.

`http` is ported from Protobox's HTTP executor: `{arg}` placeholders fill the URL path, a `{{arg}}` body template is
rendered with JSON-encoded values, the arguments the URL did not use become the query (GET, DELETE) or the JSON
body, and the operation's timeout (else the module's) applies. A failure names its side: ours (EGRESS_DENIED,
CONNECT_FAILED, TLS_FAILED, CONNECT_TIMEOUT, POOL_TIMEOUT) or the upstream's (UPSTREAM_TIMEOUT once connected, and
RATE_LIMITED, INVALID_ARGUMENTS or UPSTREAM_ERROR with the status it answered). Egress goes only to the module's
listed hosts. Output paths the operation masks are redacted before the result is returned or logged. Every request
follows the egress policy (`egress`): https to a listed host, and a connection only to an address the policy
checked.

A `{{NAME}}` secret reference in a header is resolved here, at call time, from the secrets store; an operation
whose secret is missing is refused rather than sent without its credential, and every resolved value is scrubbed
from what the call returns.
"""

from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urlsplit

import httpx

from ops_agent_kernel.ports import ToolOutcome

from . import mcp, transform
from .egress import CURRENT_TENANT, EgressDenied, EgressPolicy
from .registry import Resolved
from .secrets import SecretMissing, SecretResolver, scrub
from .tools import ToolRunner

URL_VAR = re.compile(r"\{([a-zA-Z0-9_]+)\}")
BODY_VAR = re.compile(r"\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}")
SECRET_REF = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
REDACTED = "[redacted]"
PYTHON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def invalid_fields(fields: list[dict[str, Any]], args: dict[str, Any]) -> list[dict[str, str]]:
    """Per-field problems with `args` against the operation's input fields; empty when the input is valid. Unknown
    arguments are refused too, so a caller cannot smuggle a field the reviewer never saw."""
    problems: list[dict[str, str]] = []
    known = {f["name"]: f for f in fields}
    for f in fields:
        value = args.get(f["name"])
        if value is None or value == "":
            if f["required"]:
                problems.append({"field": f["name"], "message": "Required."})
            continue
        allowed = PYTHON_TYPES.get(f["type"], (object,))
        # bool is an int in Python; a true/false is never a number here.
        if not isinstance(value, allowed) or (isinstance(value, bool) and f["type"] != "boolean"):
            problems.append({"field": f["name"], "message": f"Expected {f['type']}."})
        elif f.get("enum") and value not in f["enum"]:
            problems.append({"field": f["name"], "message": f"Must be one of {', '.join(f['enum'])}."})
    problems.extend({"field": k, "message": "Not an input of this operation."} for k in args if k not in known)
    return problems


def masked(output: Any, paths: list[str]) -> Any:
    """`output` with each dotted path replaced by a redaction marker."""
    if not paths or not isinstance(output, dict):
        return output
    out: dict[str, Any] = json.loads(json.dumps(output))
    for path in paths:
        node: Any = out
        *parents, last = path.split(".")
        for p in parents:
            node = cast(dict[str, Any], node).get(p) if isinstance(node, dict) else None
        if isinstance(node, dict) and last in node:
            node[last] = REDACTED
    return out


# Which side a failed call broke on: ours (policy, connect, TLS, pool) or the upstream's (it answered badly, or
# accepted the connection and then did not answer), so the call log tells the two apart.
OURS, UPSTREAM = "ours", "upstream"


def _failure(code: str, message: str, status: int | None = None, side: str | None = None) -> ToolOutcome:
    error: dict[str, Any] = {"code": code, "message": message}
    if status is not None:
        error["status"] = status
    if side is not None:
        error["side"] = side
    return ToolOutcome(False, {"error": error})


def _tls(e: BaseException) -> bool:
    seen: BaseException | None = e
    while seen is not None:
        if isinstance(seen, ssl.SSLError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def transport_failure(host: str | None, e: httpx.HTTPError, limit_ms: int) -> ToolOutcome:
    """A transport error by the phase httpx names in its exception class. The messages are fixed phrases: an
    exception's own text can carry the address that was dialled."""
    if isinstance(e, httpx.ConnectTimeout):
        return _failure("CONNECT_TIMEOUT", f"No connection to {host} was made within {limit_ms} ms.", side=OURS)
    if isinstance(e, httpx.PoolTimeout):
        return _failure("POOL_TIMEOUT", f"No free connection to {host} within {limit_ms} ms.", side=OURS)
    if isinstance(e, httpx.TimeoutException):
        return _failure(
            "UPSTREAM_TIMEOUT",
            f"{host} accepted the connection but did not answer within {limit_ms} ms.",
            side=UPSTREAM,
        )
    if isinstance(e, httpx.ConnectError):
        if _tls(e):
            return _failure("TLS_FAILED", f"The TLS handshake with {host} failed (certificate or protocol).", side=OURS)
        return _failure("CONNECT_FAILED", f"{host} could not be reached; no connection was made.", side=OURS)
    return _failure("UPSTREAM_ERROR", f"{host} broke off the exchange ({type(e).__name__}).", side=UPSTREAM)


def status_failure(host: str | None, status: int) -> ToolOutcome:
    """An answer the upstream gave: its status, on its side."""
    if status == 429:
        return _failure("RATE_LIMITED", f"{host} is rate limiting calls.", status, UPSTREAM)
    if status in (400, 422):
        return _failure("INVALID_ARGUMENTS", f"{host} refused the arguments.", status, UPSTREAM)
    return _failure("UPSTREAM_ERROR", f"{host} answered {status}.", status, UPSTREAM)


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    params: dict[str, Any]
    json_body: Any
    headers: dict[str, str]


def build_request(module: dict[str, Any], op: dict[str, Any], args: dict[str, Any]) -> HttpRequest:
    path = op.get("path") or "/"
    used = set(URL_VAR.findall(path))
    url = module["endpoint"].rstrip("/") + URL_VAR.sub(lambda m: quote(str(args.get(m.group(1), "")), safe=""), path)
    rest = {k: v for k, v in args.items() if k not in used}
    method = op.get("method") or "GET"
    body: Any = None
    params: dict[str, Any] = {}
    if op.get("body"):
        body = json.loads(BODY_VAR.sub(lambda m: json.dumps(args.get(m.group(1))), op["body"]))
    elif method in ("GET", "DELETE"):
        params = rest
    else:
        body = rest
    pairs: list[dict[str, str]] = op.get("headers") or []
    headers = {h["key"]: h["value"] for h in pairs}
    return HttpRequest(method, url, params, body, headers)


class _Secrets:
    """Shared by both executors: resolves `{{NAME}}` header references at call time, or fails the call naming the
    secret (never its value)."""

    secrets: SecretResolver | None

    async def _resolve(
        self, module: dict[str, Any], op: dict[str, Any], headers: dict[str, str], actor: str
    ) -> tuple[dict[str, str], list[str]] | ToolOutcome:
        if not any(SECRET_REF.search(v) for v in headers.values()):
            return headers, []
        if self.secrets is None:
            return _failure(
                "SECRET_UNAVAILABLE", "This operation needs a secret, and this gateway has no secrets store."
            )
        try:
            return await self.secrets.headers(module["tenant_id"], headers, tool=op["name"], actor=actor)
        except SecretMissing as e:
            return _failure("SECRET_MISSING", f"The secret {', '.join(e.names)} is not set for this tenant.")


class HttpExecutor(_Secrets):
    """`client` is `egress.egress_client(policy)` in production, whose connections pass the policy's address check;
    tests pass a client bound to an in-process fake. Without a policy no http operation runs."""

    def __init__(
        self, client: httpx.AsyncClient, policy: EgressPolicy | None, secrets: SecretResolver | None = None
    ) -> None:
        self.client = client
        self.policy = policy
        self.secrets = secrets

    async def run(
        self, module: dict[str, Any], op: dict[str, Any], args: dict[str, Any], *, actor: str = "gateway"
    ) -> ToolOutcome:
        req = build_request(module, op, args)
        host = urlsplit(req.url).hostname
        if self.policy is None:
            return _failure("EGRESS_DENIED", "This gateway has no egress policy, so it calls no external system.")
        if host not in module["egress_hosts"]:
            return _failure("EGRESS_DENIED", f"{host} is not one of this module's egress hosts.")
        resolved = await self._resolve(module, op, req.headers, actor)
        if isinstance(resolved, ToolOutcome):
            return resolved
        headers, used = resolved
        # The operation's own timeout when it has one, else the module's.
        limit_ms: int = op.get("timeout_ms") or module["timeout_ms"]
        token = CURRENT_TENANT.set(module["tenant_id"])
        try:
            await self.policy.check_url(module["tenant_id"], req.url)
            res = await self.client.request(
                req.method,
                req.url,
                params=req.params or None,
                json=req.json_body,
                headers=headers,
                timeout=limit_ms / 1000,
            )
        except EgressDenied as e:
            return _failure("EGRESS_DENIED", str(e), side=OURS)
        except httpx.HTTPError as e:
            return transport_failure(host, e, limit_ms)
        finally:
            CURRENT_TENANT.reset(token)
        if res.status_code >= 400:
            return status_failure(host, res.status_code)
        try:
            output: Any = res.json()
        except ValueError:
            output = {"text": res.text}
        # Scrubbed before the transform as well as after: a template given a secret could re-encode it (reverse,
        # join, a key lookup into an error) past any scrub of the literal value.
        output = scrub(masked(output, op.get("masked_output") or []), used)
        if op.get("response_transform"):
            shaped, failed = await transform.apply(op["response_transform"], output)
            # A transform that fails on a real answer still returns the answer, with why, instead of failing the call.
            output = shaped if failed is None else {"response": output, "transform_error": failed}
        # After the transform, so a template that repeats a header cannot carry a secret out.
        return ToolOutcome(True, scrub(output, used))


class McpExecutor(_Secrets):
    """Calls an imported MCP tool by its server name (the operation's `path`) through tools/call, on the egress
    policy's client like every other outbound request."""

    def __init__(
        self, client: httpx.AsyncClient, policy: EgressPolicy | None, secrets: SecretResolver | None = None
    ) -> None:
        self.client = client
        self.policy = policy
        self.secrets = secrets

    async def run(
        self, module: dict[str, Any], op: dict[str, Any], args: dict[str, Any], *, actor: str = "gateway"
    ) -> ToolOutcome:
        url: str = module["endpoint"]
        host = urlsplit(url).hostname
        if self.policy is None:
            return _failure("EGRESS_DENIED", "This gateway has no egress policy, so it calls no external system.")
        if host not in module["egress_hosts"]:
            return _failure("EGRESS_DENIED", f"{host} is not one of this module's egress hosts.")
        listed = {h["key"]: h["value"] for h in cast(list[dict[str, str]], op.get("headers") or [])}
        resolved = await self._resolve(module, op, listed, actor)
        if isinstance(resolved, ToolOutcome):
            return resolved
        headers, used = resolved
        token = CURRENT_TENANT.set(module["tenant_id"])
        try:
            await self.policy.check_url(module["tenant_id"], url)
            session = mcp.McpSession(self.client, url, headers=headers)
            await session.initialize()
            result = await session.call_tool(str(op["path"]), args)
        except EgressDenied as e:
            return _failure("EGRESS_DENIED", str(e), side=OURS)
        except mcp.McpError as e:
            # A transport failure wrapped by the session is located like any other call's.
            if isinstance(e.__cause__, httpx.HTTPError):
                return transport_failure(host, e.__cause__, mcp.TIMEOUT_MS)
            # The server's error text is its own and may repeat what it was sent.
            return _failure("UPSTREAM_ERROR", scrub(f"{host}: {e}", used), side=UPSTREAM)
        finally:
            CURRENT_TENANT.reset(token)
        ok, output = mcp.tool_output(result)
        if not ok:
            return _failure("TOOL_ERROR", f"{op['path']} on {host} reported an error.")
        return ToolOutcome(True, scrub(masked(output, op.get("masked_output") or []), used))


class Executor:
    """Runs a resolved call by its operation's executor."""

    def __init__(self, local: ToolRunner, http: HttpExecutor, mcp_executor: McpExecutor | None = None) -> None:
        self.local = local
        self.http = http
        self.mcp = mcp_executor or McpExecutor(http.client, http.policy, http.secrets)

    async def run(
        self, resolved: Resolved, tool: str, args: dict[str, Any], *, key: str, actor: str = "gateway"
    ) -> ToolOutcome:
        op, module = resolved.operation, resolved.module
        if resolved.executor == "local" or op is None or module is None:
            return await self.local.run(tool, args, key=key)
        if resolved.executor == "stub":
            return ToolOutcome(True, masked(op["stub"], op.get("masked_output") or []))
        if resolved.executor == "mcp":
            return await self.mcp.run(module, op, args, actor=actor)
        return await self.http.run(module, op, args, actor=actor)
