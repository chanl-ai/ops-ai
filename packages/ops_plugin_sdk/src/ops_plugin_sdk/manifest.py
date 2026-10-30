"""plugin.yaml, `ops-ai/plugin@2`: what a plugin brings, as data (the planning repo
docs/plans/ops-ai/plugin-contents-and-knowledge.html).

A plugin is a connection, settings, tools, knowledge sources over two of its tools, and templates. A tool is a request
template run by tools-service's http executor, or a Python function where data cannot describe the request. Unknown
fields are refused, so a misspelt key never means something other than its author wrote."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA = "ops-ai/plugin@2"
SDK_MAJOR = "1"
# The platform's sign-in kinds (tools-service auth/kinds.py, BY_ID); tools-service's tests keep the two equal.
SIGN_IN_KINDS = (
    "none",
    "api_key",
    "basic",
    "bearer",
    "oauth2_client_credentials",
    "oauth2_auth_code",
    "oauth2_jwt_bearer",
)
SIGN_IN_SETTINGS = ("team", "person", "person_or_team")
# The kinds that hold a person's own token, so each person may sign in (tools-service auth/kinds.py, per_person).
PER_PERSON_KINDS = ("oauth2_auth_code",)
# An operation's name in tools-service is `<plugin>_<tool>` and must match this (modules/schemas.py).
OPERATION_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
PLUGIN_ID = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")
KNOWLEDGE_ROLES = ("list_items", "get_item", "list_deleted")
# The formats a value written into a query can have, each checked and escaped by tools-service (formats.py).
FORMATS = ("soql_string", "sosl_term", "salesforce_id", "date-time", "date")
MAX_ITEMS = 50


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(Strict):
    id: str
    label: str
    required: bool = False


class HealthCheck(Strict):
    method: Literal["GET"] = "GET"
    path: str

    @field_validator("path")
    @classmethod
    def _rooted(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("a health-check path starts with /")
        return v


class ApiKey(Strict):
    """How the system takes its API key: in a header or a query parameter, under this name. The plugin says it, so a
    team admin gives only the key."""

    placement: Literal["header", "query"] = "header"
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")


class Connection(Strict):
    kinds: list[str] = Field(min_length=1)
    authorize_url: str | None = None
    token_url: str | None = None
    revoke_url: str | None = None
    scopes: list[Scope] = Field(default_factory=list[Scope])
    sign_in: list[Literal["team", "person", "person_or_team"]] = Field(min_length=1)
    # Settings read from the token answer at sign-in (Salesforce's instance_url), each must be a host ending in one of
    # `token_hosts`, so a token cannot point every call at a host outside the system.
    from_token: dict[str, str] = Field(default_factory=dict[str, str])
    token_hosts: list[str] = Field(default_factory=list[str])
    health_check: HealthCheck | None = None
    # Required when `kinds` lists api_key (validate.py).
    api_key: ApiKey | None = None


class Setting(Strict):
    type: Literal["string", "number", "integer", "boolean"] = "string"
    title: str = ""
    default: Any = None
    format: str | None = None
    # Filled from the token answer (Connection.from_token), never typed by a person.
    from_token: bool = False
    # The platform admin may fix its value for every team.
    lockable: bool = False
    # Stored as a secret reference and never shown back.
    secret: bool = False


class InputField(Strict):
    type: Literal["string", "number", "integer", "boolean", "object", "array"] = "string"
    description: str = ""
    required: bool = True
    # Sent when the caller leaves the input out, so an optional value still fills its place in a query.
    default: Any = None
    # A value is checked against each of these that is set, wherever it is used.
    enum: list[str | int | float | bool] | None = None
    format: Literal["soql_string", "sosl_term", "salesforce_id", "date-time", "date"] | None = None
    # For a path segment only: a pattern cannot keep a value from changing a query (validate.py).
    pattern: str | None = None
    properties: dict[str, InputField] | None = None
    items: InputField | None = None
    max_items: int = MAX_ITEMS


class Paging(Strict):
    """How a listing tool reaches its next page. `link`: the answer field holding the next page's address. `token`: the
    answer field holding a value sent back as `param`. `offset`: `limit` items a page, read from the answer's `items`
    list, with the offset and limit sent as `offset_param` and `limit_param`; a short page is the last."""

    rule: Literal["link", "token", "offset"]
    next: str | None = None
    param: str | None = None
    limit: int | None = Field(default=None, ge=1, le=2000)
    items: str | None = None
    offset_param: str = "offset"
    limit_param: str = "limit"


class Request(Strict):
    method: Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
    path: str
    # A JSON body template; `{{arg}}` is the argument as JSON.
    body: str | None = None
    # Query parameters as templates over the inputs; each `{{arg}}` is the value checked and escaped by its format.
    query: dict[str, str] = Field(default_factory=dict[str, str])
    paging: Paging | None = None

    @field_validator("path")
    @classmethod
    def _rooted(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("a request path starts with /")
        return v


class Tool(Strict):
    name: str
    # What people see in place of the name: the tools list, the grant picker and the approval card.
    title: str = Field(default="", max_length=60)
    description: str = ""
    access: Literal["read", "write"]
    input: dict[str, InputField] = Field(default_factory=dict[str, InputField])
    request: Request | None = None
    # A Jinja2 template over the answer (`data`) and the merged settings (`settings`).
    transform: str | None = None
    # `module:function` for a tool data cannot describe.
    function: str | None = None
    knowledge: Literal["list_items", "get_item", "list_deleted"] | None = None
    rate_limit_per_min: int = Field(default=60, ge=1, le=10_000)
    # A write waits for a person's approval unless the plugin says it need not.
    requires_approval: bool | None = None
    needs_person: bool = False
    scopes: list[str] = Field(default_factory=list[str])

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not TOOL_NAME.match(v):
            raise ValueError("a tool name is lower-case letters, digits and underscores, starting with a letter")
        return v

    @model_validator(mode="after")
    def _one_implementation(self) -> Tool:
        if (self.request is None) == (self.function is None):
            raise ValueError(f"tool {self.name} needs exactly one of request or function")
        if self.function is not None and ":" not in self.function:
            raise ValueError(f"tool {self.name}: function is module:name")
        return self

    @property
    def waits(self) -> bool:
        """Whether a call waits for approval: a write does unless the plugin set requires_approval false."""
        return self.access == "write" if self.requires_approval is None else self.requires_approval


class Schedule(Strict):
    kind: Literal["manual", "daily", "weekly"] = "manual"
    time: str | None = None


class KnowledgeSource(Strict):
    name: str
    title: str
    list: str
    get: str
    deleted: str | None = None
    schedule: Schedule = Field(default_factory=Schedule)


class Requires(Strict):
    tools: list[str] = Field(default_factory=list[str])
    bind: list[dict[str, str]] = Field(default_factory=list[dict[str, str]])


class Template(Strict):
    kind: Literal["agent", "skill", "workflow", "document_type"]
    id: str
    version: int = Field(ge=1)
    path: str
    requires: Requires = Field(default_factory=Requires)


class Display(Strict):
    """What the console's Connections card shows for the plugin's system (c-580): a logo, a category, one line of
    what it is, and where an admin reads how to set up its app or get its key."""

    logo: str | None = None
    category: str | None = None
    description: str | None = None
    docs_url: str | None = None


class Manifest(Strict):
    schema_: Literal["ops-ai/plugin@2"] = Field(alias="schema")
    id: str
    title: str
    version: str
    sdk: str
    connection: Connection
    settings: dict[str, Setting] = Field(default_factory=dict[str, Setting])
    egress: list[str] = Field(min_length=1)
    endpoint: str
    tools: list[Tool] = Field(min_length=1)
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list[KnowledgeSource])
    templates: list[Template] = Field(default_factory=list[Template])
    display: Display = Field(default_factory=Display)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not PLUGIN_ID.match(v):
            raise ValueError("a plugin id is <publisher>.<name>, lower-case")
        return v

    @property
    def short(self) -> str:
        """The name part of the id, which prefixes every operation: opsai.salesforce gives salesforce."""
        return self.id.split(".", 1)[1].replace("-", "_")

    def operation(self, tool: str) -> str:
        return f"{self.short}_{tool}"

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)


class ManifestError(ValueError):
    """plugin.yaml does not parse as `ops-ai/plugin@2`; `problems` names each field."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        super().__init__(f"{path}: " + "; ".join(problems))
        self.path = path
        self.problems = problems


def read(path: Path) -> Manifest:
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ManifestError(path, [f"cannot read: {e}"]) from e
    try:
        return Manifest.model_validate(raw)
    except ValidationError as e:
        raise ManifestError(
            path, [f"{'.'.join(str(p) for p in err['loc']) or 'manifest'}: {err['msg']}" for err in e.errors()]
        ) from e
