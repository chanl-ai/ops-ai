"""POST /v1/chat/completions, streaming and not, and GET /v1/models, answered from a rule set.

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
    # agent does not hold is refused rather than run.
    force: bool = False


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
        if rule.tool and rule.tool not in offered and not rule.force:
            continue
        captured: dict[str, str] = {}
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
            text = json.dumps(_fill(matched.arguments, captured))
            return Completion(text, prompt_tokens, len(text.split()))
        if matched.tool:
            call = {
                "id": f"call_fake_{len(messages)}",
                "type": "function",
                "function": {"name": matched.tool, "arguments": json.dumps(_fill(matched.arguments, captured))},
            }
            return Completion(None, prompt_tokens, 1, [call])
        text = str(_fill(matched.text, captured))
        return Completion(text, prompt_tokens, len(text.split()))
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


def create_app(script: Script, api_key: str | None = None) -> FastAPI:
    """With `api_key`, a request that sends a credential must send that one, or it is refused as OpenAI refuses a wrong
    key; a request with none is still answered, for the connections in the same stack that name no key."""
    app = FastAPI(title="Fake OpenAI", version="1.0.0")

    def wrong_key(request: Request) -> JSONResponse | None:
        sent = request.headers.get("authorization")
        if api_key is None or sent is None or sent == f"Bearer {api_key}":
            return None
        error = {"message": "Incorrect API key provided.", "type": "invalid_request_error", "code": "invalid_api_key"}
        return JSONResponse({"error": error}, status_code=401)

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
        model = str(body.get("model") or "unknown")
        done = await answer(script, model, body)
        messages: list[Any] = list(body.get("messages") or [])
        base = {"id": f"chatcmpl-fake-{len(messages)}", "created": 0, "model": model}
        if body.get("stream"):
            options: dict[str, Any] = dict(body.get("stream_options") or {})
            with_usage = bool(options.get("include_usage"))

            async def events() -> AsyncIterator[str]:
                for chunk in completion_chunks(done):
                    if chunk.get("usage") and not with_usage:
                        continue
                    yield f"data: {json.dumps({**base, **chunk})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
        message: dict[str, Any] = {"role": "assistant", "content": done.text}
        if done.tool_calls:
            message["tool_calls"] = done.tool_calls
        usage = {
            "prompt_tokens": done.input_tokens,
            "completion_tokens": done.output_tokens,
            "total_tokens": done.input_tokens + done.output_tokens,
        }
        choice = {"index": 0, "message": message, "finish_reason": done.finish_reason}
        return JSONResponse({**base, "object": "chat.completion", "choices": [choice], "usage": usage})

    return app
