"""Which agents cite each knowledge base, for kb-service's "used by" (c-072 T007) and for a person (c-222): a service
holding `agents:view`, or a person with agents.view in their team.

An agent cites the knowledge bases its published version names; one never published is counted on its newest version,
since it is what a builder testing it would see. kb-service asks for every base at once and keeps nothing. Agents are
named only to the team the token names (the team of the person kb-service asks for, c-168); agents of other teams are
counted, never named, so a base another team relies on still reads as in use.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import CurrentTenantCaller
from ops_service_kit.http import Envelope, Out

from ...store.tenancy import set_tenant
from ..agent_registry import registry
from ..deps import Runtime, runtime
from ..envelope import ok

router = APIRouter(prefix="/v1/knowledge-usage")
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


class AgentUsing(Out):
    id: str
    name: str


class KnowledgeUsage(Out):
    kb_id: str
    agents: list[AgentUsing]
    # Agents of other teams citing the base: counted, not named.
    elsewhere: int


@router.get("", response_model=Envelope[list[KnowledgeUsage]])
async def knowledge_usage(rt: Rt, caller: CurrentTenantCaller) -> JSONResponse:
    set_tenant(caller.tenant_id)
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "agents", "view", team=team, what="which agents cite a knowledge base")
    team_id = caller.team_id
    reg = registry(rt)
    named: dict[str, list[dict[str, Any]]] = {}
    elsewhere: dict[str, int] = {}
    for row in await reg.rows():
        version = row["published_version"] or row["version"]
        spec: dict[str, Any] = (await reg.version(row["id"], version))["spec"]
        collections: list[Any] = spec.get("collections") or []
        for kb in dict.fromkeys(str(k) for k in collections):
            # No team named: nobody is named, every agent is counted.
            if team_id is not None and row["team_id"] == team_id:
                named.setdefault(kb, []).append({"id": row["id"], "name": spec.get("name") or row["slug"]})
            else:
                elsewhere[kb] = elsewhere.get(kb, 0) + 1
    kbs = sorted({*named, *elsewhere})
    return ok([{"kbId": kb, "agents": named.get(kb, []), "elsewhere": elsewhere.get(kb, 0)} for kb in kbs])
