"""`/v1/secrets`: create, rotate, delete and list tool secrets. A value goes in and never comes out: responses
carry a secret's name, version and times only. A secret belongs to one team (c-509): every route reads and writes the
acting team's secrets, or with `teamId` another team's, which only the Security team's admins may name. Two teams that
need the same credential each hold their own row under the same name."""

# No `from __future__ import annotations`: the `caller` dependency is a local of secrets_router, and FastAPI resolves
# string annotations against module globals, where it does not exist.

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import Access, policy, require_provisioner
from ops_identity import Principal
from ops_policy import Cipher, context_of
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, ListResult, Out, error_responses, ok, page_window, paged
from ops_service_kit.settings import Settings
from ops_store.team_scope import acting_as

from ..callers import Person, person
from ..executor import secret_names
from ..store.modules import ModuleStore
from ..store.secrets import SecretStore


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


Team = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
# Another team whose secrets a Security admin reads or writes (`_team` in secrets_router).
TeamQuery = Annotated[str | None, Query(alias="teamId", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


class SecretIn(_In):
    # A new name is upper snake case up to 64 characters, the rule files-service's storage credentials share (c-093);
    # a secret created under the older 120-character cap keeps its name and stays usable and editable.
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)
    value: str = Field(min_length=1, max_length=8192)
    # The team it belongs to; the acting team when left out. Another team needs a Security admin (`_team`).
    team_id: Team | None = None
    # Refused when sent (`secret_one_team`): a secret limited to several teams is one row per team now (c-509).
    teams: list[Team] | None = Field(default=None, deprecated=True)
    # Set only by the provisioner (c-180): the template slot the secret fills, and `system` to keep the slot from
    # people. A Security admin still rotates a system secret's value; that is not an edit of the slot.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class RotateIn(_In):
    value: str = Field(min_length=1, max_length=8192)


class SecretUser(Out):
    module_id: str
    module_name: str
    operation: str
    # Only an unpublished edit names it; the published operation does not yet.
    staged: bool


class SecretMeta(Out):
    name: str
    version: int
    created_by: str
    created_at: str
    rotated_at: str | None = None
    last_used_at: str | None = None
    used_by: list[SecretUser] = Field(default_factory=list[SecretUser])
    # The team whose modules and connections read it.
    team_id: str
    teams: list[str] | None = Field(default=None, deprecated=True)
    template_id: str | None = None
    protection: Literal["system", "managed"] | None = None
    # The connection this secret is a part of (c-330): it is set, replaced and removed on the connection, never here.
    connection_id: str | None = None


class SecretList(ListResult[SecretMeta]):
    """GET /v1/secrets?page=: one page of the secrets' metadata."""


def _refs(op: dict[str, Any]) -> set[str]:
    return set(secret_names(op))


def users_of(modules: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Each secret name and the operations that read it: what calls run now (the published operations, or the baseline
    while edits are staged) and what a staged edit would run, so neither a delete nor a publish breaks one."""
    out: dict[str, list[dict[str, Any]]] = {}
    for m in modules:
        ops: list[dict[str, Any]] = m["operations"]
        baseline: list[dict[str, Any]] = m.get("baseline") or []
        published = {str(o["id"]): _refs(o) for o in (baseline or ops)}
        current: dict[str, set[str]] = {str(o["id"]): _refs(o) for o in ops}
        names: dict[str, str] = {str(o["id"]): str(o["name"]) for o in [*baseline, *ops]}
        for op_id in sorted({*published, *current}, key=lambda i: names[i]):
            empty: set[str] = set()
            now = current.get(op_id, empty)
            served = published.get(op_id, empty)
            for secret in sorted(now | served):
                user: dict[str, Any] = {
                    "moduleId": str(m["id"]),
                    "moduleName": str(m["display_name"]),
                    "operation": names[op_id],
                    "staged": secret not in served,
                }
                out.setdefault(secret, []).append(user)
    return out


def _meta(row: dict[str, Any], users: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    out = {
        "name": row["name"],
        "version": row["version"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"].isoformat(),
        "usedBy": (users or {}).get(row["name"], []),
        "teamId": row["team_id"],
        "teams": [row["team_id"]],
        "templateId": row.get("template_id"),
        "protection": row.get("protection"),
        "connectionId": row.get("connection_id"),
    }
    for key, col in (("rotatedAt", "rotated_at"), ("lastUsedAt", "last_used_at")):
        if row.get(col):
            out[key] = row[col].isoformat()
    return out


def may_write_secret(
    p: Principal, action: str, owner: str, *, security_team: str, protection: str | None = None
) -> None:
    """Who may add, change or remove a secret (c-186), or Forbidden. The Security team's admins (`manage`) write any.
    A team's secret is that team's: its builders write it, acting in that team, unless the tenant's
    `securityTeamAddsSecrets` policy keeps writes in the Security team. A `system` secret's slot is the provisioner's
    (c-180)."""
    access = Access(security_team=security_team)
    if access.may(p, "secrets_egress", "manage", protection=protection):
        return
    security_writes = bool(policy(p, "securityTeamAddsSecrets"))
    access.can(
        p,
        "secrets_egress",
        action,
        team=security_team if security_writes else owner,
        from_any_team=security_writes,
        what=f"a secret of {owner}",
        code="not_security_admin",
        protection=protection,
    )


def secrets_router(
    store: SecretStore, cipher: Cipher, *, security_team: str | None = None, modules: ModuleStore | None = None
) -> APIRouter:
    """`modules` lists the tenant's tool modules, for which operations read each secret; without it none are named."""
    caller = person
    team = security_team or Settings().security_team_id

    r = APIRouter(prefix="/v1/secrets", tags=["secrets"], responses=error_responses())

    def _team(who: Person, requested: str | None) -> str:
        """The team whose secrets the request reads or writes: the acting team, or `requested`. Another team's secrets
        are named only by the Security team's admins, who add secrets for every team (D34, `securityTeamAddsSecrets`);
        for anyone else another team's secrets do not exist. A token acting in no team names one."""
        if requested is None or requested == who.team_id:
            if who.team_id is None:
                raise ValidationFailed("Name the team whose secrets these are (teamId).", code="team_required")
            return who.team_id
        if who.principal is not None and not Access(security_team=team).may(who.principal, "secrets_egress", "manage"):
            raise NotFound(f"Team {requested}")
        return requested

    async def _users(tenant_id: str, owner: str) -> dict[str, list[dict[str, Any]]]:
        if modules is None:
            return {}
        # The operations of the secret's own team, the only modules that read it.
        with acting_as(owner):
            return users_of(await modules.secret_readers(tenant_id))

    async def _row(who: Person, owner: str, name: str) -> dict[str, Any]:
        row = next((x for x in await store.listed(who.tenant_id, owner) if x["name"] == name), None)
        if row is None:
            raise NotFound(f"Secret {name}")
        return row

    async def _one(who: Person, owner: str, name: str) -> dict[str, Any]:
        return _meta(await _row(who, owner, name), await _users(who.tenant_id, owner))

    def _not_a_connection_part(row: dict[str, Any]) -> None:
        """A connection's secret part changes with the connection, which knows which environment and field it fills."""
        if row.get("connection_id"):
            raise Conflict(
                f"{row['name']} belongs to a connection. Replace or remove it on that connection.",
                code="connection_secret",
                details={"connectionId": row["connection_id"]},
            )

    def _may_write(who: Person, action: str, owner: str, protection: str | None = None) -> None:
        if who.principal is not None:
            may_write_secret(who.principal, action, owner, security_team=team, protection=protection)

    @r.get("", response_model=Envelope[list[SecretMeta] | SecretList])
    async def list_secrets(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Person, Depends(caller)],
        *,
        page: Annotated[int | None, Query(ge=1)] = None,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
        search: str = "",
        template_id: Annotated[str | None, Query(alias="templateId")] = None,
        team_id: TeamQuery = None,
    ) -> JSONResponse:
        """The team's secrets' metadata, as scripts and earlier callers read it; with `page`, one page of those whose
        name matches `search`, as the Secrets list reads it. The page and its count are queried, not sliced."""
        owner = _team(who, team_id)
        users = await _users(who.tenant_id, owner)
        if page is None:
            listed = await store.listed(who.tenant_id, owner)
            return ok([_meta(x, users) for x in listed if template_id is None or x.get("template_id") == template_id])
        total = await store.count(who.tenant_id, owner, search, template_id)
        page, offset = page_window(total, page, page_size)
        found = await store.page(who.tenant_id, owner, search, offset=offset, limit=page_size, template_id=template_id)
        return ok(paged([_meta(x, users) for x in found], total, page, page_size))

    @r.post("", response_model=Envelope[SecretMeta], status_code=201)
    async def create_secret(body: SecretIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if "teams" in body.model_fields_set:
            raise ValidationFailed(
                "A secret belongs to one team: name it with teamId, and add it in each team that needs it under the "
                "same name.",
                code="secret_one_team",
            )
        owner = _team(who, body.team_id)
        _may_write(who, "create", owner)
        template = {k: v for k, v in (("template_id", body.template_id), ("protection", body.protection)) if v}
        if template and who.principal is not None:
            require_provisioner(who.principal, "secrets_egress")
        blob = cipher.encrypt(body.value, context=context_of(who.tenant_id, body.name))
        made = await store.create(
            who.tenant_id, owner, body.name, blob, actor=who.name, at=datetime.now(UTC), template=template
        )
        if not made:
            raise Conflict(f"A secret named {body.name} already exists. Rotate it to change its value.")
        return ok(await _one(who, owner, body.name), 201)

    @r.post("/{name}/rotate", response_model=Envelope[SecretMeta])
    async def rotate_secret(  # pyright: ignore[reportUnusedFunction]
        name: str, body: RotateIn, who: Annotated[Person, Depends(caller)], team_id: TeamQuery = None
    ) -> JSONResponse:
        # Setting the value is not an edit of the slot, so a system secret's protection does not apply (c-180).
        owner = _team(who, team_id)
        row = await _row(who, owner, name)
        _not_a_connection_part(row)
        _may_write(who, "edit", owner)
        blob = cipher.encrypt(body.value, context=context_of(who.tenant_id, name))
        if await store.rotate(who.tenant_id, owner, name, blob, actor=who.name, at=datetime.now(UTC)) is None:
            raise NotFound(f"Secret {name}")
        return ok(await _one(who, owner, name))

    @r.delete("/{name}", status_code=204, response_class=Response)
    async def delete_secret(  # pyright: ignore[reportUnusedFunction]
        name: str, who: Annotated[Person, Depends(caller)], team_id: TeamQuery = None
    ) -> Response:
        owner = _team(who, team_id)
        row = await _row(who, owner, name)
        _not_a_connection_part(row)
        _may_write(who, "delete", owner, row.get("protection"))
        # A secret an operation names, staged or published, is not deleted: the next call would fail SECRET_MISSING.
        if users := (await _users(who.tenant_id, owner)).get(name):
            ops = ", ".join(u["operation"] for u in users)
            raise Conflict(
                f"{name} is read by {ops}. Remove it from those operations first.",
                code="secret_in_use",
                details={"operations": [u["operation"] for u in users]},
            )
        if not await store.delete(who.tenant_id, owner, name, actor=who.name, at=datetime.now(UTC)):
            raise NotFound(f"Secret {name}")
        return Response(status_code=204)

    return r
