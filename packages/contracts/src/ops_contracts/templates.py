"""The shapes services send each other about a plugin's templates and a team's copies of them.

tools-service answers each template with what it requires; agents-service and documents-service read that, keep the
copies and answer each template with its requirements, what the team has installed and the team's copy; tools-service
reads those lists back into an app's resources. Each service builds and reads these shapes through the classes here,
so a field one side adds is a field the other side knows.

A class here is a `ServiceShape`: scripts/tests/test_no_cross_service_imports.py holds every service's committed
OpenAPI document to it, and fails on a document that describes the shape differently or under another name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from .chat import WireModel


class ServiceShape(WireModel):
    """A shape one service sends and another reads. Every field is sent, defaulted ones too: dump it with
    `model_dump(by_alias=True)`, never `wire()`, which drops a None. Its schema therefore lists each field as required
    and a reader finds it present."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


# Every kind of resource a plugin brings. A service that keeps copies answers only its own kinds.
ResourceKind = Literal[
    "agent", "skill", "workflow", "document_type", "case_type", "task_type", "guardrail", "knowledge_source"
]


class CopyRef(ServiceShape):
    """A team's copy of a template: where it came from and the record it made."""

    id: str
    kind: ResourceKind
    record_id: str
    source: str
    template_id: str
    version: int
    # Set once the team detached the copy: it is the team's own and takes no updates.
    detached_at: str | None = None


class TemplateRequires(ServiceShape):
    """What a copy of a template needs before it can run."""

    # The operations the team's plugin module serves, `<plugin short name>_<tool>`.
    tools: list[str]
    # What the person names at install: `{"knowledge_base": "<what it is>"}` or `{"model_alias": "<capability>"}`.
    bind: list[dict[str, str]]
    # The plugin's other resources a copy cannot run without, each `<source>:<template id>` as the copy route names it.
    resources: list[str] = Field(default_factory=list[str])


class Installed(ServiceShape):
    """The live copies a team holds of one template. A copy never changes by itself."""

    copies: int
    # The newest version among the copies; None when the team holds none.
    version: int | None
    # The source ships a newer version than the newest copy.
    newer_available: bool
    # The newest live copy was made from a body other than the template's current one (its digest differs).
    changed: bool = False
