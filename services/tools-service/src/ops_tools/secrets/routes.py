"""`/v1/secrets`: create, rotate, delete and list tool secrets. A value goes in and never comes out: responses
carry a secret's name, version and times only. A secret belongs to one team: every route reads and writes the
acting team's secrets, or with `teamId` another team's, which only the Security team's admins may name. Two teams that
need the same credential each hold their own row under the same name."""

# No `from __future__ import annotations`: the `caller` dependency is a local of secrets_router, and FastAPI resolves
# string annotations against module globals, where it does not exist.

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypedDict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import Access, policy, reader_of, require_provisioner
from ops_identity import Principal
from ops_identity.fastapi import Tx
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, In, ListResult, Out, error_responses, ok
from ops_service_kit.listing import ListQuery
from ops_store import isolation
from ops_store.team_scope import acting_as

from ..callers import Person, person
from ..executor import secret_refs
from ..store.connections import ConnectionStore
from ..store.modules import ModuleStore, PublishedOperation, SecretOperation, SecretReader
from ..store.secrets import SecretMeta as StoredSecret
from . import SecretResolver

Team = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
# Another team whose secrets a Security admin reads or writes (`_team` in secrets_router).
TeamQuery = Annotated[str | None, Query(alias="teamId", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


class SecretIn(In):
    # A new name is upper snake case up to 64 characters, the rule files-service's storage credentials share;
    # a secret created under the older 120-character cap keeps its name and stays usable and editable.
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)
    value: str = Field(min_length=1, max_length=8192)
    # The team it belongs to; the acting team when left out. Another team needs a Security admin (`_team`).
    team_id: Team | None = None
    # Refused when sent (`secret_one_team`): a secret limited to several teams is one row per team now.
    teams: list[Team] | None = Field(default=None, deprecated=True)
    # Set only by the provisioner: the template slot the secret fills, and `system` to keep the slot from
    # people. A Security admin still rotates a system secret's value; that is not an edit of the slot.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class RotateIn(In):
    value: str = Field(min_length=1, max_length=8192)


class RenameIn(In):
    # The same rule as a new secret's name.
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)


class SecretUser(Out):
    module_id: str
    module_name: str
    operation: str
    # Only an unpublished edit names it; the published operation does not yet.
    staged: bool


class SecretMeta(Out):
    name: str
    version: int
    # The value's last four characters, so a person can tell which value is held; none for a short value.
    ends: str | None = None
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
    # The connection this secret is a part of: it is set, replaced and removed on the connection, never here.
    connection_id: str | None = None
    # The app credential whose client secret this is: it is replaced under Credentials, never here.
    credential_id: str | None = None
    # The auth config this is the client secret of, `{id, name}`: listed here read only and changed on that config.
    auth_config: dict[str, str] | None = None
    # Whether this list may change it: false for an auth config's client secret.
    read_only: bool = False
    # What a person calls it ("GitHub · Operations client secret") when an auth config holds it; none for a team's own
    # secret, whose name is the one headers use and people know it by.
    label: str | None = None


class SecretList(ListResult[SecretMeta]):
    """GET /v1/secrets: one page of the secrets' metadata."""


class SecretUse(TypedDict):
    """One operation that reads a secret, as the secret's page lists it."""

    moduleId: str
    moduleName: str
    operation: str
    staged: bool


def _refs(op: SecretOperation | PublishedOperation) -> set[str]:
    return set(secret_refs(op.get("headers") or [], op.get("path")))


def users_of(modules: list[SecretReader]) -> dict[str, list[SecretUse]]:
    """Each secret name and the operations that read it: what calls run now (the published operations, or the baseline
    while edits are staged) and what a staged edit would run, so neither a delete nor a publish breaks one."""
    out: dict[str, list[SecretUse]] = {}
    for m in modules:
        ops = m["operations"]
        baseline = m["baseline"] or []
        published = {str(o.get("id")): _refs(o) for o in (baseline or ops)}
        current: dict[str, set[str]] = {o["id"]: _refs(o) for o in ops}
        names: dict[str, str] = {str(o.get("id")): str(o.get("name")) for o in [*baseline, *ops]}
        for op_id in sorted({*published, *current}, key=lambda i: names[i]):
            empty: set[str] = set()
            now = current.get(op_id, empty)
            served = published.get(op_id, empty)
            for secret in sorted(now | served):
                user: SecretUse = {
                    "moduleId": str(m["id"]),
                    "moduleName": str(m["display_name"]),
                    "operation": names[op_id],
                    "staged": secret not in served,
                }
                out.setdefault(secret, []).append(user)
    return out


def _meta(
    row: StoredSecret, users: dict[str, list[SecretUse]] | None = None, configs: dict[str, str] | None = None
) -> dict[str, Any]:
    config = row.credential_id
    config_name = (configs or {}).get(config, config) if config else None
    out = {
        "name": row.name,
        "version": row.version,
        "ends": row.ends,
        "createdBy": row.created_by,
        "createdAt": row.created_at.isoformat(),
        "usedBy": (users or {}).get(row.name, []),
        "teamId": row.team_id,
        "teams": [row.team_id],
        "templateId": row.template_id,
        "protection": row.protection,
        "connectionId": row.connection_id,
        "credentialId": config,
        "authConfig": {"id": config, "name": config_name} if config_name else None,
        "readOnly": bool(config or row.connection_id),
        "label": f"{config_name} client secret" if config_name else None,
    }
    for key, at in (("rotatedAt", row.rotated_at), ("lastUsedAt", row.last_used_at)):
        if at:
            out[key] = at.isoformat()
    return out


def may_write_secret(p: Principal, action: str, owner: str, *, protection: str | None = None) -> None:
    """Who may add, change or remove a secret, or Forbidden. The Security team's admins (`manage`) write any.
    A team's secret is that team's: its builders write it, acting in that team, unless the tenant's
    `securityTeamAddsSecrets` policy keeps writes in the Security team. A `system` secret's slot is the
    provisioner's."""
    access = Access()
    if access.may(p, "secrets_egress", "manage", protection=protection):
        return
    security_writes = bool(policy(p, "securityTeamAddsSecrets"))
    access.can(
        p,
        "secrets_egress",
        action,
        team=access.security_team_of(p) if security_writes else owner,
        from_any_team=security_writes,
        what="this team's secrets" if owner == p.team_id else "another team's secrets",
        code="not_security_admin",
        protection=protection,
    )


def secrets_router(
    secrets: SecretResolver,
    *,
    modules: ModuleStore | None = None,
    credentials: ConnectionStore | None = None,
) -> APIRouter:
    """`secrets` sets values through the credential store and reads the metadata of its store. `modules` lists the
    tenant's tool modules, for which operations read each secret; without it none are named. `credentials` names the
    auth config each client secret belongs to; without it a config is named by its id."""
    store = secrets.store
    caller = person

    r = APIRouter(prefix="/v1/secrets", tags=["secrets"], responses=error_responses())

    def _team(who: Person, requested: str | None) -> str:
        """The team whose secrets the request reads or writes: the acting team, or `requested`. Another team's secrets
        are named only by the Security team's admins, who add secrets for every team (D34, `securityTeamAddsSecrets`);
        for anyone else another team's secrets do not exist. A token acting in no team names one."""
        if requested is None or requested == who.team_id:
            if who.team_id is None:
                raise ValidationFailed("Name the team whose secrets these are (teamId).", code="team_required")
            return who.team_id
        if who.principal is not None and not Access().may(who.principal, "secrets_egress", "manage"):
            raise NotFound(f"Team {requested}")
        return requested

    async def _users(tenant_id: str, owner: str) -> dict[str, list[SecretUse]]:
        if modules is None:
            return {}
        # The operations of the secret's own team, the only modules that read it.
        with acting_as(owner):
            return users_of(await modules.secret_readers(tenant_id))

    async def _row(who: Person, owner: str, name: str) -> StoredSecret:
        row = await store.meta(who.tenant_id, owner, name)
        if row is None:
            raise NotFound(f"Secret {name}")
        return row

    async def _configs(tenant_id: str, owner: str) -> dict[str, str]:
        """The team's auth configs, id to name, so a client secret names the config it is changed on."""
        if credentials is None:
            return {}
        return {
            str(c["id"]): str(c.get("name") or c["id"]) for c in await credentials.team_credentials(tenant_id, owner)
        }

    async def _one(who: Person, owner: str, name: str) -> dict[str, Any]:
        configs = await _configs(who.tenant_id, owner)
        return _meta(await _row(who, owner, name), await _users(who.tenant_id, owner), configs)

    async def _not_a_connection_part(who: Person, owner: str, row: StoredSecret) -> None:
        """A connection's secret part changes with the connection, which knows which environment and field it fills."""
        if row.connection_id:
            raise Conflict(
                f"{row.name} belongs to a connection. Replace or remove it on that connection.",
                code="connection_secret",
                details={"connectionId": row.connection_id},
            )
        if row.credential_id:
            config = (await _configs(who.tenant_id, owner)).get(row.credential_id, row.credential_id)
            raise Conflict(
                f"{row.name} is the client secret of the auth config {config}. Change it on that auth config.",
                code="credential_secret",
                details={"credentialId": row.credential_id, "authConfig": config},
            )

    @contextmanager
    def _in(who: Person, owner: str) -> Generator[None]:
        """The request's transactions in `owner`'s team: the acting team, or the team a Security admin named, after
        `_team` checked that right. The database shows a transaction its own team's secrets only."""
        if owner == who.team_id:
            yield
            return
        with isolation.scope(who.tenant_id, owner):
            yield

    def _may_write(who: Person, action: str, owner: str, protection: str | None = None) -> None:
        if who.principal is not None:
            may_write_secret(who.principal, action, owner, protection=protection)

    @r.get("", response_model=Envelope[SecretList], dependencies=[Depends(reader_of("secrets_egress"))])
    async def list_secrets(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Person, Depends(caller)], _: Tx, q: ListQuery, team_id: TeamQuery = None
    ) -> JSONResponse:
        """One page of the team's secrets' metadata on the shared list contract, by name: `search` matches the name,
        `ids` names secrets, and the filter `templateId` keeps those filling a template slot. Pickers search or name
        what they need rather than loading every secret. The page and its count are queried, not sliced."""
        owner = _team(who, team_id)
        with _in(who, owner):
            users = await _users(who.tenant_id, owner)
            page, found = await store.page(who.tenant_id, owner, q)
            configs = await _configs(who.tenant_id, owner)
            return ok({**page, "data": [_meta(x, users, configs) for x in found]})

    @r.post("", response_model=Envelope[SecretMeta], status_code=201)
    async def create_secret(body: SecretIn, who: Annotated[Person, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if "teams" in body.model_fields_set:
            raise ValidationFailed(
                "A secret belongs to one team: name it with teamId, and add it in each team that needs it under the "
                "same name.",
                code="secret_one_team",
            )
        owner = _team(who, body.team_id)
        with _in(who, owner):
            _may_write(who, "create", owner)
            template = {k: v for k, v in (("template_id", body.template_id), ("protection", body.protection)) if v}
            if template and who.principal is not None:
                require_provisioner(who.principal, "secrets_egress")
            made = await secrets.create(
                who.tenant_id, owner, body.name, body.value, actor=who.name, at=datetime.now(UTC), template=template
            )
            if not made:
                raise Conflict(f"A secret named {body.name} already exists. Rotate it to change its value.")
            return ok(await _one(who, owner, body.name), 201)

    @r.post("/{name}/rotate", response_model=Envelope[SecretMeta])
    async def rotate_secret(  # pyright: ignore[reportUnusedFunction]
        name: str, body: RotateIn, who: Annotated[Person, Depends(caller)], _: Tx, team_id: TeamQuery = None
    ) -> JSONResponse:
        # Setting the value is not an edit of the slot, so a system secret's protection does not apply.
        owner = _team(who, team_id)
        with _in(who, owner):
            row = await _row(who, owner, name)
            await _not_a_connection_part(who, owner, row)
            _may_write(who, "edit", owner)
            if (
                await secrets.rotate(who.tenant_id, owner, name, body.value, actor=who.name, at=datetime.now(UTC))
                is None
            ):
                raise NotFound(f"Secret {name}")
            return ok(await _one(who, owner, name))

    @r.post("/{name}/rename", response_model=Envelope[SecretMeta])
    async def rename_secret(  # pyright: ignore[reportUnusedFunction]
        name: str, body: RenameIn, who: Annotated[Person, Depends(caller)], _: Tx, team_id: TeamQuery = None
    ) -> JSONResponse:
        """A new name, the value kept. Operations name a secret by `{{name}}`, so one an operation reads is not
        renamed: the answer names those operations, as a delete does."""
        owner = _team(who, team_id)
        with _in(who, owner):
            row = await _row(who, owner, name)
            await _not_a_connection_part(who, owner, row)
            _may_write(who, "edit", owner, row.protection)
            if users := (await _users(who.tenant_id, owner)).get(name):
                ops = ", ".join(u["operation"] for u in users)
                raise Conflict(
                    f"{name} is read by {ops}, which name it. Remove it from those operations first, or add a new "
                    "secret under the new name.",
                    code="secret_in_use",
                    details={"operations": [u["operation"] for u in users]},
                )
            moved = await secrets.rename(who.tenant_id, owner, name, body.name, actor=who.name, at=datetime.now(UTC))
            if moved is False:
                raise Conflict(f"A secret named {body.name} already exists. Pick another name.")
            if moved is None:
                raise NotFound(f"Secret {name}")
            return ok(await _one(who, owner, body.name))

    @r.delete("/{name}", status_code=204, response_class=Response)
    async def delete_secret(  # pyright: ignore[reportUnusedFunction]
        name: str, who: Annotated[Person, Depends(caller)], _: Tx, team_id: TeamQuery = None
    ) -> Response:
        owner = _team(who, team_id)
        with _in(who, owner):
            row = await _row(who, owner, name)
            await _not_a_connection_part(who, owner, row)
            _may_write(who, "delete", owner, row.protection)
            # A secret an operation names, staged or published, is not deleted: the next call would fail SECRET_MISSING.
            if users := (await _users(who.tenant_id, owner)).get(name):
                ops = ", ".join(u["operation"] for u in users)
                raise Conflict(
                    f"{name} is read by {ops}. Remove it from those operations first.",
                    code="secret_in_use",
                    details={"operations": [u["operation"] for u in users]},
                )
            if not await secrets.delete(who.tenant_id, owner, name, actor=who.name, at=datetime.now(UTC)):
                raise NotFound(f"Secret {name}")
            return Response(status_code=204)

    return r
