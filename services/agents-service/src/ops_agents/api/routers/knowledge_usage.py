"""Which agents cite each knowledge base, for kb-service's "used by" (c-072 T007) and for a person (c-222): a service
holding `agents:view`, or a person with agents.view in their team.

An agent cites the knowledge bases its published version names; one never published is counted on its newest version,
since it is what a builder testing it would see. kb-service asks for every base at once and keeps nothing. Only the
agents of the team the token names are read (the team of the person kb-service asks for): a base belongs to one team,
and no team counts another's agents (c-507).
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import CurrentTenantCaller
from ops_service_kit.http import Envelope, Out

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
    # Deprecated (c-507): always 0, since no team counts another team's agents; removed in the next release.
    elsewhere: int


@router.get("", response_model=Envelope[list[KnowledgeUsage]])
async def knowledge_usage(rt: Rt, caller: CurrentTenantCaller) -> JSONResponse:
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "agents", "view", team=team, what="which agents cite a knowledge base")
    team_id = caller.team_id
    reg = registry(rt)
    named: dict[str, list[dict[str, Any]]] = {}
    for row in await reg.rows():
        if team_id is None or row["team_id"] != team_id:
            continue
        version = row["published_version"] or row["version"]
        spec: dict[str, Any] = (await reg.version(row["id"], version))["spec"]
        collections: list[Any] = spec.get("collections") or []
        for kb in dict.fromkeys(str(k) for k in collections):
            named.setdefault(kb, []).append({"id": row["id"], "name": spec.get("name") or row["slug"]})
    return ok([{"kbId": kb, "agents": agents, "elsewhere": 0} for kb, agents in sorted(named.items())])
