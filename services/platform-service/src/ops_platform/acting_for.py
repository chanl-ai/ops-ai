"""Acting-for tokens: the proof one service hands another that a call acts for one person (agents-service to
tools-service for a tool call, tools-service to agents-service for an MCP operation that makes a record).

agents-service knows whom a chat turn or a run acts for, but a field it writes in a request body is only its word.
platform-service checks that the person is an active member of the call's team and signs a short token naming them,
with the same key as people's sessions, so tools-service verifies it through the published key set as it verifies a
person. The token is its own `kind`: ops_identity refuses it as a session, and a session is refused where this token is
asked for. `act` names the service it was minted for (RFC 8693); tools-service requires it to equal the service token
the call arrives with, so a token taken from one service's traffic cannot be replayed by another.

The token also carries what the person may do in that one team (roles, role ids, grids, policies), read when it is
minted, so a service that does not own membership (tools-service) decides a platform tool's cells as the person's own.
A service that owns a right (platform-service for members) decides from its database again, never from the token.

Membership is checked when the token is minted, so a person removed from the team can be acted for until it expires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ops_policy import Ed25519Signer, mint
from ops_service_kit.errors import NotFound
from ops_service_kit.ids import new_id

from .auth import access_claims
from .store.identity import IdentityStore
from .store.workspace import WorkspaceStore

ACTING_FOR_KIND = "acting_for"
ACTING_FOR_TTL_S = 60
# The services that may ask, each with the services its tokens may be for, the first the default: agents-service's
# tool calls go to tools-service; tools-service's platform tools (mcp_tools.py) go to agents-service, to
# platform-service (members) and to kb-service (knowledge).
AUDIENCES: dict[str, tuple[str, ...]] = {"service:agents": ("tools",), "service:tools": ("agents", "platform", "kb")}
MINTERS = frozenset(AUDIENCES)


def not_found(what: str, code: str) -> NotFound:
    """NotFound with its own code, so a caller can tell why without a 403."""
    e = NotFound(what)
    e.code = code
    return e


@dataclass(frozen=True)
class ActingForIssued:
    token: str
    expires_at: str


class ActingFor:
    def __init__(
        self,
        store: IdentityStore,
        signer: Ed25519Signer,
        *,
        ttl_s: int = ACTING_FOR_TTL_S,
        workspace: WorkspaceStore | None = None,
    ) -> None:
        self.store = store
        self.signer = signer
        self.ttl_s = ttl_s
        self.workspace = workspace

    async def mint(
        self, *, service: str, tenant_id: str, email: str, team_id: str, audience: str | None = None
    ) -> ActingForIssued:
        """A token naming the person with `email` in `team_id`, for `service`, to be sent to `audience` (one of the
        service's AUDIENCES; its first when unset). 404 `not_a_member` when no active person of the tenant has that
        email in that team, as another team's record answers, and `acting_for_refused` for a service that may not
        ask, or an audience it may not send to."""
        if service not in MINTERS or (audience is not None and audience not in AUDIENCES[service]):
            raise not_found("Acting-for tokens for this service", "acting_for_refused")
        now = datetime.now(UTC)
        at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        found = [u for u in await self.store.users_by_email(email) if u.tenant_id == tenant_id]
        user = await self.store.user(tenant_id, found[0].id) if found else None
        teams = await self.store.acting_teams(tenant_id, user.id, now=at) if user else []
        if user is None or team_id not in teams:
            raise not_found("A member of this team with that email", "not_a_member")
        claims = {
            "sub": user.id,
            "email": user.email,
            "name": user.name,
            "tenant_id": tenant_id,
            "team_id": team_id,
            "kind": ACTING_FOR_KIND,
            "act": {"sub": service},
            "jti": new_id("tok"),
            "aud": audience or AUDIENCES[service][0],
            **await access_claims(self.store, self.workspace, user, now, team=team_id),
        }
        token = mint(claims, self.signer, ttl_s=self.ttl_s, now=now.timestamp())
        expires = (now + timedelta(seconds=self.ttl_s)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return ActingForIssued(token=token, expires_at=expires)
