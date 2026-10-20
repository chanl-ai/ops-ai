"""Shape lookups never fail a save (c-353), by failure mode: documents-service refusing (403 team_required, a type
another team owns) or tools-service out of reach turns a workflow save into a 500, where the shape should stay open;
a lookup with no team asks documents-service anyway and is refused."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.api.step_shapes import ServiceLookups
from ops_agents.store.tenancy import tenant_scope
from ops_documents_client import DocumentsRefused
from ops_identity import ServiceUnreachable


class RefusingDocuments:
    def __init__(self) -> None:
        self.asked = 0

    async def document_type(self, tenant: str, team: str, type_id: str) -> dict[str, Any]:
        self.asked += 1
        raise DocumentsRefused(403, "team_required", "A service token on this route names its team.")


class DownTools:
    async def tool_policy(self, tool: str) -> dict[str, Any]:
        raise ServiceUnreachable("tools-service did not answer")


async def test_a_refused_document_type_and_an_unreachable_tool_leave_their_shapes_open() -> None:
    docs = RefusingDocuments()
    lookups = ServiceLookups(SimpleNamespace(tools=DownTools()), "team_ops", docs)  # type: ignore[arg-type]
    with tenant_scope("acme"):
        assert await lookups.document_fields("levy", None) == [] and docs.asked == 1
        assert await lookups.operation_output("get_customer") is None


async def test_with_no_team_documents_service_is_not_asked() -> None:
    docs = RefusingDocuments()
    lookups = ServiceLookups(SimpleNamespace(tools=None), "", docs)  # type: ignore[arg-type]
    with tenant_scope("acme"):
        assert await lookups.document_fields("levy", None) == [] and docs.asked == 0
