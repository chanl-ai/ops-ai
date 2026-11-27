"""Request and reply models of the agent spec routes (api/routers/agent_spec.py).

The document travels as a JSON object, not as the `AgentSpec` model: a body that failed the model would answer the
kit's 400 with Pydantic's locations, and the spec routes answer 422 `spec_invalid` with a JSON pointer per problem, so
the document is checked inside the route (ops_agents.domain.agent_spec.parse).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ops_service_kit.http import In, JsonValue, Out

Document = dict[str, JsonValue]


class SpecSave(In):
    spec: Document
    # Both required when the agent exists: a save made from an older copy is refused (409 `stale_base`).
    base_version: int | None = None
    base_digest: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class SpecIn(In):
    spec: Document


class SpecDiffIn(In):
    spec: Document
    against: Literal["draft", "live"] = "draft"


class SpecProblem(Out):
    path: str
    code: str
    message: str


class SpecSummary(Out):
    loop_kind: str
    tools: int
    helpers: int
    eval_cases: int


class SpecCheck(Out):
    ok: bool
    problems: list[SpecProblem]
    summary: SpecSummary | None = None


class SpecView(Out):
    agent_id: str
    version: int
    # SHA-256 of the stored version, the value a save names as `baseDigest` (the same digest GET /v1/agents/{id}
    # answers, so the console's editor and a spec save refuse each other's stale copies).
    digest: str
    status: Literal["draft", "published"]
    spec: Document
    can_edit: bool


class SpecChange(Out):
    op: Literal["add", "remove", "replace"]
    path: str
    before: JsonValue = None
    after: JsonValue = None


class SpecDiff(Out):
    against: Literal["draft", "live"]
    version: int
    changes: list[SpecChange]
