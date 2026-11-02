"""POST /v1/chat/completions, streaming and not, GET /v1/models, and Azure OpenAI's two chat paths, answered from a rule
set.

When the request offers tools and its last message is the user's, the first rule whose `when` pattern matches that
message and whose `tool` is offered becomes a tool call with the rule's arguments; a rule with `text` instead answers
that text (a cited answer, or the not-in-the-knowledge-base reply). A rule with `after` applies once a tool result is
back: when the assistant's last call was that tool and the result matches `result`, the rule's `tool` call or `text`
follows, so a turn can chain reads. Named groups in `when` (which sees the knowledge block ahead of the question) and
`result` fill `{name}` in the text and the arguments: a rule fires only on its evidence and quotes it. With no rule
matching, the scripted provider's `call <tool>` convention applies. Otherwise the reply is text
naming the agent from the system prompt (`You are <name>,`) and the gist of the last message, so a caller can tell
which prompt and which turn produced it. Token counts are word counts, the same as the scripted provider's.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ops_models.providers import Completion, ScriptedProvider, completion_chunks

GIST_WORDS = 12
# The output tool a structured call (a guardrail or memory check) offers for its answer: not a tool to act with.
ANSWER_TOOL = "final_result"
_AGENT = re.compile(r"\bYou are ([^,.\n]+)")


@dataclass(frozen=True)
class Rule:
    when: str = ""
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=lambda: {})
    text: str | None = None
    # The tool whose result the request's last message carries; the rule then applies in place of `when`.
    after: str | None = None
    # For an `after` rule: a pattern the tool result's content must match. Named groups in `when` and `result`
    # fill `{name}` in `text` and in string arguments, so an answer quotes its evidence rather than a constant.
    result: str | None = None
    # Calls `tool` even when the request does not offer it, as a model might: how a use case proves that a tool an
    # agent does not hold is refused rather than run. Only in a request that offers a tool to act with: a guardrail or
    # memory check offers none, or only its answer's `final_result`, and is answered by its own rules.
    force: bool = False
    # A pattern an earlier user message must match, its named groups filling `{name}` as `when`'s do: a follow-up such
    # as "I connected Salesforce. Please go ahead." acts on the case the person asked about before it.
    before: str | None = None


@dataclass(frozen=True)
class Script:
    rules: list[Rule]
    models: list[str]
    port: int | None = None


def load_script(folder: Path) -> Script:
    """`<folder>/script.json`: {"port"?, "models"?, "rules": [{"when", "tool", "arguments"?}]}; absent, no rules."""
    path = folder / "script.json"
    raw: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
    listed: list[dict[str, Any]] = list(raw.get("rules") or [])
    rules = [
        Rule(
            str(r.get("when") or ""),
            str(r["tool"]) if r.get("tool") else None,
            dict(r.get("arguments") or {}),
            str(r["text"]) if r.get("text") else None,
            str(r["after"]) if r.get("after") else None,
            str(r["result"]) if r.get("result") else None,
            bool(r.get("force")),
            str(r["before"]) if r.get("before") else None,
        )
        for r in listed
    ]
    models = [str(m) for m in raw.get("models") or ["default"]]
    port = raw.get("port")
    return Script(rules, models, int(port) if port is not None else None)


def _text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, list):  # content parts
        parts: list[Any] = list(content)  # pyright: ignore[reportUnknownArgumentType]
        texts: list[dict[str, Any]] = [p for p in parts if isinstance(p, dict)]
        return " ".join(str(p.get("text", "")) for p in texts)
    return str(content or "")


def _gist(text: str) -> str:
    words = text.split()
    return " ".join(words[:GIST_WORDS]) + (" ..." if len(words) > GIST_WORDS else "")


def _agent(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        if m.get("role") in ("system", "developer") and (found := _AGENT.search(_text(m))):
            return found.group(1).strip()
    return "assistant"


def _last_call(messages: list[dict[str, Any]]) -> str | None:
    """The tool whose result the last message carries: the name in the assistant's preceding `tool_calls`."""
    if not messages or messages[-1].get("role") != "tool":
        return None
    for m in reversed(messages[:-1]):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls: list[dict[str, Any]] = list(m["tool_calls"])
            wanted = messages[-1].get("tool_call_id")
            hit = next((c for c in calls if c.get("id") == wanted), calls[-1])
            function: dict[str, Any] = dict(hit.get("function") or {})
            return str(function.get("name") or "")
    return None


def _fit(arguments: dict[str, Any], declared: dict[str, Any]) -> dict[str, Any]:
    """The rule's arguments cut to the properties the answer's schema declares, so one rule written for what a customer
    said can answer a classify, a summary and a draft step alike: each step keeps only the fields it asks for."""
    return {k: v for k, v in arguments.items() if k in declared} if declared else arguments


def _declared(parameters: Any) -> dict[str, Any]:
    """`properties` of a JSON schema, empty when it names none."""
    if isinstance(parameters, dict):
        found = cast(dict[str, Any], parameters).get("properties")
        if isinstance(found, dict):
            return cast(dict[str, Any], found)
    return {}


def _fill(template: Any, captured: dict[str, str]) -> Any:
    """`{name}` in a string (or in the strings of a list or dict) replaced by what the rule's patterns captured."""
    if isinstance(template, str):
        return template.format_map(_Captured(captured))
    if isinstance(template, list):
        items: list[Any] = list(cast(list[Any], template))
        return [_fill(x, captured) for x in items]
    if isinstance(template, dict):
        pairs: dict[str, Any] = dict(cast(dict[str, Any], template))
        return {k: _fill(v, captured) for k, v in pairs.items()}
    return template


class _Captured(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _rule_for(script: Script, messages: list[dict[str, Any]], offered: set[str]) -> tuple[Rule, dict[str, str]] | None:
    """The first rule that applies, with what its patterns captured: an `after` rule to the tool just answered (its
    `result` pattern on the tool's content, its `when` on the question), else a `when` rule to the user's last
    message, which carries the knowledge block, so a cited answer can require its passage. A rule naming a tool
    applies only when that tool is offered."""
    last = messages[-1] if messages else {}
    finished = _last_call(messages)
    user_said = [_text(m) for m in messages if m.get("role") == "user"]
    for rule in script.rules:
        if rule.tool and rule.tool not in offered and not (rule.force and offered - {ANSWER_TOOL}):
            continue
        captured: dict[str, str] = {}
        if rule.before:
            hits = (re.search(rule.before, t, re.IGNORECASE | re.DOTALL) for t in reversed(user_said[:-1]))
            earlier = next((m for m in hits if m is not None), None)
            if earlier is None:
                continue
            captured.update({k: v for k, v in earlier.groupdict().items() if v is not None})
        if rule.after:
            if finished != rule.after:
                continue
            asked = user_said[-1] if user_said else ""
            on_question = re.search(rule.when, asked, re.IGNORECASE | re.DOTALL) if rule.when else None
            if rule.when and on_question is None:
                continue
            on_result = re.search(rule.result, _text(last), re.IGNORECASE | re.DOTALL) if rule.result else None
            if rule.result and on_result is None:
                continue
            for m in (on_question, on_result):
                if m is not None:
                    captured.update({k: v for k, v in m.groupdict().items() if v is not None})
            return rule, captured
        if last.get("role") == "user" and rule.when:
            found = re.search(rule.when, _text(last), re.IGNORECASE | re.DOTALL)
            if found is not None:
                captured.update({k: v for k, v in found.groupdict().items() if v is not None})
                return rule, captured
    return None


async def answer(script: Script, model: str, body: dict[str, Any]) -> Completion:
    messages: list[dict[str, Any]] = list(body.get("messages") or [])
    prompt_tokens = sum(len(_text(m).split()) for m in messages)
    tools: list[dict[str, Any]] = list(body.get("tools") or [])
    functions: list[dict[str, Any]] = [t.get("function") or {} for t in tools]
    offered = {str(f.get("name")) for f in functions}
    # Native structured output (response_format json_schema, as pydantic-ai's NativeOutput sends): the answer is the
    # message's content, so a rule naming the schema's tool (final_result) answers with its arguments as that content.
    fmt: dict[str, Any] = dict(body.get("response_format") or {})
    schema: dict[str, Any] = dict(fmt.get("json_schema") or {})
    native = str(schema.get("name") or "") if fmt.get("type") == "json_schema" else ""
    last = messages[-1] if messages else {}
    if (hit := _rule_for(script, messages, offered | ({native} if native else set()))) is not None:
        matched, captured = hit
        if matched.tool and matched.tool == native and native not in offered:
            filled = _fit(_fill(matched.arguments, captured), _declared(schema.get("schema")))
            text = json.dumps(filled)
            return Completion(text, prompt_tokens, len(text.split()))
        if matched.tool:
            wanted = next((f.get("parameters") for f in functions if f.get("name") == matched.tool), None)
            filled = _fit(_fill(matched.arguments, captured), _declared(wanted))
            call = {
                "id": f"call_fake_{len(messages)}",
                "type": "function",
                "function": {"name": matched.tool, "arguments": json.dumps(filled)},
            }
            return Completion(None, prompt_tokens, 1, [call])
        text = str(_fill(matched.text, captured))
        return Completion(text, prompt_tokens, len(text.split()))
    if last.get("role") == "user":
        asked = _text(last)
        specialists = sorted(n for n in offered if n.startswith("agent__"))
        if specialists and re.search(r"(?i)research|handbook|delegate|specialist", asked):
            call = {
                "id": f"call_fake_{len(messages)}",
                "type": "function",
                "function": {"name": specialists[0], "arguments": json.dumps({"question": asked})},
            }
            return Completion(None, prompt_tokens, 1, [call])
        workflows = sorted(n for n in offered if n.startswith("workflow__"))
        if workflows and re.search(r"(?i)start a customer hold|start.*hold", asked):
            args: dict[str, Any] = {}
            if named := re.search(r"(?i)hold for (.+?) for ([\d.]+)", asked):
                args = {"customer": named.group(1).strip(), "amount": float(named.group(2))}
            call = {
                "id": f"call_fake_{len(messages)}",
                "type": "function",
                "function": {"name": workflows[0], "arguments": json.dumps(args)},
            }
            return Completion(None, prompt_tokens, 1, [call])
    if offered and last.get("role") == "user":
        scripted = await ScriptedProvider().complete(model, body)
        if scripted.tool_calls:
            return scripted
    agent = _agent(messages)
    if last.get("role") == "tool":
        text = f"{agent} read the tool result: {_gist(_text(last))}"
    else:
        text = f"{agent} on {model} heard: {_gist(_text(last))}"
    return Completion(text, prompt_tokens, len(text.split()))


# Azure OpenAI's annotations: a first stream frame with no choices carrying the prompt's filter results, filter results
# on each choice, and a choice with no delta once the answer is checked. Callers must ignore all three.
_FILTERED = {"hate": {"filtered": False, "severity": "safe"}, "violence": {"filtered": False, "severity": "safe"}}
_PROMPT_FRAME: dict[str, Any] = {
    "id": "",
    "object": "",
    "created": 0,
    "model": "",
    "choices": [],
    "prompt_filter_results": [{"prompt_index": 0, "content_filter_results": _FILTERED}],
}
# Azure answers a call on a deployment path with no api-version, or any path it does not serve, with this.
_NOT_FOUND = {"error": {"code": "404", "message": "Resource not found"}}
_DENIED = {
    "error": {
        "code": "401",
        "message": "Access denied due to invalid subscription key or wrong API endpoint. Make sure to provide a valid "
        "key for an active subscription and use a correct regional API endpoint for your resource.",
    }
}
# The first dated version whose streams carry usage under stream_options.include_usage.
_STREAM_USAGE_SINCE = "2024-09-01"


def create_app(script: Script, api_key: str | None = None, azure_region: str = "Sweden Central") -> FastAPI:
    """With `api_key`, a request that sends a credential must send that one, or it is refused as OpenAI refuses a wrong
    key; a request with none is still answered, for the connections in the same stack that name no key.

    Azure OpenAI's two paths are served beside OpenAI's: `/openai/deployments/{deployment}/chat/completions` needs an
    `api-version` query and the key in the `api-key` header (a bearer token is refused there), and
    `/openai/v1/chat/completions` takes the deployment as `model` and the key as `api-key` or a bearer token. Both
    answer with Azure's `x-ms-region` header (`azure_region`) and its filter annotations."""
    app = FastAPI(title="Fake OpenAI", version="1.0.0")

    def wrong_key(request: Request) -> JSONResponse | None:
        sent = request.headers.get("authorization")
        if api_key is None or sent is None or sent == f"Bearer {api_key}":
            return None
        error = {"message": "Incorrect API key provided.", "type": "invalid_request_error", "code": "invalid_api_key"}
        return JSONResponse({"error": error}, status_code=401)

    def azure_denied(request: Request, *, bearer: bool) -> JSONResponse | None:
        """None when the request signs in as Azure takes it: `api-key`, or on the v1 path also a bearer token."""
        sent = request.headers.get("api-key")
        if sent is None and bearer:
            auth = request.headers.get("authorization") or ""
            sent = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else None
        if sent is None or (api_key is not None and sent != api_key):
            return JSONResponse(_DENIED, status_code=401, headers={"x-ms-region": azure_region})
        return None

    async def reply(body: dict[str, Any], model: str, *, azure: bool, stream_usage: bool = True) -> Response:
        done = await answer(script, model, body)
        messages: list[Any] = list(body.get("messages") or [])
        base = {"id": f"chatcmpl-fake-{len(messages)}", "created": 0, "model": model}
        headers = {"x-ms-region": azure_region} if azure else {}
        if body.get("stream"):
            options: dict[str, Any] = dict(body.get("stream_options") or {})
            with_usage = bool(options.get("include_usage")) and stream_usage

            async def events() -> AsyncIterator[str]:
                if azure:
                    yield f"data: {json.dumps(_PROMPT_FRAME)}\n\n"
                for chunk in completion_chunks(done):
                    out: dict[str, Any] = chunk
                    if chunk.get("usage"):
                        if not with_usage:
                            continue
                        if azure:
                            # The answer's own check, after its last delta: a choice with no delta.
                            checked = {"index": 0, "finish_reason": None, "content_filter_results": _FILTERED}
                            frame = {**base, "object": "chat.completion.chunk", "choices": [checked]}
                            yield f"data: {json.dumps(frame)}\n\n"
                    elif azure:
                        choices: list[dict[str, Any]] = chunk["choices"]
                        out = {**chunk, "choices": [{**c, "content_filter_results": {}} for c in choices]}
                    yield f"data: {json.dumps({**base, **out})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
        message: dict[str, Any] = {"role": "assistant", "content": done.text}
        if done.tool_calls:
            message["tool_calls"] = done.tool_calls
        usage = {
            "prompt_tokens": done.input_tokens,
            "completion_tokens": done.output_tokens,
            "total_tokens": done.input_tokens + done.output_tokens,
        }
        choice: dict[str, Any] = {"index": 0, "message": message, "finish_reason": done.finish_reason}
        out: dict[str, Any] = {**base, "object": "chat.completion", "choices": [choice], "usage": usage}
        if azure:
            choice["content_filter_results"] = _FILTERED
            out["prompt_filter_results"] = _PROMPT_FRAME["prompt_filter_results"]
        return JSONResponse(out, headers=headers)

    @app.get("/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models(request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
        if (refused := wrong_key(request)) is not None:
            return refused
        rows = [{"id": m, "object": "model", "created": 0, "owned_by": "fake-openai"} for m in script.models]
        return {"object": "list", "data": rows}

    @app.post("/v1/chat/completions")
    async def completions(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        if (refused := wrong_key(request)) is not None:
            return refused
        body: dict[str, Any] = await request.json()
        return await reply(body, str(body.get("model") or "unknown"), azure=False)

    @app.post("/openai/deployments/{deployment}/chat/completions")
    async def azure_deployment(request: Request, deployment: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        version = request.query_params.get("api-version")
        if not version:
            return JSONResponse(_NOT_FOUND, status_code=404)
        if (refused := azure_denied(request, bearer=False)) is not None:
            return refused
        body: dict[str, Any] = await request.json()
        return await reply(body, deployment, azure=True, stream_usage=version >= _STREAM_USAGE_SINCE)

    @app.post("/openai/v1/chat/completions")
    async def azure_v1(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        if (refused := azure_denied(request, bearer=True)) is not None:
            return refused
        body: dict[str, Any] = await request.json()
        return await reply(body, str(body.get("model") or "unknown"), azure=True)

    return app
