"""POST /v1/calls: hash the input, ask OPA, log the decision, and run the tool only when OPA allows it."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager, nullcontext
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import Receive, Scope, Send

from ops_access import Access, can
from ops_identity import Auth, CurrentService, Principal, install_auth
from ops_policy import input_hash
from ops_service_kit.background import BackgroundHealthOut
from ops_service_kit.errors import Unprocessable
from ops_service_kit.flags import Flags
from ops_service_kit.http import Envelope, Out, error_body, error_responses, install_error_handlers, operation_id
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.background import LOCAL as LOCAL_BEATS
from ops_store.background import report as background_report

from .auth import Authenticator
from .code_runs import CodeExecutor, resolve_handles, run_acting_for, run_caller, run_claims
from .egress import EgressPolicy, egress_client
from .environments import RunKind
from .executor import Executor, HttpExecutor
from .gateway_calls import API, WRITES, CallRequest, GatewayCalls, Outcome, Refused
from .held_hosts import install_held_hosts
from .mcp_server import McpAdapter
from .mocks import MockAnswers
from .modules.directory import Directory
from .modules.policy import RequesterMayDecide, WriteApprovals, approves_own_writes
from .modules.service import ModuleService
from .opa import POLICY_FILE, OpaClient, PolicyMismatchError, policy_hash, registered_identities
from .plugins.executor import PluginExecutor
from .plugins.host import PluginHost
from .registry import Resolved, ToolRegistry
from .secrets import SecretResolver
from .send_check import SendCheck
from .store import CallLog
from .store.connections import ConnectionStore, plugin_app
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
    # The kind of run the call is made in: live runs send production, everything else test. Absent is test,
    # so a caller that does not say never reaches a live account's write unseen.
    environment: RunKind | None = None
    # The account each app's calls use, app id to account name, as a step, an agent or a chat chose; an app with no
    # entry uses the person's default, else the team's. The call reads its own app's entry.
    accounts: dict[str, Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, max_length=50)
    # Deprecated: one account name for the call's app, as older callers send it; read for one release, `accounts`
    # wins.
    account: str | None = Field(default=None, min_length=1, max_length=200)


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
    # What people see in place of the name (a plugin tool's manifest title); none for a tool without one.
    title: str | None = None
    description: str
    access: str
    input_schema: dict[str, Any]
    requires_approval: bool
    # Who answers a call that waits, from the one resolver (`effective_answer`): "none", "person" (the asker confirms)
    # or "reviewer" (someone else with `reviewer_role`), and the level it came from.
    answer: str = "none"
    reviewer_role: str | None = None
    source: str = "team"
    approvers: int
    # Approving asks for a step-up: set on the operation, or two approvers.
    step_up: bool = False
    # The declared result shape (x-ops-shape), which agents-service's shaper prefers when the data fits it.
    output_shape: str | None = None
    module_id: str | None
    module_name: str
    # The caller's team has a test account of the app: a test run's write signs in there and changes nothing real, so
    # it never asks (gateway_calls holds no write on a test account either).
    test_account: bool = False
    # False for a tool the team turned off in its app's catalog: listed so a run can call it and be refused with the
    # fix (Turn on <tool>, or Ask an admin), never offered to agents to pick.
    added: bool = True


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


MCP_OFF = "The MCP address is off for this install. Add mcp_gateway to OPS_FLAGS in the install config to turn it on."


async def _mcp_off(scope: Scope, receive: Receive, send: Send) -> None:
    """Every /mcp request while the mcp_gateway flag is off: a 404 that says why, not a bare not-found."""
    if scope["type"] == "http":
        await JSONResponse(error_body(404, "feature_off", MCP_OFF), status_code=404)(scope, receive, send)


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
    requester_policy: RequesterMayDecide | None = None,
    send_check: SendCheck | None = None,
    authenticator: Authenticator | None = None,
    directory: Directory | None = None,
    code: CodeExecutor | None = None,
    plugins: PluginHost | None = None,
    cursor_key: bytes = b"",
    flags: Flags | None = None,
    modules: ModuleService | None = None,
) -> FastAPI:
    """`clock` is the time a token's expiry is judged by, sent to OPA with each call; tests pass a fixed one.
    `policy` is the Rego the gateway decides by, `policy/gateway.rego` unless given; it is written into OPA at start
    and checked there on every health probe. `routers` mounts the registry's routes (`ops_tools.modules`).
    `egress` is the policy every outbound request follows; without it no http operation runs. `http_client` is what
    those requests go through: by default the policy's own client, in tests one bound to a fake API.
    `secret_resolver` resolves `{{NAME}}` header references at call time; without it an operation needing a secret
    is refused. `cors_origins` are the browser origins (the console) allowed to call these routes. `auth` resolves
    callers (ops_identity's shared dependency); by default it is built from Settings for audience "tools". `background`
    runs beside the server from start-up and is cancelled at shutdown (the copy of reviews into Reviews).
    `write_approvals` reads each team's appChanges and appChangesByApp live; without it only a tool's own setting
    decides.
    `requester_policy` reads the tenant's requesterMayDecide live, so an approval the asker gave themselves is checked
    again at the call; without it the dev policies decide.
    `authenticator` signs a module's calls in through its connection; without it a connection adds nothing.
    `directory` holds the teams the MCP adapter scopes each assistant's tools to; without it no /mcp.
    `flags` are the install's feature flags, none on unless given: /mcp is served only with `mcp_gateway` on.
    `code` runs code operations on runner-service and checks their calls back; without it they fail."""
    rules = policy if policy is not None else POLICY_FILE.read_text()
    client = http_client or (egress_client(egress) if egress else httpx.AsyncClient())
    http_executor = HttpExecutor(client, egress, secret_resolver, authenticator)
    executor = Executor(
        runner,
        http_executor,
        mocks=MockAnswers(MockStore(log.engine)),
        code=code,
        # A plugin's Python tools run here, with the http executor's sign-in and egress client.
        plugins=PluginExecutor(plugins, http_executor, cursor_key) if plugins is not None else None,
    )
    expected = policy_hash(rules)
    counters = rates or RateWindows(log.engine)

    async def with_test_account(
        tenant_id: str, team_id: str | None, mods: dict[str, Any], rows: list[dict[str, Any]]
    ) -> set[str]:
        """The ids of the written-to modules whose app has a test account in `team_id`, as records.account_for
        chooses one for a test run: a plugin's app by its plugin, any other by its connection's app."""
        if not team_id:
            return set()
        store = ConnectionStore(log.engine)
        found: set[str] = set()
        with isolation.scope(tenant_id, team_id):
            for mid in {str(r.get("module_id") or "") for r in rows if r["access"] in WRITES} & set(mods):
                m = mods[mid]
                template = str(m.get("template_id") or "")
                conn = await store.get(tenant_id, str(m["connection_id"])) if m.get("connection_id") else None
                app = plugin_app(template.removeprefix("plugin:")) if template.startswith("plugin:") else None
                app = app or (str(conn["app_id"]) if conn else None)
                if app and any(a.get("sandbox") for a in await store.accounts(tenant_id, team_id, app)):
                    found.add(mid)
        return found

    access_check = Access()

    def approver(p: Principal) -> bool:
        return approves_own_writes(access_check, p)

    calls = GatewayCalls(
        registry=registry,
        log=log,
        opa=opa,
        executor=executor,
        counters=counters,
        send_check=send_check,
        clock=clock,
        approvals=write_approvals,
        approver=approver,
        # An approval the asker gave themselves counts only while today's policy lets an asker decide.
        requester_may_decide=(requester_policy or RequesterMayDecide(None, dev=Settings().dev_policies)).allowed,
    )
    if modules is not None:
        # A tool page's Real run is this gateway's call, never a path of the registry's own.
        modules.real_runs = calls.console_run

    resolved_auth = auth or Auth.from_settings(Settings(), audience="tools")
    mcp = (
        McpAdapter(calls=calls, registry=registry, directory=directory, auth=resolved_auth)
        if directory is not None and (flags or Flags()).on("mcp_gateway")
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        await opa.load_review_key(review_key)
        await opa.load_identities(registered_identities())
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
    install_held_hosts(app)
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
    else:
        app.mount("/mcp", _mcp_off)

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

    def team_view(caller: Principal) -> Callable[[Aggregate], bool] | None:
        """The modules a run of the caller's team may reach: its own, workspace-level ones, and those approved
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
        """The operations an agent of the caller's tenant may be granted, for a service holding `tools:view`.
        agents-service lists, grants and hands a run its tools from here; it keeps no catalogue of its own."""
        can(caller, "tools", "view", what="the grantable operations")
        rows = await registry.grantable(caller.tenant_id, team_view(caller))
        if plugins is not None and caller.team_id:
            # A tool the team has not added from its app's catalog is listed as not added: agents are not offered it,
            # and a run that calls it is refused with the fix.
            off = await plugins.tools_off(caller.tenant_id, caller.team_id)
            rows = [r | {"added": False} if str(r["name"]) in off else r for r in rows]
        mods = (
            {str(m["id"]): m for m in await registry.modules.all_teams(caller.tenant_id)}
            if registry.modules and write_approvals is not None and any(r["access"] in WRITES for r in rows)
            else {}
        )

        if write_approvals is not None:
            # The one rule behind the gateway's wait: each write's answer from its own setting, its app and the team.
            tested = await with_test_account(caller.tenant_id, caller.team_id, mods, rows)
            levels = await write_approvals.levels(caller.tenant_id, caller.team_id)
            out: list[dict[str, Any]] = []
            for r in rows:
                if r["access"] not in WRITES:
                    out.append(r)
                    continue
                m = mods.get(str(r.get("module_id") or ""))
                ans = await write_approvals.answer(
                    caller.tenant_id,
                    caller.team_id,
                    m,
                    access=r["access"],
                    setting=r.get("setting"),
                    approvers=r["approvers"],
                    levels=levels,
                )
                out.append(
                    r
                    | {
                        "requires_approval": ans["waits"],
                        "answer": ans["answer"],
                        "reviewer_role": ans["reviewerRole"],
                        "source": ans["source"],
                    }
                )
            rows = out
        if write_approvals is not None:
            tested = await with_test_account(caller.tenant_id, caller.team_id, mods, rows)
            rows = [r | {"test_account": str(r.get("module_id") or "") in tested} for r in rows]
        data = [GrantableOperation.model_validate(r).model_dump(by_alias=True) for r in rows]
        return JSONResponse({"success": True, "data": data})

    @app.get("/v1/tools/{name}", tags=["gateway"], responses=error_responses())
    async def tool_access(name: str, caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token): a tool's access class from the gateway's registry, the one the policy decides
        on. The review service asks here how many approvers a call needs instead of reading the registry itself."""
        access, policy, output, deadline = await registry.described(name, caller.tenant_id, caller.team_id)
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
        # `output`: what the operation answers, a step's output fields before it runs; null when unknown.
        # `deadlineSeconds`: how long the gateway may take over one call, which the engine's step waits out.
        data = {
            "name": name,
            "access": access,
            "approval": approval,
            "outputSchema": output,
            "deadlineSeconds": deadline,
        }
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
        body: CallIn,
        caller: CurrentService,
        x_lease_generation: Annotated[int | None, Header()] = None,
        x_acting_for: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        # Whom the call acts for comes only from the token platform-service signed for the calling service.
        acting = await resolved_auth.identity.acting_for(x_acting_for, caller) if x_acting_for else None
        request = CallRequest(
            tool=body.tool,
            input=body.input,
            key=body.key,
            run_context=body.run_context.model_dump(),
            approval_token=body.approval_token,
            acting_for=acting,
        )
        found = await calls.call(caller, request, generation=x_lease_generation, channel=API, sees=team_view(caller))
        return as_response(found)

    @app.post("/v1/code-runs/calls", tags=["gateway"], response_model=Envelope[CallResult], responses=error_responses())
    async def code_run_call(  # pyright: ignore[reportUnusedFunction]
        body: CodeCallIn, caller: CurrentService, x_code_run: Annotated[str | None, Header()] = None
    ) -> JSONResponse:
        """Internal: one `ops.call` from a running code operation, sent by runner-service with the run's call
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
            acting_for=run_acting_for(claims),
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
