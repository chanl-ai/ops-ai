"""The models each models-service route documents in OpenAPI. Admin routes answer in the platform envelope with
camelCase fields; the completion route speaks OpenAI's wire format (snake_case, no envelope), because OpenAI clients
are its callers. Routes build their JSON by hand; `ops_service_kit.contract` checks it against these in the tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from ops_service_kit.http import ExternalOut, In, Json, ListResult, Out, Passthrough


class Health(Out):
    status: str


class ProviderOut(Out):
    """A provider connection: where its calls go and the name of the key it signs in with, never the key."""

    id: str
    name: str
    type: str
    base_url: str | None
    key_ref: str | None
    # azure-openai only: `v1` or a dated version, the region it names, and the region Azure last answered from.
    api_version: str | None = None
    region: str | None = None
    observed_region: str | None = None
    # `answered from <region>, expected <region>` when they differ; computed here so no client compares regions.
    region_mismatch: str | None = None


class ProviderTypeOut(Out):
    """A provider type a connection can be made of, from the registry. `connection` is a JSON Schema object of the
    fields a connection of it takes; a field marked `x-secret` is saved as a provider key and never returned."""

    id: str
    label: str
    icon: str
    connection: Json
    # Whether a saved key can be tested and its models listed (POST /v1/provider-keys/{name}/check).
    lists_models: bool
    # Whether its models are in the model catalog, with capabilities, prices and knobs.
    catalogued: bool


class CatalogModelOut(Out):
    """One catalogued model: what it can do, its limits and list prices (per million tokens, None when unknown), and
    the knobs it takes."""

    id: str
    name: str
    context: int | None
    output: int | None
    reasoning: bool
    images: bool
    input_per_million: float | None
    output_per_million: float | None
    knobs: list[str]


class KnobsOut(Out):
    """The settings an agent on an alias may set: `knobs` is a JSON Schema object of only the knobs the alias's model
    takes, each with its type, title, description, range and catalog default."""

    alias: str
    version: int
    model_id: str
    catalogued: bool
    knobs: Json


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
    # The connection's name, for the aliases page; None when the connection is gone.
    provider_name: str | None = None
    # How many agents name this alias: for a person only, None when agents-service did not answer.
    used_by: int | None = None


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


class CallPage(ListResult[CallOut]):
    """A page of calls on the shared list contract, and per key the count and cost of every call that matches,
    whichever page it is on."""

    by_key: list[KeySpend]


class Admission(Out):
    admitted: bool
    remaining: str


BudgetKind = Literal["thread", "run", "step", "group", "eval", "draft"]


class BudgetIn(In):
    """A budget's caps, set by the service that owns its conversation or run. A null cap is no cap; a repeat with other
    caps moves them and never the spend. Kind, parent, team and creator are kept from the first PUT."""

    kind: BudgetKind
    # A step or group budget names its run budget.
    parent_id: str | None = Field(default=None, max_length=200)
    team_id: str = Field(min_length=1, max_length=64)
    # The module that creates it (`api/budgets.py`), for an operator reading the table.
    created_by: str = Field(min_length=1, max_length=80)
    max_cost_usd: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    max_calls: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None


class BudgetOut(Out):
    """A budget's caps, what was spent against them and what calls in flight hold. `exhausted` names the first cap
    the spend has reached."""

    id: str
    kind: BudgetKind
    parent_id: str | None
    team_id: str
    created_by: str
    max_cost_usd: Decimal | None
    max_calls: int | None
    max_tokens: int | None
    spent_cost_usd: Decimal
    spent_calls: int
    spent_tokens: int
    reserved_cost_usd: Decimal
    reserved_tokens: int
    exhausted: Literal["cost", "calls", "tokens"] | None
    updated_at: datetime


class BudgetQuery(In):
    ids: list[str] = Field(min_length=1, max_length=200)


class ChatCompletionRequest(Passthrough):
    """OpenAI's chat completion request. Fields this service does not read (temperature, tool_choice and the rest) are
    kept and forwarded to the provider."""

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    tools: list[dict[str, Any]] | None = None


class ToolFunction(ExternalOut):
    """The function a tool call names and its arguments, a JSON string as the model wrote it."""

    name: str
    arguments: str


class ToolCall(ExternalOut):
    """One tool call in OpenAI's reply format."""

    id: str
    type: Literal["function"]
    function: ToolFunction


class ChatMessage(ExternalOut):
    role: Literal["assistant"]
    content: str | None
    tool_calls: list[ToolCall] | None = None
    # The model's words when it declined, as OpenAI's format names them; unset otherwise.
    refusal: str | None = None


class ChatChoice(ExternalOut):
    index: int
    message: ChatMessage
    # `length`: cut at the output limit; `content_filter`: stopped by the provider's filter.
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"]


class ChatUsage(ExternalOut):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletion(ExternalOut):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage


class ChunkDelta(ExternalOut):
    """What one stream chunk adds to the reply. Dumped with `exclude_unset`, so a delta carries only the keys it was
    built with (`{}` on the finishing chunk)."""

    role: Literal["assistant"] | None = None
    content: str | None = None
    # The calls as the model wrote them, each with its `index` in the stream.
    tool_calls: list[Json] | None = None


class ChunkChoice(ExternalOut):
    index: int
    delta: ChunkDelta
    # Always set, `null` until the last chunk: OpenAI clients read the key on every chunk.
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"] | None


class ChatChunk(ExternalOut):
    """One `chat.completion.chunk` this service writes itself (the scripted provider). A real provider's chunks are
    passed on as parsed, never through this model, so a field it adds reaches the client unchanged."""

    object: Literal["chat.completion.chunk"]
    choices: list[ChunkChoice]
    # Only on the last chunk, which `stream_options.include_usage` asks for.
    usage: ChatUsage | None = None


class EmbeddingsRequest(In):
    """OpenAI's embeddings request: the alias as `model`, one text or a list, and the width when the caller names
    one."""

    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1, le=4096)


class EmbeddingRow(ExternalOut):
    object: Literal["embedding"]
    index: int
    embedding: list[float]


class EmbeddingsUsage(ExternalOut):
    prompt_tokens: int
    total_tokens: int


class Embeddings(ExternalOut):
    object: Literal["list"]
    model: str
    data: list[EmbeddingRow]
    usage: EmbeddingsUsage
