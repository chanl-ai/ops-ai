"""Runs an allowed call: input checked against the operation's schema first, then the operation's executor.

`http` calls the module's endpoint: `{arg}` placeholders fill the URL path, a `{{arg}}` body template is
rendered with JSON-encoded values, the arguments the URL did not use become the query (GET, DELETE) or the JSON
body, and the operation's timeout (else the module's) applies. A failure names its side: ours (EGRESS_DENIED,
CONNECT_FAILED, TLS_FAILED, CONNECT_TIMEOUT, POOL_TIMEOUT) or the upstream's (UPSTREAM_TIMEOUT once connected, and
RATE_LIMITED, INVALID_ARGUMENTS or UPSTREAM_ERROR with the status it answered). Egress goes only to the module's
listed hosts. Output paths the operation masks are redacted before the result is returned or logged. Every request
follows the egress policy (`egress`): https to a listed host, and a connection only to an address the policy
checked.

A `{{NAME}}` secret reference in a header, a path segment or a query value of the operation's path is resolved here,
at call time, from the secrets store; an operation whose secret is missing is refused rather than sent without its
credential, and every resolved value is scrubbed from what the call returns. References are read from the operation's
own definition only, never from a caller's arguments, which are URL-encoded before they reach the path.

A module with a connection signs in through it (`auth.Authenticator`, c-330): its strategy adds headers, query values
or a client certificate for the call's environment, after the operation's own, so a connection's credential is never
replaced by an operation header of the same name. A read the system refuses with 401 is sent once more with a new
token when the connection holds one; a write is not, since the system may have acted (AUTH_EXPIRED).
"""

from __future__ import annotations

import json
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit

import httpx

from ops_agent_kernel.ports import ToolOutcome

from . import mcp, transform
from .auth import Authenticator, AuthFailed, Prepared
from .egress import EgressDenied, EgressPolicy, for_tenant
from .mocks import MockAnswers
from .registry import Resolved
from .secrets import SecretMissing, SecretOutOfScope, SecretResolver, scrub
from .tools import ToolCaller, ToolRunner

# A single-brace argument placeholder; the inner braces of a `{{NAME}}` secret reference are not one.
URL_VAR = re.compile(r"(?<!\{)\{([a-zA-Z0-9_]+)\}(?!\})")
BODY_VAR = re.compile(r"\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}")
ESCAPE = re.compile(r"%[0-9A-F]{2}")
SECRET_REF = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
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


def with_defaults(fields: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    """`args` with each optional field the call left out set to its default, as the agent's schema promised."""
    filled = dict(args)
    for f in fields:
        if f.get("default") is not None and args.get(f["name"]) in (None, ""):
            filled[f["name"]] = f["default"]
    return filled


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


def auth_failure(e: AuthFailed) -> ToolOutcome:
    return _failure(e.code, str(e), e.status, e.side)


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


def _with_auth(req: HttpRequest, prepared: Prepared | None) -> tuple[dict[str, Any], dict[str, str]]:
    """The query and headers sent: the operation's, then the connection's, which win over a name they share."""
    if prepared is None:
        return req.params, req.headers
    return {**req.params, **prepared.params}, {**req.headers, **prepared.headers}


@dataclass
class Trial:
    """What the test console shows of one call (c-088): the request as sent and the gateway's steps, both with every
    secret value scrubbed, and the answer before any transform. Filled only for a test; a gateway call passes none."""

    request: dict[str, Any] | None = None
    raw: Any = None
    # The resolved secret values: the caller scrubs its draft transform's output with them, as the gateway does.
    used: list[str] = field(default_factory=list[str])
    log: list[tuple[float, str]] = field(default_factory=list[tuple[float, str]])
    started: float = field(default_factory=time.perf_counter)

    def note(self, message: str) -> None:
        self.log.append((round((time.perf_counter() - self.started) * 1000, 1), message))


def secret_names(op: dict[str, Any]) -> list[str]:
    """The secrets an operation's headers and path name, each once."""
    texts = [h["value"] for h in cast(list[dict[str, str]], op.get("headers") or [])] + [op.get("path") or ""]
    return sorted({n for t in texts for n in SECRET_REF.findall(t)})


def build_request(
    module: dict[str, Any], op: dict[str, Any], args: dict[str, Any], secrets: dict[str, str] | None = None
) -> HttpRequest:
    """The request an operation makes. `secrets` resolves the `{{NAME}}` references; without it they stay as written,
    which is enough to read the host. The path's own query (`?api_key={{KEY}}`) is sent alongside the arguments:
    httpx would otherwise drop it in favour of `params`."""
    values = secrets or {}

    def secret(m: re.Match[str], encode: bool) -> str:
        if m.group(1) not in values:
            return m.group(0)
        return quote(values[m.group(1)], safe="") if encode else values[m.group(1)]

    template, _, query = (op.get("path") or "/").partition("?")
    used = set(URL_VAR.findall(template))
    # Secrets first, URL-encoded; then the caller's arguments, URL-encoded, so neither can form a reference.
    path = URL_VAR.sub(
        lambda m: quote(str(args.get(m.group(1), "")), safe=""), SECRET_REF.sub(lambda m: secret(m, True), template)
    )
    url = module["endpoint"].rstrip("/") + path
    fixed = {k: SECRET_REF.sub(lambda m: secret(m, False), v) for k, v in parse_qsl(query, keep_blank_values=True)}
    rest = {k: v for k, v in args.items() if k not in used}
    method = op.get("method") or "GET"
    body: Any = None
    params: dict[str, Any] = dict(fixed)
    if op.get("body"):
        body = json.loads(BODY_VAR.sub(lambda m: json.dumps(args.get(m.group(1))), op["body"]))
    elif method in ("GET", "DELETE"):
        # The operation's own query wins over an argument of the same name: a caller cannot replace a credential.
        params = {**rest, **fixed}
    else:
        body = rest
    pairs: list[dict[str, str]] = op.get("headers") or []
    headers = {h["key"]: SECRET_REF.sub(lambda m: secret(m, False), h["value"]) for h in pairs}
    return HttpRequest(method, url, params, body, headers)


class _Secrets:
    """Shared by both executors: resolves the `{{NAME}}` references an operation names at call time, or fails the call
    naming the secret (never its value), and signs the call in through the module's connection."""

    secrets: SecretResolver | None
    auth: Authenticator | None

    async def _signed_in(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        environment: str | None,
        actor: str,
        *,
        trial: Trial | None = None,
        stale_rotation: int | None = None,
    ) -> Prepared | None:
        if self.auth is None:
            return None
        prepared = await self.auth.prepare(
            module, environment, tool=str(op["name"]), actor=actor, stale_rotation=stale_rotation
        )
        if prepared is not None and trial is not None:
            trial.note(f"Signed in through the connection ({prepared.environment})")
        return prepared

    async def _resolve(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        actor: str,
        given: dict[str, str] | None = None,
        trial: Trial | None = None,
    ) -> dict[str, str] | ToolOutcome:
        """`given`: values typed for one test call, used for the names they cover and never stored; the rest come from
        the tenant's secrets."""
        names = secret_names(op)
        if not names:
            return {}
        typed = {n: v for n, v in (given or {}).items() if n in names and v}
        rest = [n for n in names if n not in typed]
        if trial is not None:
            for n in names:
                trial.note(
                    f"Secret {n} from " + ("the value typed for this run" if n in typed else "the tenant's secrets")
                )
        if not rest:
            return typed
        if self.secrets is None:
            return _failure(
                "SECRET_UNAVAILABLE", "This operation needs a secret, and this gateway has no secrets store."
            )
        try:
            looked = await self.secrets.lookup(
                module["tenant_id"], rest, tool=op["name"], actor=actor, team=module.get("team_id")
            )
            return {**looked, **typed}
        except SecretOutOfScope as e:
            return _failure(
                "SECRET_OUT_OF_SCOPE", f"The secret {', '.join(e.names)} is not available to this module's team."
            )
        except SecretMissing as e:
            return _failure("SECRET_MISSING", f"The secret {', '.join(e.names)} is not set for this tenant.")


def scrubbed_values(secrets: dict[str, str]) -> list[str]:
    """Every form a resolved value can come back in: as sent in a header, URL-encoded as in a path, and form-encoded
    as in a query (a space as `+`), the last two with upper- or lowercase escapes, as an upstream repeating its URL
    would show them."""
    out: set[str] = set()
    for v in secrets.values():
        if v:
            encoded = {quote(v, safe=""), quote(v), quote_plus(v, safe=""), quote_plus(v)}
            # Escapes are case-insensitive; a server repeating the URL may write %2f for %2F.
            out |= {v, *encoded, *(ESCAPE.sub(lambda m: m.group(0).lower(), e) for e in encoded)}
    return sorted(out)


def _scrub_set(resolved: dict[str, str], prepared: Prepared | None) -> list[str]:
    """Every value this call resolved, the operation's secrets and the connection's alike, in each form it can come
    back in."""
    extra = {f"connection:{n}": v for n, v in enumerate(prepared.values if prepared else [])}
    return scrubbed_values({**resolved, **extra})


class HttpExecutor(_Secrets):
    """`client` is `egress.egress_client(policy)` in production, whose connections pass the policy's address check;
    tests pass a client bound to an in-process fake. Without a policy no http operation runs."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        policy: EgressPolicy | None,
        secrets: SecretResolver | None = None,
        auth: Authenticator | None = None,
    ) -> None:
        """`auth` signs a module's calls in through its connection; without it a connection adds nothing."""
        self.client = client
        self.policy = policy
        self.secrets = secrets
        self.auth = auth

    async def run(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        *,
        actor: str = "gateway",
        secret_values: dict[str, str] | None = None,
        trial: Trial | None = None,
        environment: str | None = None,
    ) -> ToolOutcome:
        """With `trial` (the test console) the operation's own transform is not applied: the console applies its draft
        to `trial.raw`. `secret_values` are a test's typed values (_Secrets._resolve). `environment` is the run's (test
        or production), which picks the connection's settings."""
        host = urlsplit(build_request(module, op, args).url).hostname
        if self.policy is None:
            return _failure("EGRESS_DENIED", "This gateway has no egress policy, so it calls no external system.")
        if host not in module["egress_hosts"]:
            return _failure("EGRESS_DENIED", f"{host} is not one of this module's egress hosts.")
        if trial is not None:
            trial.note(f"Egress allowed: {host}")
        resolved = await self._resolve(module, op, actor, secret_values, trial)
        if isinstance(resolved, ToolOutcome):
            return resolved
        try:
            prepared = await self._signed_in(module, op, environment, actor, trial=trial)
        except AuthFailed as e:
            return auth_failure(e)
        req = build_request(module, op, args, resolved)
        used = _scrub_set(resolved, prepared)
        if trial is not None:
            trial.used = used
            sent = str(httpx.URL(req.url, params=_with_auth(req, prepared)[0] or None))
            trial.request = scrub(
                {
                    "method": req.method,
                    "url": sent,
                    "headers": [{"key": k, "value": v} for k, v in _with_auth(req, prepared)[1].items()],
                    **({"body": json.dumps(req.json_body)} if req.json_body is not None else {}),
                },
                used,
            )
        # The operation's own timeout when it has one, else the module's.
        limit_ms: int = op.get("timeout_ms") or module["timeout_ms"]
        try:
            await self.policy.check_url(module["tenant_id"], req.url)
            res = await self._send(module, req, prepared, limit_ms)
            if res.status_code == 401 and prepared is not None and prepared.renewable:
                if op.get("access") != "read":
                    # The system may have acted before refusing; a write is never sent twice by the gateway.
                    return _failure(
                        "AUTH_EXPIRED",
                        f"{host} refused the connection's token; the write was not sent again.",
                        401,
                        OURS,
                    )
                if trial is not None:
                    trial.note(f"{host} answered 401; signing in again once")
                try:
                    prepared = await self._signed_in(module, op, environment, actor, stale_rotation=prepared.rotation)
                except AuthFailed as e:
                    return auth_failure(e)
                used = sorted({*used, *_scrub_set(resolved, prepared)})
                if trial is not None:
                    trial.used = used
                res = await self._send(module, req, prepared, limit_ms)
        except EgressDenied as e:
            # The policy may name the URL it refused, which now carries resolved secrets.
            return _failure("EGRESS_DENIED", scrub(str(e), used), side=OURS)
        except httpx.HTTPError as e:
            return transport_failure(host, e, limit_ms)
        if trial is not None:
            trial.note(f"{host} answered {res.status_code}")
        if res.status_code >= 400:
            return status_failure(host, res.status_code)
        try:
            output: Any = res.json()
        except ValueError:
            output = {"text": res.text}
        # Scrubbed before the transform as well as after: a template given a secret could re-encode it (reverse,
        # join, a key lookup into an error) past any scrub of the literal value.
        output = scrub(masked(output, op.get("masked_output") or []), used)
        if trial is not None:
            trial.raw = output
            return ToolOutcome(True, output)
        if op.get("response_transform"):
            shaped, failed = await transform.apply(op["response_transform"], output)
            # A transform that fails on a real answer still returns the answer, with why, instead of failing the call.
            output = shaped if failed is None else {"response": output, "transform_error": failed}
        # After the transform, so a template that repeats a header cannot carry a secret out.
        return ToolOutcome(True, scrub(output, used))

    async def _send(
        self, module: dict[str, Any], req: HttpRequest, prepared: Prepared | None, limit_ms: int
    ) -> httpx.Response:
        params, headers = _with_auth(req, prepared)
        return await self.client.request(
            req.method,
            req.url,
            params=params or None,
            json=req.json_body,
            headers=headers,
            timeout=limit_ms / 1000,
            extensions=for_tenant(module["tenant_id"], prepared.certificate if prepared else None),
        )


class McpExecutor(_Secrets):
    """Calls an imported MCP tool by its server name (the operation's `path`) through tools/call, on the egress
    policy's client like every other outbound request. A module with a connection signs in through it as an http one
    does (c-331); the token goes only to the module's endpoint, the server it was issued for."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        policy: EgressPolicy | None,
        secrets: SecretResolver | None = None,
        auth: Authenticator | None = None,
    ) -> None:
        self.client = client
        self.policy = policy
        self.secrets = secrets
        self.auth = auth

    async def _call(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        headers: dict[str, str],
        prepared: Prepared | None,
    ) -> dict[str, Any]:
        session = mcp.McpSession(
            self.client,
            str(module["endpoint"]),
            headers={**headers, **(prepared.headers if prepared else {})},
            tenant_id=module["tenant_id"],
            certificate=prepared.certificate if prepared else None,
        )
        await session.initialize()
        return await session.call_tool(str(op["path"]), args)

    async def run(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        args: dict[str, Any],
        *,
        actor: str = "gateway",
        secret_values: dict[str, str] | None = None,
        trial: Trial | None = None,
        environment: str | None = None,
    ) -> ToolOutcome:
        url: str = module["endpoint"]
        host = urlsplit(url).hostname
        if self.policy is None:
            return _failure("EGRESS_DENIED", "This gateway has no egress policy, so it calls no external system.")
        if host not in module["egress_hosts"]:
            return _failure("EGRESS_DENIED", f"{host} is not one of this module's egress hosts.")
        resolved = await self._resolve(module, op, actor, secret_values, trial)
        if isinstance(resolved, ToolOutcome):
            return resolved
        values: dict[str, str] = resolved
        headers = {
            h["key"]: SECRET_REF.sub(lambda m: values.get(m.group(1), m.group(0)), h["value"])
            for h in cast(list[dict[str, str]], op.get("headers") or [])
        }
        try:
            prepared = await self._signed_in(module, op, environment, actor, trial=trial)
        except AuthFailed as e:
            return auth_failure(e)
        used = _scrub_set(resolved, prepared)
        if trial is not None:
            trial.used = used
        try:
            await self.policy.check_url(module["tenant_id"], url)
            try:
                result = await self._call(module, op, args, headers, prepared)
            except mcp.McpError as e:
                if e.status != 401 or prepared is None or not prepared.renewable:
                    raise
                if op.get("access") != "read":
                    return _failure(
                        "AUTH_EXPIRED",
                        f"{host} refused the connection's token; the call was not sent again.",
                        401,
                        OURS,
                    )
                try:
                    prepared = await self._signed_in(module, op, environment, actor, stale_rotation=prepared.rotation)
                except AuthFailed as failed:
                    return auth_failure(failed)
                used = sorted({*used, *_scrub_set(resolved, prepared)})
                result = await self._call(module, op, args, headers, prepared)
        except EgressDenied as e:
            return _failure("EGRESS_DENIED", str(e), side=OURS)
        except mcp.McpError as e:
            # A transport failure wrapped by the session is located like any other call's.
            if isinstance(e.__cause__, httpx.HTTPError):
                return transport_failure(host, e.__cause__, mcp.TIMEOUT_MS)
            if e.status is not None:
                return status_failure(host, e.status)
            # The server's error text is its own and may repeat what it was sent.
            return _failure("UPSTREAM_ERROR", scrub(f"{host}: {e}", used), side=UPSTREAM)
        ok, output = mcp.tool_output(result)
        if not ok:
            return _failure("TOOL_ERROR", f"{op['path']} on {host} reported an error.")
        output = scrub(masked(output, op.get("masked_output") or []), used)
        if trial is not None:
            trial.note(f"{op['path']} on {host} answered")
            trial.raw = output
        return ToolOutcome(True, output)


class Executor:
    """Runs a resolved call by its operation's executor."""

    def __init__(
        self,
        local: ToolRunner,
        http: HttpExecutor,
        mcp_executor: McpExecutor | None = None,
        mocks: MockAnswers | None = None,
    ) -> None:
        """`mocks` answers a test call from the operation's mock answers (c-332); without it none is read."""
        self.local = local
        self.http = http
        self.mcp = mcp_executor or McpExecutor(http.client, http.policy, http.secrets, http.auth)
        self.mocks = mocks

    async def _mocked(self, module: dict[str, Any], op: dict[str, Any], mock: dict[str, Any]) -> ToolOutcome:
        """A test call answered as the system would have, before any egress (c-332): the same failures a real answer
        or a real timeout gives, so a workflow's ports behave as they would against the system."""
        assert self.mocks is not None
        limit_ms: int = op.get("timeout_ms") or module["timeout_ms"]
        host = urlsplit(str(module["endpoint"])).hostname
        await self.mocks.wait(mock, limit_ms)
        if mock["timeout"]:
            failed = transport_failure(host, httpx.ReadTimeout("mock"), limit_ms)
        elif int(mock["status"]) >= 400:
            failed = status_failure(host, int(mock["status"]))
        else:
            return ToolOutcome(True, masked(mock.get("body"), op.get("masked_output") or []))
        error = cast(dict[str, Any], failed.output)["error"]
        error["mock"] = mock["id"]
        if mock.get("body") is not None:
            error["body"] = masked(mock["body"], op.get("masked_output") or [])
        return failed

    async def run(
        self,
        resolved: Resolved,
        tool: str,
        args: dict[str, Any],
        *,
        key: str,
        caller: ToolCaller,
        environment: str | None = None,
    ) -> ToolOutcome:
        """`caller` is the verified caller the gateway decided for: every executor path acts for it alone.
        `environment` is the run's (test or production; test when None), which picks a connection's settings."""
        op, module = resolved.operation, resolved.module
        if module is not None and module["tenant_id"] != caller.tenant_id:
            raise ValueError("A module is run only for its own tenant.")
        actor = caller.sub
        if resolved.executor == "local" or op is None or module is None:
            return await self.local.run(tool, args, key=key, caller=caller)
        if resolved.executor == "stub":
            return ToolOutcome(True, masked(op["stub"], op.get("masked_output") or []))
        # Defaults fill reads only. A write runs exactly the input its approval token binds (the hash of what the
        # approver saw), so nothing the approver did not see is added to it.
        if resolved.access == "read":
            args = with_defaults(op.get("input") or [], args)
        if self.mocks is not None and (
            mock := await self.mocks.for_call(caller.tenant_id, op["name"], args, environment)
        ):
            return await self._mocked(module, op, mock)
        if resolved.executor == "mcp":
            return await self.mcp.run(module, op, args, actor=actor, environment=environment)
        return await self.http.run(module, op, args, actor=actor, environment=environment)
