"""/v1/agents/.../spec: an agent as one document (docs/design/agents-v2/agent-spec-file.md), read, saved, checked and
compared, one route per job. The document is mapped onto the stored agent version (ops_agents.domain.agent_spec), so
the console's editor keeps reading and saving the same version.

Every route that names an agent reads its row first, so another tenant's or a deleted agent answers 404 before the
body is looked at. A save asks tools-service, kb-service and models-service with nothing open, and is refused (503
`dependency_unavailable`) rather than saved unchecked when one cannot answer.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_agents.activities.agent_limits import check_limits, limits_of
from ops_agents.activities.knowledge import KnowledgeUnavailable
from ops_agents.activities.tool_directory import ToolsUnavailable
from ops_agents.app import agent_spec as checks
from ops_agents.app.agent_spec import HelperFacts, Versions
from ops_agents.domain import agent_spec as doc
from ops_service_kit.errors import Conflict, ServiceUnavailable, Unprocessable, ValidationFailed
from ops_service_kit.http import Envelope, Json, JsonList
from ops_service_kit.ids import now_iso

from ...store.agent_registry import AgentRow, digest_of, refuse_stale
from ..agent_registry import AgentSpec as StoredSpec
from ..agent_registry import registry
from ..agent_spec_schemas import SpecCheck, SpecDiff, SpecDiffIn, SpecIn, SpecSave, SpecView
from ..auth import Principal, caller, caller_in, reader_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..guardrails import guardrails, resolve_pins
from ..model_aliases import ModelsUnavailable, chat_aliases
from ..rights import rights
from ..skills import pin as pin_skill
from ..skills import skills
from ..widgets import published as published_widget
from .agents import changeable
from .tool_catalog import known_tools

router = APIRouter(prefix="/v1/agents", dependencies=[Depends(caller_in("agents"))])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Cl: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("agents"))]  # noqa: UP040


def _unavailable(what: str, exc: Exception) -> ServiceUnavailable:
    del exc
    return ServiceUnavailable(
        f"{what} cannot answer, so the spec cannot be checked; try again shortly.", code="dependency_unavailable"
    )


class RouteRecords:
    """`SpecRecords` from this service's registries and the other services, each asked at most once per check."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._tools: set[str] | None = None

    async def tools(self) -> set[str]:
        if self._tools is None:
            try:
                self._tools = {str(t["id"]) for t in await known_tools(self.rt, fresh=True)}
            except ToolsUnavailable as exc:
                raise _unavailable("The tools service", exc) from exc
        return self._tools

    async def knowledge_bases(self) -> set[str]:
        try:
            return {k.id for k in await self.rt.kbs().bases()}
        except KnowledgeUnavailable as exc:
            raise _unavailable("The knowledge service", exc) from exc

    async def skill(self, skill_id: str) -> Versions | None:
        reg = skills(self.rt)
        row = await reg.find(skill_id)
        if row is None:
            return None
        published = frozenset(int(v.version) for v in await reg.versions(skill_id) if v.published_at is not None)
        return Versions(published, row.published_version)

    async def guardrail(self, guardrail_id: str) -> Versions | None:
        reg = guardrails(self.rt)
        row = await reg.find(guardrail_id)
        if row is None:
            return None
        published = frozenset(int(v.version) for v in await reg.versions(guardrail_id) if v.published_at is not None)
        return Versions(published, row.published_version)

    async def agent(self, agent_id: str) -> HelperFacts | None:
        reg = registry(self.rt)
        row = await reg.find(agent_id)
        if row is None:
            return None
        served = row.published_version or row.version
        held = doc.exported((await reg.version(agent_id, served)).spec, agent_id).get("agents") or []
        helpers = frozenset(str(cast(Json, h)["id"]) for h in cast(JsonList, held))
        return HelperFacts(team_id=row.team_id, published=row.published_version is not None, helpers=helpers)

    async def aliases(self) -> set[str]:
        assert self.rt.model_aliases is not None
        try:
            return set(await chat_aliases(self.rt.model_aliases))
        except ModelsUnavailable as exc:
            raise _unavailable("The models service", exc) from exc


def _refuse(problems: list[doc.Problem]) -> Unprocessable:
    first = problems[0]
    more = f" and {len(problems) - 1} more" if len(problems) > 1 else ""
    return Unprocessable(
        f"The spec breaks a rule at {first.path or '/'}: {first.message}{more}",
        code="spec_invalid",
        details={"problems": cast(JsonList, [p.wire() for p in problems])},
    )


async def spec_problems(rt: Runtime, row: AgentRow, stored: Json) -> list[doc.Problem]:
    """What a stored version breaks of the spec's rules now: the publish asks this, since a helper, skill or tool the
    draft named when it was saved may have gone since."""
    exported = doc.exported(stored, row.id)
    found = await checks.check(exported, RouteRecords(rt), team_id=row.team_id, agent_id=row.id, aliases=False)
    return found.problems


async def _view(rt: Runtime, me: Principal, agent_id: str, version: int | None = None) -> SpecView:
    reg = registry(rt)
    row = await reg.row(agent_id)
    n = version if version is not None else row.version
    v = await reg.version(agent_id, n)
    flags = await rights(lambda action: changeable(rt, me, agent_id, action))
    return SpecView(
        agent_id=agent_id,
        version=n,
        digest=digest_of(v.spec),
        status="published" if v.published_at is not None else "draft",
        spec=doc.exported(v.spec, agent_id),
        can_edit=flags["canEdit"],
    )


@router.get("/{agent_id}/spec", response_model=Envelope[SpecView])
async def read_spec(
    rt: Rt, me: Reader, agent_id: str, version: Annotated[int | None, Query(ge=1)] = None
) -> JSONResponse:
    """The agent as a spec document: the newest version, or `version`. The CLI writes it as YAML."""
    return ok((await _view(rt, me, agent_id, version)).model_dump(by_alias=True))


@router.post("/spec/validate", response_model=Envelope[SpecCheck])
async def validate_spec(rt: Rt, me: Cl, body: SpecIn) -> JSONResponse:
    """Every rule a save checks, with nothing saved: `ok` and each problem with its JSON pointer. The team is the one
    the request acts in."""
    if not me.team_id:
        raise ValidationFailed("Choose a team with the X-Team-Id header.", code="team_required")
    found = await checks.check(body.spec, RouteRecords(rt), team_id=me.team_id, agent_id=None)
    return ok(
        {
            "ok": found.ok,
            "problems": [p.wire() for p in found.problems],
            "summary": doc.summary(found.spec) if found.spec is not None else None,
        }
    )


async def _stored_from(rt: Runtime, me: Principal, spec: doc.AgentSpec, raw: Json, held: Json) -> Json:
    """The version to store: the document mapped onto today's keys, with each skill, guardrail and widget it names
    snapshotted as the console's attach does."""
    at = now_iso()
    grants: Json = {"toolIds": list(spec.tool_ids or []), "collections": list(spec.collections or []), "skillPins": []}
    for s in spec.skills or []:
        ref = s if isinstance(s, doc.SkillRef) else doc.SkillRef(id=s)
        version = ref.version or (await skills(rt).row(ref.id)).published_version or 0
        pins = await pin_skill(rt, cast(StoredSpec, grants), ref.id, version, by=me.email, at=at, fresh=False)
        grants["skillPins"] = cast(JsonList, pins)
    skill_pins = cast(list[Json], grants["skillPins"])
    wanted: list[Json] = []
    for g in spec.guardrails or []:
        ref_g = g if isinstance(g, doc.GuardrailRef) else doc.GuardrailRef(id=g)
        wanted.append({"guardrailId": ref_g.id, "version": ref_g.version or 0, "enabled": ref_g.enabled})
    guardrail_pins = await resolve_pins(rt, wanted, cast(list[Json], held.get("guardrailPins") or []))
    widget_pins: list[Json] = []
    for w in spec.widgets.pins if spec.widgets is not None else []:
        found = await published_widget(rt, w.id, w.version)
        if found is None:
            raise Unprocessable(f"No published widget {w.id}.", code="unknown_widget")
        widget_pins.append(found.model_dump(by_alias=True, exclude={"sample"}))
    resolved = doc.Resolved(
        skill_pins=skill_pins, guardrail_pins=cast(list[Json], guardrail_pins), widget_pins=widget_pins
    )
    stored = doc.to_stored(spec, raw, resolved, kept=held)
    if "limits" in stored:
        check_limits(limits_of(stored), stored)
    return stored


@router.put("/{agent_id}/spec", response_model=Envelope[SpecView])
async def save_spec(rt: Rt, me: Cl, agent_id: str, body: SpecSave) -> JSONResponse:
    """Saves the document as the agent's draft. 422 `spec_invalid` naming each broken rule, 409 `stale_base` when
    `baseVersion` and `baseDigest` are not the newest copy, 503 `dependency_unavailable` when a lookup cannot answer;
    nothing is saved in any of them."""
    row = await changeable(rt, me, agent_id, "edit")
    if body.base_version is None or body.base_digest is None:
        raise ValidationFailed(
            "Name the copy the spec was made from: baseVersion and baseDigest.", code="base_required"
        )
    reg = registry(rt)
    newest = await reg.version(agent_id, row.version)
    base = (body.base_version, body.base_digest)
    refuse_stale(base, row.version, digest_of(newest.spec), saved_by=newest.saved_by, saved_at=newest.saved_at)
    found = await checks.check(body.spec, RouteRecords(rt), team_id=row.team_id, agent_id=agent_id)
    if found.problems or found.spec is None:
        raise _refuse(found.problems)
    stored = await _stored_from(rt, me, found.spec, body.spec, dict(newest.spec))
    # The store compares the base again under its row lock, so a save landing during the lookups is refused too.
    n = await reg.save(agent_id, stored, by=me.email, note=body.note or "", base=base)
    return ok((await _view(rt, me, agent_id, n)).model_dump(by_alias=True))


@router.post("/{agent_id}/spec/diff", response_model=Envelope[SpecDiff])
async def diff_spec(rt: Rt, _: Reader, agent_id: str, body: SpecDiffIn) -> JSONResponse:
    """What saving `spec` would change against the newest draft or the live version, as JSON pointer changes."""
    reg = registry(rt)
    row = await reg.row(agent_id)
    against: Literal["draft", "live"] = body.against
    n = row.version if against == "draft" else row.published_version
    if n is None:
        raise Conflict("This agent has never been published, so there is no live version.", code="not_published")
    spec, problems = doc.parse(body.spec)
    if spec is None:
        raise _refuse(problems)
    current = doc.exported((await reg.version(agent_id, n)).spec, agent_id)
    proposed = {"apiVersion": doc.API_VERSION, "id": agent_id, **doc.written(body.spec)}
    return ok({"against": against, "version": n, "changes": doc.diff(current, proposed)})
