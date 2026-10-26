"""POST /v1/calls: hash the input, ask OPA, log the decision, and run the tool only when OPA allows it."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager, nullcontext
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ops_access import can
from ops_identity import Auth, CurrentService, Principal, install_auth
from ops_policy import input_hash
from ops_service_kit.background import BackgroundHealthOut
from ops_service_kit.errors import Forbidden, NotFound, ServiceUnavailable, Unprocessable
from ops_service_kit.http import Envelope, Out, error_body, error_responses, install_error_handlers, operation_id
from ops_service_kit.logging import quiet_request_logs
from ops_service_kit.settings import Settings
from ops_store.background import LOCAL as LOCAL_BEATS
from ops_store.background import report as background_report

from .auth import Authenticator
from .code_runs import CodeExecutor, resolve_handles, run_caller, run_claims
from .egress import EgressPolicy, egress_client
from .executor import Executor, HttpExecutor
from .gateway_calls import API, WRITES, CallRequest, GatewayCalls, Outcome, Refused
from .mcp_server import McpAdapter
from .mocks import MockAnswers
from .modules.directory import Directory
from .modules.policy import WriteApprovals
from .opa import POLICY_FILE, OpaClient, PolicyMismatchError, policy_hash
from .registry import Resolved, ToolRegistry
from .secrets import SecretMissing, SecretOutOfScope, SecretResolver
from .send_check import SendCheck
from .store import CallLog
from .store.mocks import MockStore
from .store.modules import Aggregate
from .store.rate_windows import RateWindows
from .tools import ToolRunner


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunContext(_Wire):
    """Where the call comes from. Who calls is not here: it is the verified service token's subject (I13)."""

    thread: str | None = None
    step: str | None = None
    act: str | None = None
    # Which of a connection's environments the call uses (c-330): live runs send production, everything else test.
    # Absent is test, so a caller that does not say never reaches a production credential.
    environment: Literal["test", "production"] | None = None


class FenceIn(_Wire):
    thread: str
    generation: int = Field(ge=1)


class AbandonIn(_Wire):
    key: str = Field(min_length=1, max_length=200)
    tool: str = Field(min_length=1, max_length=64)
    thread: str | None = None


class AbandonedCall(Out):
    id: str
    # ok, error, refused, running, replayed, in_progress or lost, as the log has it.
    outcome: str
    # The row carrying the write's side effect (its claim), as opposed to a refusal or a replay.
    effect: bool
    decision: str
    output: Any = None
    error: dict[str, Any] | None = None


class AbandonResult(Out):
    # True when the gateway had no call under the key and now refuses one; otherwise `call` is the one it has.
    abandoned: bool
    call: AbandonedCall | None


class CallIn(_Wire):
    tool: str
    input: dict[str, Any]
    key: str
    run_context: RunContext = Field(alias="runContext")
    approval_token: str | None = Field(default=None, alias="approvalToken")


class CodeCallIn(_Wire):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict[str, Any])


class GrantableOperation(Out):
    """A tool an agent may be granted: a published operation, with what a model needs to choose and call it."""

    name: str
    description: str
    access: str
    input_schema: dict[str, Any]
    requires_approval: bool
    approvers: int
    # Approving asks for a step-up: set on the operation, or two approvers.
    step_up: bool = False
    # The declared result shape (x-ops-shape), which agents-service's shaper prefers when the data fits it.
    output_shape: str | None = None
    module_id: str | None
    module_name: str


class SecretValuesIn(_Wire):
    names: list[str] = Field(min_length=1, max_length=50)


class SecretValues(Out):
    values: dict[str, str]


class CallResult(Out):
    call_id: str
    decision: str
    ok: bool
    output: Any
    view: Any = None
    replay_of: str | None = None


def as_response(outcome: Outcome) -> JSONResponse:
    """POST /v1/calls' wire form of a call's outcome."""
    if isinstance(outcome, Refused):
        body = error_body(outcome.status, outcome.code, "; ".join(outcome.reasons))
        body["error"]["details"] = {"callId": outcome.call_id, "reasons": outcome.reasons, **outcome.details}
        return JSONResponse(body, status_code=outcome.status)

    data: dict[str, Any] = {
        "callId": outcome.call_id,
        "decision": "allow",
        "ok": outcome.ok,
        "output": outcome.output,
        "view": outcome.view,
    }
    if outcome.replay_of:
        data["replayOf"] = outcome.replay_of
    return JSONResponse({"success": True, "data": data})


def create_gateway_app(
    *,
    opa: OpaClient,
    registry: ToolRegistry,
    log: CallLog,
    runner: ToolRunner,
    review_key: str,
    auth: Auth | None = None,
    rates: RateWindows | None = None,
    clock: Callable[[], float] = time.time,
    policy: str | None = None,
    routers: tuple[APIRouter, ...] = (),
    http_client: httpx.AsyncClient | None = None,
    egress: EgressPolicy | None = None,
    secret_resolver: SecretResolver | None = None,
    cors_origins: tuple[str, ...] = (),
    background: tuple[Callable[[], Coroutine[Any, Any, None]], ...] = (),
    write_approvals: WriteApprovals | None = None,
    send_check: SendCheck | None = None,
    authenticator: Authenticator | None = None,
    directory: Directory | None = None,
    code: CodeExecutor | None = None,
) -> FastAPI:
    """`clock` is the time a token's expiry is judged by, sent to OPA with each call; tests pass a fixed one.
    `policy` is the Rego the gateway decides by, `policy/gateway.rego` unless given; it is written into OPA at start
    and checked there on every health probe. `routers` mounts the registry's routes (`ops_tools.modules`).
    `egress` is the policy every outbound request follows; without it no http operation runs. `http_client` is what
    those requests go through: by default the policy's own client, in tests one bound to a fake API.
    `secret_resolver` resolves `{{NAME}}` header references at call time; without it an operation needing a secret
    is refused. `cors_origins` are the browser origins (the console) allowed to call these routes. `auth` resolves
    callers (ops_identity's shared dependency); by default it is built from Settings for audience "tools". `background`
    runs beside the server from start-up and is cancelled at shutdown (the copy of reviews into Reviews, c-163).
    `write_approvals` reads each team's toolWritesNeedApproval live; without it each write follows its registry flag.
    `authenticator` signs a module's calls in through its connection (c-330); without it a connection adds nothing.
    `directory` holds the teams the MCP adapter scopes each assistant's tools to (c-356); without it no /mcp.
    `code` runs code operations on runner-service and checks their calls back (c-531); without it they fail."""
    # Resolved secrets go into the URLs this gateway requests, and httpx logs each URL at INFO; the gateway turns those
    # lines off whether or not its process called configure_logging.
    quiet_request_logs()
    rules = policy if policy is not None else POLICY_FILE.read_text()
    client = http_client or (egress_client(egress) if egress else httpx.AsyncClient())
    executor = Executor(
        runner,
        HttpExecutor(client, egress, secret_resolver, authenticator),
        mocks=MockAnswers(MockStore(log.engine)),
        code=code,
    )
    expected = policy_hash(rules)
    counters = rates or RateWindows(log.engine)

    async def all_writes_wait(tenant_id: str, team_id: str | None) -> bool:
        return write_approvals is not None and await write_approvals.all_writes(tenant_id, team_id)

    calls = GatewayCalls(
        registry=registry,
        log=log,
        opa=opa,
        executor=executor,
        counters=counters,
        send_check=send_check,
        all_writes_wait=all_writes_wait,
        clock=clock,
    )

    resolved_auth = auth or Auth.from_settings(Settings(), audience="tools")
    mcp = (
        McpAdapter(calls=calls, registry=registry, directory=directory, auth=resolved_auth)
        if directory is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        await opa.load_review_key(review_key)
        await opa.load_policy(rules)
        if await opa.loaded_policy_hash() != expected:
            raise PolicyMismatchError("OPA does not hold this gateway's policy after loading it; refusing to start.")
        tasks = [asyncio.create_task(job()) for job in background]
        try:
            async with mcp.running() if mcp is not None else nullcontext():
                yield
        finally:
            for t in tasks:
                t.cancel()

    app = FastAPI(title="Ops AI tool gateway", lifespan=lifespan, generate_unique_id_function=operation_id)
    install_error_handlers(app)
    install_auth(app, resolved_auth)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Accept", "Authorization", "X-API-Key", "X-Team-Id"],
            max_age=600,
        )
    for router in routers:
        app.include_router(router)
    if mcp is not None:
        # A raw ASGI mount: the SDK writes its own responses, and MCP is not part of the REST OpenAPI.
        app.mount("/mcp", mcp)

    @app.get("/health", response_model=None, tags=["gateway"])
    async def health() -> dict[str, str] | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # Another process writing a different policy into a shared OPA would change every decision; say so.
        if await opa.loaded_policy_hash() != expected:
            return JSONResponse({"status": "policy_drift"}, status_code=503)
        return {"status": "ok"}

    @app.get("/health/background", tags=["health"], response_model=BackgroundHealthOut)
    async def health_background() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """This service's background processes and their state; counts and error types only, no record's data."""
        return {"processes": background_report(await LOCAL_BEATS.read(), "tools", time.time())}

    @app.post(
        "/v1/secrets/values", tags=["secrets"], response_model=Envelope[SecretValues], responses=error_responses()
    )
    async def secret_values(body: SecretValuesIn, caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token holding `secrets_egress:run`, c-221): the values of the tenant's workspace-wide
        secrets, for a service that keeps no credential of its own (models-service's provider keys). A secret scoped to
        teams never leaves for another service, and every value read is audited as the calling service."""
        can(caller, "secrets_egress", "run", what="secret values")
        if secret_resolver is None:
            raise ServiceUnavailable("This gateway reads no secrets.")
        try:
            found = await secret_resolver.lookup(
                caller.tenant_id, list(dict.fromkeys(body.names)), tool="secrets.values", actor=caller.sub, team=None
            )
        except SecretOutOfScope as e:
            raise Forbidden(
                f"Only workspace-wide secrets are read by services; {', '.join(e.names)} belongs to teams.",
                code="secret_out_of_scope",
            ) from e
        except SecretMissing as e:
            raise NotFound(f"Secret {', '.join(e.names)}") from e
        return JSONResponse({"success": True, "data": {"values": found}})

    def team_view(caller: Principal) -> Callable[[Aggregate], bool] | None:
        """The modules a run of the caller's team may reach (c-433): its own, workspace-level ones, and those approved
        for one of its workflows, a grant that covers the team's agents too. None for a token naming no team, which
        acts for the whole tenant."""
        if not caller.team_id:
            return None
        team = (directory or Directory(teams=())).team(caller.team_id)
        return lambda m: (directory or Directory(teams=())).sees_module(team, m)

    @app.get(
        "/v1/grantable-operations",
        tags=["gateway"],
        response_model=Envelope[list[GrantableOperation]],
        responses=error_responses(),
    )
    async def grantable_operations(caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The operations an agent of the caller's tenant may be granted, for a service holding `tools:view` (c-168).
        agents-service lists, grants and hands a run its tools from here; it keeps no catalogue of its own."""
        can(caller, "tools", "view", what="the grantable operations")
        rows = await registry.grantable(caller.tenant_id, team_view(caller))
        if await all_writes_wait(caller.tenant_id, caller.team_id):
            # The caller's team has every write wait, so the agents that list these pause before each one.
            rows = [r | {"requires_approval": True} if r["access"] in WRITES else r for r in rows]
        data = [GrantableOperation.model_validate(r).model_dump(by_alias=True) for r in rows]
        return JSONResponse({"success": True, "data": data})

    @app.get("/v1/tools/{name}", tags=["gateway"], responses=error_responses())
    async def tool_access(name: str, caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token): a tool's access class from the gateway's registry, the one the policy decides
        on. The review service asks here how many approvers a call needs instead of reading the registry itself."""
        access, policy, output = await registry.described(name, caller.tenant_id, caller.team_id)
        if access == "unknown":
            return as_response(Refused("", 404, "not_found", [f"tool {name} is not registered with the gateway"]))
        approval = (
            {
                "approvers": policy["approvers"],
                "approverTeam": policy["approver_team"],
                "stepUp": policy["step_up"],
            }
            if policy
            else {"approvers": 1, "approverTeam": None, "stepUp": False}
        )
        # `output`: what the operation answers (c-353), a step's output fields before it runs; null when unknown.
        data = {"name": name, "access": access, "approval": approval, "outputSchema": output}
        return JSONResponse({"success": True, "data": data})

    @app.post("/v1/fences", tags=["gateway"])
    async def raise_fence(body: FenceIn, _: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token): agents-service calls it when it takes a thread over, so the new generation is
        the fence before any write of the new owner, and a stalled old owner cannot write in between. Idempotent;
        a lower generation than the fence is refused."""
        current = await log.raise_fence(body.thread, body.generation)
        if current > body.generation:
            return as_response(Refused("", 409, "lease_superseded", [f"fence is at generation {current}"]))
        return JSONResponse({"success": True, "data": {"thread": body.thread, "generation": current}})

    @app.post(
        "/v1/calls/abandon", tags=["gateway"], response_model=Envelope[AbandonResult], responses=error_responses()
    )
    async def abandon(body: AbandonIn, caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token), for a workflow that lost the answer to a write: the call the gateway has under
        `key` (a claim still running past its expiry reads as lost), or, when it has none, the key abandoned so the
        call is refused if it arrives later (it was still in flight). One transaction under the key's lock, so a call
        and its abandon never both win. Idempotent."""
        tenant = caller.tenant_id
        await log.expire_running(tenant_id=tenant, key=body.key)
        found = await log.abandon(tenant_id=tenant, key=body.key, tool=body.tool, thread_id=body.thread, sub=caller.sub)
        call = (
            {
                "id": found["id"],
                "outcome": found["outcome"],
                "effect": bool(found["effect"]),
                "decision": found["decision"],
                "output": found["output"],
                "error": found["error"],
            }
            if found
            else None
        )
        return JSONResponse({"success": True, "data": {"abandoned": found is None, "call": call}})

    @app.post("/v1/calls", tags=["gateway"], response_model=Envelope[CallResult], responses=error_responses())
    async def call(  # pyright: ignore[reportUnusedFunction]
        body: CallIn, caller: CurrentService, x_lease_generation: Annotated[int | None, Header()] = None
    ) -> JSONResponse:
        request = CallRequest(
            tool=body.tool,
            input=body.input,
            key=body.key,
            run_context=body.run_context.model_dump(),
            approval_token=body.approval_token,
        )
        found = await calls.call(caller, request, generation=x_lease_generation, channel=API, sees=team_view(caller))
        return as_response(found)

    @app.post("/v1/code-runs/calls", tags=["gateway"], response_model=Envelope[CallResult], responses=error_responses())
    async def code_run_call(  # pyright: ignore[reportUnusedFunction]
        body: CodeCallIn, caller: CurrentService, x_code_run: Annotated[str | None, Header()] = None
    ) -> JSONResponse:
        """Internal: one `ops.call` from a running code operation (c-531), sent by runner-service with the run's call
        token. Only a tool the operation binds is called, decided as the run's caller's own gateway call."""
        can(caller, "tools", "run", what="a code run's calls")
        if code is None:
            raise Unprocessable("This gateway runs no code.", code="runner_unavailable")
        claims = run_claims(x_code_run, code.signer)
        if body.tool not in claims.get("bindings", []):
            message = f"{body.tool} is not one of the tools this function may call."
            raise Unprocessable(message, code="binding_forbidden")
        principal = run_caller(claims)
        request = CallRequest(
            tool=body.tool,
            input=body.input,
            # The same call with the same input in one run is the same call: a write is claimed once.
            key=f"{claims['key']}:{body.tool}:{input_hash(body.input)[:16]}",
            run_context={"act": f"code:{claims['operation']}", "environment": claims.get("environment")},
        )

        async def prepare(resolved: Resolved | None, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
            return await resolve_handles(claims, resolved, args, secret_resolver)

        found = await calls.call(
            principal,
            request,
            channel=API,
            prepare=prepare,
            sees=team_view(principal),
        )
        return as_response(found)

    return app
