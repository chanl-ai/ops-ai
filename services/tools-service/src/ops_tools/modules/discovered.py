"""What discovery finds in a source (an OpenAPI document or an MCP server) and what import stores of it.

`openapi.discover`, `mcp.discovered` and a hand-built HTTP tool all produce a `DiscoveredOperation`;
`ModuleService._new_op` stores one. The document or server they read stays loose JSON: only the operations
built from it are named here."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from ops_service_kit.http import Json, JsonValue

from ..store.modules import CodeSettings, Header, InputField


class DiscoveredOperation(TypedDict):
    """One operation as discovery or a hand-built tool describes it. The keys after `input` are set only by the
    producers that know them: OpenAPI gives an example answer, a declared shape and a response schema; a hand-built
    tool gives a body; a pick from a source gains its executor; a function gains its settings."""

    name: str
    description: str
    access: Literal["read", "write"]
    method: str | None
    path: str | None
    group: str
    input: list[InputField]
    headers: list[Header]
    body: NotRequired[str | None]
    body_encoding: NotRequired[str | None]
    executor: NotRequired[str]
    requires_approval: NotRequired[bool | None]
    stub: NotRequired[JsonValue]
    output_shape: NotRequired[str | None]
    response_schema: NotRequired[Json | None]
    code: NotRequired[CodeSettings | None]


class Discovered(TypedDict):
    """A source as discovery read it, with each operation's headers and example kept for import."""

    type: str
    system: str
    suggestedName: str
    version: str
    endpoint: str
    operations: list[DiscoveredOperation]
    warnings: list[str]


class DiscoveredOpenApi(Discovered):
    """An OpenAPI document as discovery read it: whether none of its operations carries an auth header."""

    noAuth: bool


class PublicOperation(TypedDict):
    """A discovered operation as the console receives it: the call's headers and example stay on the service."""

    name: str
    description: str
    access: str
    method: str | None
    path: str | None
    group: str
    input: list[InputField]


class PublicDiscovered(TypedDict):
    noAuth: NotRequired[bool]
    type: str
    system: str
    suggestedName: str
    version: str
    endpoint: str
    operations: list[PublicOperation]
    warnings: list[str]
