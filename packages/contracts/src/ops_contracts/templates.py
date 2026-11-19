"""The shapes services send each other about a plugin's templates and a team's copies of them.

agents-service and documents-service keep the copies and answer each in their template lists and copy routes;
tools-service reads those lists and answers the same copy in an app's resources. Each service builds and reads the
shape through the class here, so a field one side adds is a field the other side knows.

A class here is a `ServiceShape`: scripts/tests/test_no_cross_service_imports.py holds every service's committed
OpenAPI document to it, and fails on a document that describes the shape differently or under another name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

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
