"""Code operations (c-531): a builder's Python function, run on runner-service, that reaches other systems only through
the tools it is bound to.

The gateway decides a call to a code operation like any other, then this executor sends the function, the call's input
and a call token to the runner. The token is this service's own (HMAC, purpose `code-run`) and names the caller, the
tools the function may call and the secrets it may hand them, so the runner holds no grant: each `ops.call` comes back
to `POST /v1/code-runs/calls`, where the token is checked and the call is decided again as the caller's own gateway
call, with its own call row.

A secret reaches a call only as a handle, `{"$secret": NAME}`, replaced here by its value when NAME is one the operation
binds, the call is a read over http, and the argument becomes a query value; the value never enters the sandbox, and it
is scrubbed from the answer the function receives."""

from __future__ import annotations

import json
from typing import Any, cast

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import Principal, ServiceCallError, ServiceClient, ServiceUnreachable
from ops_policy import HmacSigner, TokenError, mint, verify
from ops_service_kit.errors import Unauthorized, Unprocessable

from .executor import URL_VAR
from .registry import Resolved
from .secrets import SecretMissing, SecretResolver
from .tools import ToolCaller

PURPOSE = "code-run"
# How long past the function's own time limit its calls are still accepted.
TOKEN_GRACE_S = 30
SECRET = "$secret"


def failed(code: str, message: str, **more: Any) -> ToolOutcome:
    return ToolOutcome(False, {"error": {"code": code, "message": message}, **more})


def code_signer(secrets_key: str) -> HmacSigner:
    return HmacSigner.derived(secrets_key, PURPOSE)


class CodeExecutor:
    """Runs a code operation on runner-service. Without a runner every code operation fails `runner_unavailable`."""

    def __init__(self, runner: ServiceClient | None, signer: HmacSigner) -> None:
        self.runner = runner
        self.signer = signer

    def token(self, op: dict[str, Any], code: dict[str, Any], caller: ToolCaller, key: str, env: str | None) -> str:
        limits = cast(dict[str, Any], code.get("limits") or {})
        claims = {
            "purpose": PURPOSE,
            "tenant_id": caller.tenant_id,
            "team_id": caller.team_id,
            "sub": caller.sub,
            "kind": caller.kind,
            "operation": op["name"],
            "access": op["access"],
            "bindings": list(code.get("bindings") or []),
            "secrets": list(code.get("secrets") or []),
            "key": key,
            "environment": env,
        }
        return mint(claims, self.signer, ttl_s=int(float(limits.get("timeS", 10)) + TOKEN_GRACE_S))

    async def run(
        self,
        op: dict[str, Any],
        args: dict[str, Any],
        *,
        key: str,
        caller: ToolCaller,
        environment: str | None,
    ) -> ToolOutcome:
        code = cast(dict[str, Any] | None, op.get("code"))
        if not code or not code.get("source"):
            return failed("code_missing", f"{op['name']} has no function to run.")
        if self.runner is None:
            return failed("runner_unavailable", "This gateway has no code runner.")
        body = {
            "source": code["source"],
            "entry": code.get("entry") or "main",
            "input": args,
            "limits": code.get("limits") or {},
            "callToken": self.token(op, code, caller, key, environment),
        }
        try:
            result = cast(
                dict[str, Any],
                await self.runner.post(
                    "/v1/runs", json=body, tenant=caller.tenant_id, team=caller.team_id, timeout=_timeout(code)
                ),
            )
        except ServiceUnreachable:
            return failed("runner_unavailable", "The code runner did not answer.")
        except ServiceCallError as e:
            return failed("runner_error", e.message)
        run = {k: result.get(k) for k in ("log", "calls", "createMs", "executeMs", "trace")}
        if result.get("ok"):
            return ToolOutcome(True, result.get("output"), view={"run": run})
        error = cast(dict[str, Any], result.get("error") or {})
        return failed(str(error.get("code") or "runner_error"), str(error.get("message") or ""), run=run)


def _timeout(code: dict[str, Any]) -> float:
    limits = cast(dict[str, Any], code.get("limits") or {})
    return float(limits.get("timeS", 10)) + 15.0


def run_claims(token: str | None, signer: HmacSigner) -> dict[str, Any]:
    """The claims of a call token this service minted for a run still in time; refused otherwise."""
    if not token:
        raise Unauthorized("A code run's call needs its call token.", code="code_run_token")
    try:
        claims = verify(token, signer)
    except TokenError as e:
        raise Unauthorized("This code run's call token is not valid or has expired.", code="code_run_token") from e
    if claims.get("purpose") != PURPOSE:
        raise Unauthorized("This is not a code run's call token.", code="code_run_token")
    return claims


def run_caller(claims: dict[str, Any]) -> Principal:
    """The caller the run acts for, as the gateway decides each of its calls."""
    team = cast(str | None, claims.get("team_id"))
    kind = str(claims.get("kind"))
    return Principal(
        kind=kind if kind in ("person", "api_key", "service") else "service",  # pyright: ignore[reportArgumentType]
        sub=str(claims["sub"]),
        email="",
        name=str(claims["sub"]),
        tenant_id=str(claims["tenant_id"]),
        team_id=team,
        team_ids=[team] if team else [],
        roles={},
        scopes=[],
        auth_method="service" if kind == "service" else "session",
    )


def handles_in(args: dict[str, Any]) -> dict[str, str]:
    """Each top-level argument passed as a secret handle, argument name to secret name. A handle nested deeper is not
    placed anywhere, so it is refused."""
    found: dict[str, str] = {}
    for name, value in args.items():
        item: Any = value
        if isinstance(item, dict) and SECRET in item:
            found[name] = str(cast(dict[str, Any], item)[SECRET])
        elif SECRET in json.dumps(item):
            raise Unprocessable("A secret handle is passed only as a whole argument.", code="secret_placement")
    return found


async def resolve_handles(
    claims: dict[str, Any],
    resolved: Resolved | None,
    args: dict[str, Any],
    secrets: SecretResolver | None,
) -> tuple[dict[str, Any], list[str]]:
    """`args` with each handle replaced by its secret's value, and the values to scrub from the answer. A handle is
    refused unless the operation binds the secret, the tool is a read over http, and the argument becomes a query
    value (not in the path, with no body template). A read function may not call a write: the gateway decided its own
    call as a read, so a write it made would skip the write's approval; a function that writes is marked write."""
    if claims.get("access") == "read" and resolved is not None and resolved.access == "write":
        target = resolved.operation["name"] if resolved.operation else "a write"
        raise Unprocessable(f"{claims['operation']} is a read, so it may not call {target}.", code="write_from_read")
    handles = handles_in(args)
    if not handles:
        return args, []
    unbound = sorted(set(handles.values()) - set(claims.get("secrets") or []))
    if unbound:
        raise Unprocessable(f"This function may not use the secret {', '.join(unbound)}.", code="secret_not_bound")
    op = resolved.operation if resolved else None
    if op is None or resolved is None or resolved.executor != "http" or resolved.access != "read":
        raise Unprocessable("A secret is handed only to a read over http.", code="secret_placement")
    in_path = set(URL_VAR.findall(str(op.get("path") or "").partition("?")[0]))
    if op.get("body") or (op.get("method") or "GET") not in ("GET", "DELETE") or in_path & set(handles):
        raise Unprocessable("A secret is handed to a call only as a query value.", code="secret_placement")
    if secrets is None:
        raise Unprocessable("This gateway has no secrets store.", code="secret_unavailable")
    try:
        values = await secrets.lookup(
            str(claims["tenant_id"]),
            cast(str | None, claims.get("team_id")),
            sorted(set(handles.values())),
            tool=str(claims["operation"]),
            actor=str(claims["sub"]),
        )
    except SecretMissing as e:
        raise Unprocessable(f"The secret {', '.join(e.names)} is not set for this team.", code="secret_missing") from e
    filled = {**args, **{arg: values[name] for arg, name in handles.items()}}
    return filled, list(values.values())
