"""A test's own Pydantic AI `FunctionModel` answering at the HTTP edge, so the same test runs on either agent loop.

The kernel's Strands loop only speaks the model gateway's wire (OpenAI chat completions); a `FunctionModel` has no
wire. `on_wire` puts the test's `respond(messages, info)` behind the scripted gateway (`tests.conftest.model_on`): each
request body is read back into the messages and `AgentInfo` the function expects, built only from what the request
sent, and its `ModelResponse` is written back as the scripted reply. Assertions stay as the test wrote them.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, cast

import httpx2
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.tools import ToolDefinition

from ops_agent_kernel.models import ModelsServiceModels
from ops_agent_kernel.testing import Reply, ScriptedModel, ToolCall
from ops_service_kit.http import Json


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(cast(Json, p).get("text") or "") for p in cast(list[Any], content) if isinstance(p, dict))
    return ""


def _content(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def messages_of(wire: list[Json]) -> list[ModelMessage]:
    """The request's messages as Pydantic AI history: consecutive system, user and tool messages in one request."""
    out: list[ModelMessage] = []
    names: dict[str, str] = {}
    asked: list[ModelRequestPart] = []
    for m in wire:
        role, text = m.get("role"), _text(m.get("content"))
        if role == "assistant":
            if asked:
                out.append(ModelRequest(parts=asked))
                asked = []
            parts: list[Any] = [TextPart(text)] if text else []
            for c in cast(list[Json], m.get("tool_calls") or []):
                fn = cast(Json, c["function"])
                names[str(c["id"])] = str(fn["name"])
                parts.append(ToolCallPart(str(fn["name"]), json.loads(str(fn.get("arguments") or "{}")), str(c["id"])))
            out.append(ModelResponse(parts=parts))
        elif role in ("system", "developer"):
            asked.append(SystemPromptPart(text))
        elif role == "tool":
            call_id = str(m.get("tool_call_id") or "")
            asked.append(ToolReturnPart(names.get(call_id, ""), _content(text), tool_call_id=call_id))
        else:
            asked.append(UserPromptPart(text))
    if asked:
        out.append(ModelRequest(parts=asked))
    return out


def info_of(body: Json, tools: list[Json]) -> AgentInfo:
    """What the request offered: its tools, whether it asks for JSON (a response format), its reasoning effort."""
    defs = [
        ToolDefinition(
            name=str(fn["name"]),
            description=str(fn.get("description") or ""),
            parameters_json_schema=cast(Json, fn.get("parameters") or {}),
        )
        for t in tools
        if isinstance(fn := t.get("function"), dict)
    ]
    asked = cast(Json, body.get("response_format") or {}).get("json_schema")
    wanted = (
        OutputObjectDefinition(
            json_schema=cast(Json, asked.get("schema") or {}),
            name=cast(str | None, asked.get("name")),
            description=cast(str | None, asked.get("description")),
        )
        if isinstance(asked, dict)
        else None
    )
    params = ModelRequestParameters(
        function_tools=defs,
        output_mode="native" if wanted is not None else "text",
        output_object=wanted,
        allow_text_output=True,
        thinking=cast(Any, body.get("reasoning_effort")),
    )
    instructions = " ".join(
        _text(m.get("content")) for m in cast(list[Json], body.get("messages") or []) if m.get("role") == "system"
    )
    return AgentInfo(
        function_tools=defs,
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=params,
        instructions=instructions or None,
    )


def reply_of(response: ModelResponse) -> Reply:
    text = "".join(p.content for p in response.parts if isinstance(p, TextPart))
    calls = [ToolCall(p.tool_name, p.args_as_dict()) for p in response.parts if isinstance(p, ToolCallPart)]
    u = response.usage
    return Reply(text=text, tool_calls=calls, input_tokens=u.input_tokens or 10, output_tokens=u.output_tokens or 5)


async def _streamed(stream: Any, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A stream-only FunctionModel's chunks as one response: text pieces, and tool calls by their index."""
    text, calls = "", dict[int, list[str]]()
    async for chunk in stream(messages, info):
        if isinstance(chunk, str):
            text += chunk
            continue
        for i, delta in cast(dict[int, DeltaToolCall], chunk).items():
            name, args = calls.setdefault(i, ["", ""])
            calls[i] = [name + (delta.name or ""), args + (delta.json_args or "")]
    parts: list[Any] = [TextPart(text)] if text else []
    parts += [ToolCallPart(n, json.loads(a or "{}")) for _, (n, a) in sorted(calls.items())]
    return ModelResponse(parts=parts)


def on_wire(model: FunctionModel) -> Model:
    """`model`'s stream (or its `respond`, when it has no stream) behind the scripted gateway (as
    `tests.conftest.model_on`): the kernel's model on either loop."""
    respond, stream = model.function, model.stream_function
    assert respond is not None or stream is not None

    async def script(messages: list[Json], tools: list[Json]) -> Reply:
        # The transport keeps each body before it asks the script, so the newest is this request's.
        history, info = messages_of(messages), info_of(wire.requests[-1], tools)
        # The stream first, as the loops ask for one: a test's stream that fails part-way fails the call.
        if stream is not None:
            return reply_of(await _streamed(stream, history, info))
        answered: Any = cast(Any, respond)(history, info)
        if inspect.isawaitable(answered):
            answered = await answered
        return reply_of(cast(ModelResponse, answered))

    wire = ScriptedModel(script)
    http = httpx2.AsyncClient(transport=wire)
    return ModelsServiceModels("http://models.scripted", "mk_scripted", http_client=http).model_for("scripted")


__all__ = ["info_of", "messages_of", "on_wire", "reply_of"]
