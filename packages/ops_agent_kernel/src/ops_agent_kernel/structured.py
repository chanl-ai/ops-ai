"""One model call outside a turn's loop: a guardrail check, a judge's verdict, a correction, the closing answer at the
budget, a workflow's one-shot step. It goes through the same gateway client as the loop's calls, naming its purpose
(`X-Call-Purpose`) and the headers the endpoint gives that purpose, so the gateway budgets and records it as one of
the turn's calls (docs/design/agents-v2/model-gateway.md).

A call with a schema offers one function, `final_result`, and requires it; its arguments are the answer. A model that
answers in text instead is read as JSON text. Whether the answer matches the schema is the caller's to check.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, cast

import openai

from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import json_object

from .contract import ModelEndpoint
from .ports import PURPOSE_HEADER, BudgetReachedError
from .types import TokenUsage

ANSWER_TOOL = "final_result"
# A 429 with one of these codes is the gateway refusing the call at its budget (ports.BudgetReachedError).
BUDGET_CODES = frozenset({"budget_reached", "check_cap_reached"})


@dataclass(frozen=True)
class Answered:
    """What the call returned: its text, the parsed answer when it had a schema (None when the model's answer is not
    JSON), what it spent, and the model that answered."""

    text: str
    value: JsonValue | None
    usage: TokenUsage
    model_id: str


class CallRefused(Exception):
    """The gateway refused the call (any refusal but the budget's): its status and body."""

    def __init__(self, status: int, body: object) -> None:
        super().__init__(f"The model call was refused ({status}).")
        self.status = status
        self.body = body


def refusal_code(body: object) -> str | None:
    """The `code` of a refusal body, whether the client kept the whole envelope or only its `error` member."""
    fields = json_object(body)
    inner = fields.get("error")
    value = inner.get("code") if isinstance(inner, dict) else fields.get("code")
    return str(value) if value else None


async def ask(
    endpoint: ModelEndpoint,
    *,
    system: str,
    prompt: str,
    purpose: str,
    schema: Json | None = None,
    messages: list[Json] | None = None,
    params: Json | None = None,
) -> Answered:
    """One request: `system`, then `messages` (OpenAI chat messages, a run's exchange so far), then `prompt` as the
    person's message. Raises BudgetReachedError at the budget, CallRefused for any other refusal, and whatever the
    client raised for a call that never got an answer."""
    body: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system},
            *(messages or []),
            {"role": "user", "content": prompt},
        ],
        **(params or {}),
    }
    if schema is not None:
        body["tools"] = [{"type": "function", "function": {"name": ANSWER_TOOL, "parameters": schema}}]
        body["tool_choice"] = {"type": "function", "function": {"name": ANSWER_TOOL}}
    at = endpoint
    while True:
        headers = await at.headers(purpose) if at.headers is not None else {}
        started = time.perf_counter()
        try:
            response = await at.client.chat.completions.create(
                model=at.model_id, extra_headers={PURPOSE_HEADER: purpose, **headers}, **body
            )
        except openai.APIStatusError as e:
            if at.fallback is not None and at.falls_back is not None and at.falls_back(e.status_code, e.body):
                at = at.fallback
                continue
            if e.status_code == 429 and refusal_code(e.body) in BUDGET_CODES:
                raise BudgetReachedError() from e
            raise CallRefused(e.status_code, e.body) from e
        break
    usage = response.usage
    spent = TokenUsage(usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0, 1)
    if at.answered is not None:
        at.answered(spent.input_tokens, spent.output_tokens, time.perf_counter() - started)
    message = response.choices[0].message if response.choices else None
    text = str(message.content or "") if message is not None else ""
    calls = list(message.tool_calls or []) if message is not None else []
    raw = next((c.function.arguments for c in calls if c.function.name == ANSWER_TOOL), None)
    value: JsonValue | None = None
    if schema is not None:
        try:
            value = cast(JsonValue, json.loads(raw if raw is not None else text))
        except ValueError:
            value = None
    return Answered(text.strip(), value, spent, str(response.model or at.model_id))
