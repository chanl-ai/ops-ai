"""Request and response models for platform-service. Requests refuse unknown fields (I5), and none names a tenant or
team (I1): both come from the identity."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from ops_service_kit.http import ListResult, Out


class In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SignIn(In):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(max_length=200)


class Refresh(In):
    refresh_token: str = Field(min_length=10, max_length=200)


class StepUpIn(In):
    password: str = Field(max_length=200)


class StepUpOut(Out):
    token: str
    expires_at: str


class Introspect(In):
    api_key: str = Field(min_length=1, max_length=200)


class ActingForIn(In):
    """The person a tool call acts for, by the email a run or chat turn records; the team is the service token's."""

    email: str = Field(min_length=3, max_length=320)


class ActingForOut(Out):
    token: str
    expires_at: str


class KeyTarget(Out):
    """What an API key may start (c-246). `version` pins a workflow version; null runs the live one."""

    kind: Literal["agent", "workflow"]
    id: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)


class KeyRef(Out):
    id: str
    target: KeyTarget | None


class Principal(Out):
    kind: Literal["person", "api_key", "service"]
    sub: str
    email: str
    name: str
    tenant_id: str
    team_id: str | None
    team_ids: list[str]
    roles: dict[str, str]
    scopes: list[str]
    auth_method: str
    # The tenant's access policies (c-186); a missing key has its open default.
    policies: dict[str, Any] = Field(default_factory=dict[str, Any])
    # An API key's id and what it may start; None for a person.
    api_key: KeyRef | None = None


class SessionOut(Out):
    token: str
    refresh_token: str
    expires_at: str
    principal: Principal


class Jwk(BaseModel):
    """A public key as RFC 7517 names its fields, so they stay snake-free and unaliased."""

    model_config = ConfigDict(extra="forbid")
    kty: str
    crv: str
    x: str
    kid: str
    alg: str
    use: str


class Jwks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[Jwk]


class Health(Out):
    status: str


ROLE = r"^(admin|builder|approver|viewer)$"
MEMBER_ID = r"^mem_[A-Za-z0-9_-]{1,60}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class MeUser(Out):
    id: str
    email: str
    name: str


class MeTeam(Out):
    id: str
    name: str
    role: str


class WorkspaceStateOut(Out):
    """The workspace's owner and status (c-529): `purgeAfter` is when a closed workspace's records go, else null."""

    owner_user_id: str | None
    status: Literal["active", "suspended", "closed", "purging", "purged"]
    purge_after: str | None


class Me(Out):
    user: MeUser
    tenant_id: str
    # The workspace's name, for the console's header.
    tenant_name: str
    teams: list[MeTeam]
    # The tenant's access policies now (c-186), every key with its value.
    policies: dict[str, Any]
    # The team that holds the Security team's actions in this deployment.
    security_team_id: str
    workspace: WorkspaceStateOut


class TeamName(Out):
    id: str
    name: str


class PersonName(Out):
    email: str
    name: str


class TeamOut(Out):
    id: str
    name: str
    owner_groups: list[str]
    scope: str
    role: str
    member_count: int


TEAM_NAME = r"^\S(.{0,78}\S)?$"


class TeamIn(In):
    name: str = Field(min_length=1, max_length=80, pattern=TEAM_NAME)
    # The first admin: the email of an active person of the workspace.
    admin: str = Field(min_length=3, max_length=320, pattern=EMAIL)


class TeamRenameIn(In):
    name: str = Field(min_length=1, max_length=80, pattern=TEAM_NAME)


class WorkspaceRenameIn(In):
    """The workspace's display name: the bank's or organisation's name people see in the console."""

    name: str = Field(min_length=1, max_length=80, pattern=TEAM_NAME)


class WorkspaceNameOut(Out):
    id: str
    name: str


class TransferIn(In):
    """The account admin who becomes the workspace's owner."""

    user_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class WorkspaceCloseIn(In):
    """The workspace's name, typed by its owner to confirm the delete."""

    name: str = Field(min_length=1, max_length=80)


class TeamDeleteCheckOut(Out):
    """Whether a team may be deleted now and why not (c-529): the Delete card reads it in one call."""

    team_id: str
    status: str
    security: bool
    # Days until an archived team may be deleted; null while it is active.
    days_left: int | None
    # False when agents-service did not answer; Delete is then off.
    usage_known: bool
    live_workflows: list[str]
    runs_in_progress: int
    can_delete: bool


class WorkspaceTeamOut(Out):
    """A team as a workspace admin sees it (c-198): counts joined by the service."""

    id: str
    name: str
    status: Literal["active", "archived"]
    scope: str
    created_at: str
    archived_at: str | None
    member_count: int
    admin_count: int
    # The workspace's Security team, which cannot be archived.
    security: bool


class WorkspaceTeamsIn(In):
    security_team: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # Null: no default team; new people join only the team something else names.
    default_team: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class WorkspaceTeamsOut(Out):
    security_team: str
    default_team: str | None


class MemberOut(Out):
    id: str
    name: str
    email: str
    role: str
    team_id: str
    team: str
    status: Literal["active", "invited"]
    invited_at: str | None = None
    # The person's own id once they have joined (null for an invite): what their person page is keyed by.
    user_id: str | None = None
    # Roles the person holds in every team (`*`), by name: where access beyond their team role comes from.
    workspace_roles: list[str] = Field(default_factory=list[str])


class InviteIn(In):
    emails: list[Annotated[str, StringConstraints(pattern=EMAIL, max_length=320)]] = Field(min_length=1, max_length=50)
    role: str = Field(pattern=ROLE)


class RoleIn(In):
    ids: list[Annotated[str, StringConstraints(pattern=MEMBER_ID)]] = Field(min_length=1, max_length=100)
    role: str = Field(pattern=ROLE)


class DeleteIn(In):
    ids: list[Annotated[str, StringConstraints(pattern=MEMBER_ID)]] = Field(min_length=1, max_length=100)


class Skip(Out):
    id: str
    reason: str


class BulkOut(Out):
    updated: list[str]
    skipped: list[Skip]


class InviteLink(Out):
    member_id: str
    email: str
    token: str


class InviteBulkOut(BulkOut):
    invites: list[InviteLink]


class InvitePreview(Out):
    token: str
    email: str
    team_id: str
    team: str
    role: str
    invited_by: str | None = Field(description="Who sent it; null when that person is gone")
    existing_account: bool = Field(description="The email already has an account: accept while signed in as it")
    invited_at: str
    expires_at: str
    state: Literal["pending", "expired", "accepted"]


class AcceptIn(In):
    name: str = Field(min_length=1, max_length=200)
    # Set for a new person in a workspace that signs in by password; stored as a hash.
    password: str | None = Field(default=None, max_length=200)


class ApiKeyOut(Out):
    id: str
    name: str
    prefix: str
    scopes: list[Literal["read", "write"]]
    created_by: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    team: str
    status: Literal["active", "revoked", "disabled"]
    target: KeyTarget | None = None


class ApiKeySummary(Out):
    """A key as another service lists it (c-246): what it serves and whether it works."""

    id: str
    name: str
    prefix: str
    team_id: str
    status: Literal["active", "revoked", "disabled"]
    target: KeyTarget | None
    last_used_at: str | None
    expires_at: str | None
    created_at: str


class KeyTargetIn(In):
    kind: Literal["agent", "workflow"]
    id: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)


class ApiKeyIn(In):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[Literal["read", "write"]] = Field(min_length=1, max_length=2)
    expires_in_days: int | None = Field(default=None, ge=1, le=730)
    # The one agent or workflow the key may start; left out, any live workflow of the team.
    target: KeyTargetIn | None = None


class ApiKeyCreated(Out):
    key: ApiKeyOut
    secret: str


AuditKind = Literal["invited", "joined", "role_changed", "deleted", "created", "revoked", "login", "edited", "checked"]


class AuditEntryOut(Out):
    id: str
    team_id: str | None
    team: str | None = Field(description="The team's name; null for an entry outside any team, such as a sign-in")
    actor: str
    actor_name: str | None = Field(description="Null when the actor is not a person of this tenant")
    actor_email: str | None
    action: str
    kind: AuditKind = Field(description="The action as the console names it")
    summary: str = Field(description="One line a person reads")
    target_kind: str
    target_id: str
    target_name: str | None = Field(description="A member's email or an API key's name; null for other targets")
    request_id: str
    at: str
    detail: dict[str, Any]


class AuditPage(ListResult[AuditEntryOut]):
    view_counts: dict[str, int] = Field(
        description="Entries in each of the audit page's views: all, access, deletions, publishes"
    )


Scope = Literal["all", "own"]


class RoleOut(Out):
    id: str
    name: str
    builtin: bool
    description: str
    permission_count: int
    assignment_count: int


class PermissionOut(Out):
    area: str
    action: str
    scope: Scope


class GridRow(Out):
    area: str
    # Every action in the catalogue: its scope when the role grants it, null when it does not.
    actions: dict[str, Scope | None]


class RoleDetail(RoleOut):
    permissions: list[PermissionOut]
    grid: list[GridRow]


class GrantingRole(Out):
    id: str
    name: str
    via: Literal["person", "team"]


class EffectivePermission(Out):
    area: str
    action: str
    scope: Scope
    security_team_only: bool
    roles: list[GrantingRole]


class TeamPermissions(Out):
    team_id: str
    team_name: str
    permissions: list[EffectivePermission]


class RoleRef(Out):
    id: str
    name: str


class Holder(Out):
    id: str
    name: str
    email: str
    # The granting roles this person holds in the team.
    roles: list[str]


class HoldersOut(Out):
    team_id: str
    # Every role that grants the action, built-in first.
    roles: list[RoleRef]
    holders: list[Holder]


class AccessCheckIn(In):
    person_id: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    area: str = Field(max_length=32)
    action: str = Field(max_length=16)
    # The record's owner or creator (email), for an `own` scope; the person who asked, for separation of duties.
    owner: str | None = Field(default=None, max_length=320)
    requested_by: str | None = Field(default=None, max_length=320)


class CheckRefusal(Out):
    code: str
    reason: str


class AccessCheckOut(Out):
    person_id: str
    team_id: str
    area: str
    action: str
    allowed: bool
    scope: Scope | None
    # The roles that grant it in the team (allowed), or the rule that refused it (a role, a policy, another team).
    granted_by: list[GrantingRole]
    refused_by: CheckRefusal | None


class WhyOut(AccessCheckOut):
    # The roles that grant the action in the team, and the people there who can give roles: who to ask.
    roles: list[RoleRef]
    askable: list[str]


class PermissionsOut(Out):
    person_id: str
    # The person's display name and address, so a person page names who it is about without a second list.
    name: str | None = None
    email: str | None = None
    permission_version: int
    # What the person may do in every team at once, from their `*` assignments (a workspace admin, c-198).
    workspace: list[EffectivePermission]
    teams: list[TeamPermissions]


# ── Sign-in methods, SSO and password reset (c-188) ──

# A console path to return to: one leading slash, so it can never name another host.
NEXT_PATH = r"^/([^/\\\s][^\s]{0,498})?$"
DOMAIN = r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"


class OptionsIn(In):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL)


class SsoOption(Out):
    kind: Literal["oidc", "saml"]
    label: str


class OptionsOut(Out):
    password: bool
    sso: SsoOption | None


class SsoStartIn(In):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL)
    next: str | None = Field(default=None, pattern=NEXT_PATH)


class StepUpSsoStartIn(In):
    next: str | None = Field(default=None, pattern=NEXT_PATH)


class SsoStarted(Out):
    redirect_url: str
    flow_key: str


class SsoCompleteIn(In):
    code: str = Field(min_length=10, max_length=200)
    flow_key: str = Field(min_length=10, max_length=200)


class ForgotIn(In):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL)


class ResetIn(In):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=200)


class OidcSettings(In):
    issuer: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    client_id: str = Field(min_length=1, max_length=255)
    client_secret_ref: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    scopes: list[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_:./-]{1,100}$")]] | None = Field(
        default=None, max_length=20
    )


class SamlSettings(In):
    idp_entity_id: str = Field(min_length=1, max_length=500)
    sso_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    certificate: str = Field(min_length=100, max_length=20000)
    email_attribute: str | None = Field(default=None, max_length=255)
    name_attribute: str | None = Field(default=None, max_length=255)
    # c-197: sign each AuthnRequest, and refuse an assertion that is not encrypted; both need the SP key.
    sign_requests: bool = False
    require_encryption: bool = False


class JitSettings(In):
    """Where a person new to the workspace lands on their first sign-in through this provider: the team, or with no
    team the workspace's default team (c-202)."""

    team: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    role: str = Field(max_length=16)


class GroupRule(In):
    group: str = Field(min_length=1, max_length=255)
    team: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    role: str = Field(max_length=16)


class GroupSettings(In):
    """Identity provider groups to team memberships (c-202): `source` is the OIDC claim or SAML attribute that lists
    the person's groups (default `groups`)."""

    source: str | None = Field(default=None, max_length=255)
    map: list[GroupRule] = Field(min_length=1, max_length=100)


class ProviderIn(In):
    kind: Literal["password", "oidc", "saml"]
    label: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    domains: list[Annotated[str, StringConstraints(to_lower=True, max_length=253, pattern=DOMAIN)]] = Field(
        default_factory=list[str], max_length=50
    )
    oidc: OidcSettings | None = None
    saml: SamlSettings | None = None
    jit: JitSettings | None = None
    groups: GroupSettings | None = None


class OidcSettingsOut(Out):
    issuer: str
    client_id: str
    client_secret_ref: str | None
    scopes: list[str] | None


class SamlSettingsOut(Out):
    idp_entity_id: str
    sso_url: str
    certificate: str
    email_attribute: str | None
    name_attribute: str | None
    sign_requests: bool
    require_encryption: bool


class JitOut(Out):
    team: str | None
    role: str


class GroupRuleOut(Out):
    group: str
    team: str
    role: str


class GroupSettingsOut(Out):
    source: str | None
    map: list[GroupRuleOut]


class TxtRecordOut(Out):
    name: str
    value: str


class DomainCheckOut(Out):
    """A listed domain: routes sign-in only once `verified_at` is set, after `record` was seen in its DNS."""

    domain: str
    verified_at: str | None
    record: TxtRecordOut


class ProviderOut(Out):
    id: str
    kind: Literal["password", "oidc", "saml"]
    label: str
    enabled: bool
    domains: list[str]
    verification: list[DomainCheckOut]
    oidc: OidcSettingsOut | None
    saml: SamlSettingsOut | None
    jit: JitOut | None
    groups: GroupSettingsOut | None


class PolicyIn(In):
    # A bool for a switch, a number from 0 to 1 or null for a floor, whole days or null for a retention; the catalogue
    # checks which the key takes. int before float, so whole days stay whole. A per-team key (publishReview) takes
    # the acting team's {area: mode}.
    value: bool | int | float | dict[str, Any] | None


class PolicyOut(Out):
    key: str
    # A per-team key's value is the whole {team: {area: mode}}.
    value: bool | int | float | dict[str, Any] | None
    default: bool | int | float | dict[str, Any] | None
    changed_by: str
    effect: str
    kind: Literal["bool", "floor", "days", "hours", "publish_modes", "plugins"]
    title: str


class DevSignInIn(In):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")


class DevTeamRole(Out):
    team: str
    role: str


class DevPerson(Out):
    """A seeded demo person the dev sign-in page offers; never the password."""

    name: str
    email: str
    teams: list[DevTeamRole]
