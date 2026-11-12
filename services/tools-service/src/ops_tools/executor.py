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

A module with a connection signs in through it (`auth.Authenticator`): its strategy adds headers, query values
or a client certificate for the call's environment, after the operation's own, so a connection's credential is never
replaced by an operation header of the same name. A read the system refuses with 401 is sent once more with a new
token when the connection holds one; a write is not, since the system may have acted (AUTH_EXPIRED).
"""

from __future__ import annotations

import json
import re
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit

import httpx

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ActingForPerson
from ops_plugin_sdk import NeedsReconnect
from ops_plugin_sdk.answers import answer_error

from . import mcp, transform
from .auth import Authenticator, AuthFailed, Prepared
from .auth.tokens import scope_list
from .egress import EgressDenied, EgressPolicy, for_tenant
from .environments import TEST
from .mocks import MockAnswers
from .plugins.host import plugin_id_of
from .registry import Resolved
from .secrets import SecretMissing, SecretResolver, scrub
from .tools import ToolCaller, ToolRunner

if TYPE_CHECKING:
    from .code_runs import CodeExecutor
    from .plugins.executor import PluginExecutor

# A single-brace argument placeholder; the inner braces of a `{{NAME}}` secret reference are not one.
URL_VAR = re.compile(r"(?<!\{)\{([a-zA-Z0-9_]+)\}(?!\})")
BODY_VAR = re.compile(r"\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}")
ESCAPE = re.compile(r"%[0-9A-F]{2}")
SECRET_REF = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
# A query value's references: a secret (group 1) or an argument (group 2).
QUERY_REF = re.compile(f"{SECRET_REF.pattern}|{URL_VAR.pattern}")
REDACTED = "[redacted]"
PYTHON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


# The scope a knowledge source's sync calls with: only those calls reach the hosts the source's own settings name.
SOURCE_SYNC_SCOPE = "knowledge:run"


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


def with_access(e: AuthFailed, op: Mapping[str, Any], module: Mapping[str, Any]) -> AuthFailed:
    """A person's sign-in request names the app and whether the call reads or changes something, so the chat asks in
    those words ("reads Salesforce as you", "makes the change in your name")."""
    if e.code == "CONNECTION_NOT_LINKED":
        e.details["access"] = "write" if op.get("access") == "write" else "read"
        if module.get("display_name"):
            e.details["app"] = str(module["display_name"])
    return e


def auth_failure(e: AuthFailed) -> ToolOutcome:
    outcome = _failure(e.code, str(e), e.status, e.side)
    if e.details:
        outcome.output["error"]["details"] = e.details
    return outcome


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
    # A form-encoded body in place of the JSON one (a plugin's form tool, or a form operation).
    form: dict[str, str] | None = None
    # A raw body, sent as the text it is with the operation's own Content-Type.
    content: str | None = None


def _with_auth(req: HttpRequest, prepared: Prepared | None) -> tuple[dict[str, Any], dict[str, str]]:
    """The query and headers sent: the operation's, then the connection's, which win over a name they share."""
    if prepared is None:
        return req.params, req.headers
    return {**req.params, **prepared.params}, {**req.headers, **prepared.headers}


@dataclass
class Trial:
    """What the test console shows of one call: the request as sent and the gateway's steps, both with every
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
    which is enough to read the host. The path's own query (`?api_key={{KEY}}`, `?email={email}`) is sent alongside the
    arguments it does not name: httpx would otherwise drop it in favour of `params`."""
    values = secrets or {}

    def secret(m: re.Match[str], encode: bool) -> str:
        if m.group(1) not in values:
            return m.group(0)
        return quote(values[m.group(1)], safe="") if encode else values[m.group(1)]

    def argument(name: str) -> str:
        value = args.get(name)
        return "" if value is None else str(value)

    template, _, query = (op.get("path") or "/").partition("?")
    used = set(URL_VAR.findall(template)) | set(URL_VAR.findall(query))
    # Secrets first, URL-encoded; then the caller's arguments, URL-encoded, so neither can form a reference.
    path = URL_VAR.sub(
        lambda m: quote(str(args.get(m.group(1), "")), safe=""), SECRET_REF.sub(lambda m: secret(m, True), template)
    )
    url = module["endpoint"].rstrip("/") + path
    # One pass over each query value, so an argument's value is never read again as a reference: `{name}` takes the
    # argument (left out when it is not given and is the whole value), `{{NAME}}` the secret.
    fixed: dict[str, str] = {}
    for k, v in parse_qsl(query, keep_blank_values=True):
        whole = URL_VAR.fullmatch(v)
        if whole and args.get(whole.group(1)) is None:
            continue
        fixed[k] = QUERY_REF.sub(lambda m: secret(m, False) if m.group(1) else argument(m.group(2)), v)
    rest = {k: v for k, v in args.items() if k not in used}
    method = op.get("method") or "GET"
    body: Any = None
    params: dict[str, Any] = dict(fixed)
    form: dict[str, str] | None = None
    content: str | None = None
    encoding = op.get("body_encoding") or "json"
    if op.get("body") and encoding == "form":
        form = form_fields(cast(dict[str, str], json.loads(op["body"])), args)
    elif op.get("body") and encoding == "raw":
        content = BODY_VAR.sub(lambda m: _as_text(args.get(m.group(1))), op["body"])
    elif op.get("body"):
        body = json.loads(BODY_VAR.sub(lambda m: json.dumps(args.get(m.group(1))), op["body"]))
    elif method in ("GET", "DELETE"):
        # The operation's own query wins over an argument of the same name: a caller cannot replace a credential.
        params = {**rest, **fixed}
    else:
        body = rest
    pairs: list[dict[str, str]] = op.get("headers") or []
    headers = {h["key"]: SECRET_REF.sub(lambda m: secret(m, False), h["value"]) for h in pairs}
    return HttpRequest(method, url, params, body, headers, form, content)


def _sent_headers(req: HttpRequest, prepared: Prepared | None) -> dict[str, str]:
    """The headers as the request left: the operation's and the connection's, and the Content-Type its body encoding
    set (httpx adds it on the wire), so what a person reads is what the system got."""
    headers = _with_auth(req, prepared)[1]
    encoded = (
        "application/x-www-form-urlencoded"
        if req.form is not None
        else "application/json"
        if req.json_body is not None
        else None
    )
    if encoded and not any(k.lower() == "content-type" for k in headers):
        return {**headers, "Content-Type": encoded}
    return headers


def _as_text(value: Any) -> str:
    """An argument inside a form field or a raw body: text as it is, anything else as JSON, nothing as empty."""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def form_fields(templates: dict[str, str], args: dict[str, Any]) -> dict[str, str]:
    """A form body: each field's `{{arg}}` the argument as text (an object or a list as JSON), a field whose whole
    value is an argument not given left out. httpx encodes every value, so an argument cannot add a field."""

    out: dict[str, str] = {}
    for name, template in templates.items():
        whole = BODY_VAR.fullmatch(template.strip())
        if whole and args.get(whole.group(1)) is None:
            continue
        out[name] = BODY_VAR.sub(lambda m: _as_text(args.get(m.group(1))), template)
    return out


# A call to a module whose account names no address: nothing is sent.
NO_ADDRESS = "This tool's app names no address; set it on the app's account."


class _Secrets:
    """Shared by both executors: resolves the `{{NAME}}` references an operation names at call time, or fails the call
    naming the secret (never its value), and signs the call in through the module's connection."""

    secrets: SecretResolver | None
    auth: Authenticator | None

    async def _signed_in(
        self,
        module: dict[str, Any],
        op: dict[str, Any],
        environment: str,
        actor: str,
        *,
        trial: Trial | None = None,
        stale_rotation: int | None = None,
        acting_for: ActingForPerson | None = None,
    ) -> Prepared | None:
        if self.auth is None:
            return None
        try:
            prepared = await self.auth.prepare(
                module,
                environment,
                tool=str(op["name"]),
                actor=actor,
                stale_rotation=stale_rotation,
                acting_for=acting_for,
                needs_person=bool(op.get("needs_person")),
                scopes=scope_list(op.get("scopes")),
            )
        except AuthFailed as e:
            with_access(e, op, module)
            raise
        if prepared is not None and trial is not None:
            trial.note(f"Signed in through the account {prepared.connection_id}")
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
                module["tenant_id"], module.get("team_id"), rest, tool=op["name"], actor=actor
            )
            return {**looked, **typed}
        except SecretMissing as e:
            return _failure("SECRET_MISSING", f"The secret {', '.join(e.names)} is not set for this module's team.")


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
        environment: str = "test",
        acting_for: ActingForPerson | None = None,
        on_answer: Callable[[Any, Mapping[str, str]], Any] | None = None,
    ) -> ToolOutcome:
        """With `trial` (the test console) the operation's own transform is not applied: the console applies its draft
        to `trial.raw`. `secret_values` are a test's typed values (_Secrets._resolve). `environment` is the run's (test
        or production): a live run is never signed in with a sandbox account. `on_answer` sees the answer and its
        headers before the transform, as a plugin's paging reads the next page from them (plugins/executor.py)."""
        if not module.get("endpoint"):
            return _failure("CONNECTION_NOT_SET", NO_ADDRESS)
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
            prepared = await self._signed_in(module, op, environment, actor, trial=trial, acting_for=acting_for)
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
                    "headers": [{"key": k, "value": v} for k, v in _sent_headers(req, prepared).items()],
                    **({"body": json.dumps(req.json_body)} if req.json_body is not None else {}),
                    **({"body": urlencode(req.form)} if req.form is not None else {}),
                    **({"body": req.content} if req.content is not None else {}),
                },
                used,
            )
        # The operation's own timeout when it has one, else the module's.
        limit_ms: int = op.get("timeout_ms") or module["timeout_ms"]
        try:
            # The app's own hosts (its module's) pass for its own calls, as the plugin host renders them for a plugin.
            await self.policy.check_url(module["tenant_id"], req.url, module["egress_hosts"])
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
                    prepared = await self._signed_in(
                        module, op, environment, actor, stale_rotation=prepared.rotation, acting_for=acting_for
                    )
                except AuthFailed as e:
                    return auth_failure(e)
                used = sorted({*used, *_scrub_set(resolved, prepared)})
                if trial is not None:
                    trial.used = used
                res = await self._send(module, req, prepared, limit_ms)
            if (
                res.status_code == 401
                and prepared is not None
                and prepared.person is not None
                and not prepared.renewable
                and self.auth is not None
                and acting_for is not None
            ):
                # A person's own key the system refused: theirs alone is marked, and the card asks for it again.
                refused = await self.auth.refused(module, prepared, acting_for, f"{host} answered 401.")
                return auth_failure(with_access(refused, op, module))
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
        # A system that reports failure inside a 200 (Slack's `ok: false`) fails the call in its own words.
        refused = answer_error(output, op.get("error_when"))
        if refused is not None:
            if trial is not None:
                trial.raw = output
            if isinstance(refused, NeedsReconnect):
                return _failure("AUTH_EXPIRED", str(refused), 401, UPSTREAM)
            return _failure(refused.code, str(refused), res.status_code, UPSTREAM)
        if on_answer is not None:
            try:
                output = on_answer(output, dict(res.headers))
            except Exception as e:  # the caller's reading of the answer: the call fails, the gateway does not
                return _failure("ANSWER_UNREADABLE", f"The answer from {host} could not be read ({type(e).__name__}).")
        if trial is not None:
            trial.raw = output
            # A plugin tool's transform reads the team's settings, which only the gateway holds, and its page has no
            # draft to try; so the gateway shapes its answer here, once, as for an agent's call.
            if plugin_id_of(module) is None:
                return ToolOutcome(True, output)
        if op.get("response_transform"):
            # A plugin's transform also reads the team's merged settings; every other module's sees none.
            shaped, failed = await transform.apply(op["response_transform"], output, module.get("plugin_settings"))
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
            json=req.json_body if req.form is None and req.content is None else None,
            data=req.form,
            content=req.content,
            headers=headers,
            timeout=limit_ms / 1000,
            extensions=for_tenant(
                module["tenant_id"], prepared.certificate if prepared else None, module["egress_hosts"]
            ),
        )


class McpExecutor(_Secrets):
    """Calls an imported MCP tool by its server name (the operation's `path`) through tools/call, on the egress
    policy's client like every other outbound request. A module with a connection signs in through it as an http one
    does; the token goes only to the module's endpoint, the server it was issued for."""

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
            hosts=module["egress_hosts"],
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
        environment: str = "test",
    ) -> ToolOutcome:
        if not module.get("endpoint"):
            return _failure("CONNECTION_NOT_SET", NO_ADDRESS)
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
            await self.policy.check_url(module["tenant_id"], url, module["egress_hosts"])
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
        code: CodeExecutor | None = None,
        *,
        plugins: PluginExecutor | None = None,
    ) -> None:
        """`mocks` answers a test call from the operation's mock answers; without it none is read. `code` runs
        a code operation's function on runner-service; without it a code operation fails."""
        self.local = local
        self.http = http
        self.mcp = mcp_executor or McpExecutor(http.client, http.policy, http.secrets, http.auth)
        self.mocks = mocks
        self.code = code
        # A plugin's Python tools; without it they fail.
        self.plugins = plugins

    async def _mocked(self, module: dict[str, Any], op: dict[str, Any], mock: dict[str, Any]) -> ToolOutcome:
        """A test call answered as the system would have, before any egress: the same failures a real answer
        or a real timeout gives, so a workflow's ports behave as they would against the system."""
        assert self.mocks is not None
        limit_ms: int = op.get("timeout_ms") or module["timeout_ms"]
        host = urlsplit(str(module.get("endpoint") or "")).hostname
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
        trial: Trial | None = None,
        secret_values: dict[str, str] | None = None,
    ) -> ToolOutcome:
        """`caller` is the verified caller the gateway decided for: every executor path acts for it alone.
        `environment` is the run's (test or production; test when None), which picks mock answers and the code runner's
        mode. The account a call signs in with is the module's `connection_id`, chosen where the registry resolved it.
        A tool page's Real run passes `trial` and its typed `secret_values` through to the http and MCP executors,
        which fill the request it shows."""
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
        if resolved.executor == "code":
            if self.code is None:
                return _failure("runner_unavailable", "This gateway has no code runner.")
            return await self.code.run(
                op, args, key=key, caller=caller, environment=environment, module_team=module.get("team_id")
            )
        # A plugin's address is rendered from its manifest by the plugin host (instance plus API path); the connection
        # holds only the instance's origin, so only every other module takes its connection's address.
        signs_in = environment or TEST
        if resolved.executor in ("http", "mcp") and self.http.auth is not None and plugin_id_of(module) is None:
            # A module's address is its account's, its only home.
            module = await self.http.auth.addressed(module)
        if self.mocks is not None and (
            mock := await self.mocks.for_call(caller.tenant_id, str(module["id"]), op["name"], args, environment)
        ):
            return await self._mocked(module, op, mock)
        if resolved.executor == "mcp":
            return await self.mcp.run(
                module, op, args, actor=actor, environment=signs_in, trial=trial, secret_values=secret_values
            )
        if resolved.executor == "plugin":
            if self.plugins is None:
                return _failure("PLUGIN_DISABLED", "This gateway runs no plugins.")
            # A knowledge source's own addresses (a crawled site) are reachable only on a sync's calls: the service
            # syncing sources holds knowledge:run, and no agent or person does.
            syncing = caller.kind == "service" and SOURCE_SYNC_SCOPE in caller.scopes
            return await self.plugins.run(
                module,
                op,
                args,
                actor=actor,
                environment=signs_in,
                acting_for=caller.acting_for,
                trial=trial,
                source_hosts=syncing,
            )
        return await self.http.run(
            module,
            op,
            args,
            actor=actor,
            environment=signs_in,
            acting_for=caller.acting_for,
            trial=trial,
            secret_values=secret_values,
        )
