"""Which agents cite each knowledge base, for kb-service's "used by" and for a person: a service
holding `agents:view`, or a person with agents.view in their team.

An agent cites the knowledge bases its published version names; one never published is counted on its newest version,
since it is what a builder testing it would see. `ids` names the bases asked about: kb-service names the bases on the
page it shows, and the store reads only the agents citing one of them (store/knowledge_citations.py); with no `ids`
every base the team's agents cite is listed. Only the agents of the team the token names are read (the team of the
person kb-service asks for): a base belongs to one team, and no team counts another's agents. The route reads only
this service's rows, so it answers in the request transaction (`Tx`).
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import CurrentTenantCaller
from ops_identity.fastapi import Tx
from ops_service_kit.http import Envelope, Out
from ops_service_kit.listing import IDS_MAX

from ...store.knowledge_citations import KnowledgeCitations
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
    # Deprecated: always 0, since no team counts another team's agents; removed in the next release.
    elsewhere: int


@router.get("", response_model=Envelope[list[KnowledgeUsage]])
async def knowledge_usage(
    rt: Rt,
    caller: CurrentTenantCaller,
    _: Tx,
    ids: Annotated[list[str] | None, Query(max_length=IDS_MAX)] = None,
) -> JSONResponse:
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "agents", "view", team=team, what="which agents cite a knowledge base")
    if caller.team_id is None:
        return ok([])
    asked = None if ids is None else set(ids)
    named: dict[str, list[AgentUsing]] = {}
    for cited in await KnowledgeCitations(rt.db).citing(caller.team_id, ids):
        for kb in cited.collections:
            if asked is None or kb in asked:
                named.setdefault(kb, []).append(AgentUsing(id=cited.agent_id, name=cited.name))
    rows = [KnowledgeUsage(kb_id=kb, agents=agents, elsewhere=0) for kb, agents in sorted(named.items())]
    return ok([r.model_dump(mode="json", by_alias=True) for r in rows])
