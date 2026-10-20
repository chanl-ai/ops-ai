"""The kernel's model wrapper: every model request of a graph run recorded once, replayed on a crashed node's re-run.

The spec's agent activity keeps a step ledger in its heartbeat; on the LangGraph adapter a resume node that
crashes after its turn runs again from its start, and without a ledger it calls the model again. `LedgerModel`
wraps the kernel's model: inside a graph run (a LangGraph config with a thread) each response is recorded under the
thread and a hash of the request, and the same request on the same thread is answered from the record. Outside a
graph run (chat turns) it passes through. The request hash leaves out timestamps and run ids, which differ between
the first run and the re-run while the conversation is the same.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol, cast

from langgraph.config import get_config
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from ops_agent_kernel.ports import ModelSource
from ops_agents.graphs.common import emit
from ops_agents.graphs.metering import CallSite, call_site
from ops_metering import Usage

_VOLATILE = frozenset({"timestamp", "run_id", "provider_response_id", "provider_details"})


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        items = cast(dict[str, Any], value)
        return {k: _stable(items[k]) for k in sorted(items) if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in cast(list[Any], value)]
    return value


def request_hash(messages: list[ModelMessage]) -> str:
    dumped = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    return hashlib.sha256(json.dumps(_stable(dumped), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class _Site:
    call: CallSite
    task: str | None


def _site() -> _Site | None:
    """Where the request runs: the graph call site and the LangGraph task, which a crashed node's re-run keeps and a
    new step does not. None outside a graph run."""
    call = call_site()
    if call is None:
        return None
    cfg = get_config()
    task = (cfg.get("configurable") or {}).get("checkpoint_ns") or (cfg.get("metadata") or {}).get(
        "langgraph_checkpoint_ns"
    )
    return _Site(call, str(task) if task else None)


class ModelCallRecorder(Protocol):
    """Where the wrapper records each request and finds a recorded one (store/usage.py's UsageLedger)."""

    async def recorded_response(self, thread_id: str, task: str, request_hash: str) -> Any: ...

    async def record_model_call(
        self,
        site: CallSite,
        alias: str,
        usage: Usage,
        *,
        latency_ms: int,
        task: str | None,
        request_hash: str,
        response: Any,
    ) -> bool: ...


def _replay(recorded: ModelResponse) -> FunctionModel:
    """A model that streams exactly the recorded response."""

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for i, part in enumerate(recorded.parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {
                    i: DeltaToolCall(
                        name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id=part.tool_call_id
                    )
                }

    return FunctionModel(stream_function=stream, model_name=recorded.model_name)


class LedgerModel(WrapperModel):
    """The kernel's model with every request of a graph run recorded: alias, tokens, latency, thread, run, step, task,
    request hash and response. A request already recorded for the same task is answered from the record."""

    def __init__(self, wrapped: Model, recorder: ModelCallRecorder, alias: str, *, call_headers: bool = False) -> None:
        super().__init__(wrapped)
        self.recorder = recorder
        self.alias = alias
        # Through models-service, each request names its thread, run, step and request hash, so its call log row
        # joins this record. Never sent to a provider directly.
        self.call_headers = call_headers

    def _with_call_headers(
        self, settings: ModelSettings | None, site: _Site | None, digest: str
    ) -> ModelSettings | None:
        if not self.call_headers or site is None:
            return settings
        headers = {"X-Thread-Id": site.call.thread_id, "X-Step-Id": site.call.node, "X-Request-Hash": digest}
        if site.call.run_id:
            headers["X-Run-Id"] = site.call.run_id
        merged: ModelSettings = {**(settings or {})}
        merged["extra_headers"] = {**(merged.get("extra_headers") or {}), **headers}
        return merged

    async def _recorded(self, site: _Site, digest: str) -> ModelResponse | None:
        if site.task is None:
            return None
        raw = await self.recorder.recorded_response(site.call.thread_id, site.task, digest)
        return ModelMessagesTypeAdapter.validate_python([raw])[0] if raw else None  # type: ignore[return-value]

    async def _record(self, site: _Site, digest: str, response: ModelResponse, started: float) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        u = response.usage
        usage = Usage(u.input_tokens, u.output_tokens, 1)
        dumped = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
        await self.recorder.record_model_call(
            site.call,
            self.alias,
            usage,
            latency_ms=latency_ms,
            task=site.task,
            request_hash=digest,
            response=dumped,
        )
        emit(
            "model_call",
            site.call.node,
            {
                "alias": self.alias,
                "inputTokens": u.input_tokens,
                "outputTokens": u.output_tokens,
                "latencyMs": latency_ms,
                "requestHash": digest,
            },
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        site = _site()
        if site is None:
            return await super().request(messages, model_settings, model_request_parameters)
        digest = request_hash(messages)
        if (recorded := await self._recorded(site, digest)) is not None:
            return recorded
        started = time.perf_counter()
        response = await super().request(
            messages, self._with_call_headers(model_settings, site, digest), model_request_parameters
        )
        await self._record(site, digest, response, started)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncGenerator[StreamedResponse]:
        site = _site()
        digest = request_hash(messages) if site else ""
        recorded = await self._recorded(site, digest) if site else None
        source: Model = _replay(recorded) if recorded is not None else self.wrapped
        started = time.perf_counter()
        settings = self._with_call_headers(model_settings, site, digest)
        async with source.request_stream(messages, settings, model_request_parameters, run_context) as stream:
            yield stream
        # Recorded once the stream has been read to the end, so a response cut off by a crash is never replayed.
        if site and recorded is None:
            await self._record(site, digest, stream.get(), started)


class LedgerSource:
    """Each alias's model wrapped once in `LedgerModel`, so a call is recorded under the alias it ran on and carries the
    call headers models-service logs."""

    def __init__(self, models: ModelSource, recorder: ModelCallRecorder) -> None:
        self.source = models
        self.recorder = recorder
        self.models: dict[str, Model] = {}

    def model_for(self, alias: str) -> Model:
        if alias not in self.models:
            self.models[alias] = LedgerModel(self.source.model_for(alias), self.recorder, alias, call_headers=True)
        return self.models[alias]
