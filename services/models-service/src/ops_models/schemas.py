"""The models each models-service route documents in OpenAPI. Admin routes answer in the platform envelope with
camelCase fields; the completion route speaks OpenAI's wire format (snake_case, no envelope), because OpenAI clients
are its callers. Routes build their JSON by hand; `ops_service_kit.contract` checks it against these in the tests."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ops_service_kit.http import Out


class Health(BaseModel):
    status: str


class ProviderOut(Out):
    id: str
    name: str
    type: str
    base_url: str | None
    key_ref: str | None


class ProviderKeyOut(Out):
    """A model provider key's name and history; its value is never returned once saved."""

    name: str
    version: int
    created_by: str
    created_at: str
    rotated_at: str | None


class ProviderCreated(Out):
    id: str
    name: str
    type: str


class AliasOut(Out):
    name: str
    version: int
    kind: str
    provider_id: str
    model_id: str
    cleared_sensitivity: str
    input_per_million: str
    output_per_million: str
    status: str
    reasoning_effort: str | None = None
    images: bool = False


class AliasRef(Out):
    name: str
    version: int


class KeyOut(Out):
    id: str
    kind: str
    budget: str
    spent: str
    rate_limit_per_minute: int
    expires_at: str | None
    status: str
    rotated_at: str | None
    previous_valid_until: str | None


class KeySecret(Out):
    """Returned once, at issue; the service keeps only the secret's hash."""

    id: str
    secret: str


class KeyRotated(KeySecret):
    previous_valid_until: str


class CallOut(Out):
    id: str
    key_id: str
    alias: str
    alias_version: int | None
    provider_model: str | None
    input_tokens: int
    output_tokens: int
    cost: str
    latency_ms: int
    outcome: str
    reason: str | None
    run_id: str | None
    step_id: str | None
    thread_id: str | None
    request_hash: str | None
    created_at: str | None
    images: int = 0


class KeySpend(Out):
    key_id: str
    calls: int
    cost: str


class CallPage(Out):
    items: list[CallOut]
    by_key: list[KeySpend]


class Admission(Out):
    admitted: bool
    remaining: str


class ChatCompletionRequest(BaseModel):
    """OpenAI's chat completion request. Fields this service does not read (temperature, tool_choice and the rest) are
    kept and forwarded to the provider."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    tools: list[dict[str, Any]] | None = None


class _OpenAI(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(_OpenAI):
    role: Literal["assistant"]
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None


class ChatChoice(_OpenAI):
    index: int
    message: ChatMessage
    finish_reason: Literal["stop", "tool_calls"]


class ChatUsage(_OpenAI):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletion(_OpenAI):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage
