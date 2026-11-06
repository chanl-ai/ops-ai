"""A workspace's sign-in providers, set by its security admins: which methods it allows, which email domains go to
which SSO provider, and where a person new to the workspace lands on their first SSO sign-in.

Reads and writes need `settings.view` and `settings.manage`, which only the Security team grants (`ops_access`), from
the roles the database holds now. A provider stores no secret: an OIDC client secret is named by `clientSecretRef`
and read from settings, and a name settings does not hold is refused here, not at the first sign-in; the console reads
the names, never the values. A first sign-in may make a member, never an admin.

A listed domain is a claim that routes nobody until verified: the workspace publishes the claim's TXT record and asks
for it to be checked. The DNS answer is read before any transaction opens, so a slow resolver holds no lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography import x509

from ops_service_kit.errors import Conflict, NotFound, Unprocessable, ValidationFailed
from ops_signin.dns import TxtResolver, record_value

from .store.members import Actor
from .store.signin import PASSWORD, DomainListedError, DomainTakenError, Provider, SignInStore
from .store.signin_secrets import SignInSecretStore
from .teams import Members

# The membership roles a first SSO sign-in may give; admin is never one.
JIT_ROLES = ("chat_user", "viewer", "builder", "approver")


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def provider_out(p: Provider) -> dict[str, Any]:
    c = p.config
    return {
        "id": p.id,
        "kind": p.kind,
        "label": p.label,
        "enabled": p.enabled,
        "domains": p.domains,
        "verification": [
            {
                "domain": x.domain,
                "verifiedAt": x.verified_at,
                "record": {"name": x.domain, "value": record_value(x.token)},
            }
            for x in p.claims
        ],
        "oidc": {
            "issuer": c.get("issuer"),
            "clientId": c.get("clientId"),
            "clientSecretRef": c.get("clientSecretRef"),
            "scopes": c.get("scopes"),
        }
        if p.kind == "oidc"
        else None,
        "saml": {
            "idpEntityId": c.get("idpEntityId"),
            "ssoUrl": c.get("ssoUrl"),
            "certificate": c.get("certificate"),
            "emailAttribute": c.get("emailAttribute"),
            "nameAttribute": c.get("nameAttribute"),
            "signRequests": bool(c.get("signRequests")),
            "requireEncryption": bool(c.get("requireEncryption")),
        }
        if p.kind == "saml"
        else None,
        "jit": {"team": p.jit_team_id, "role": p.jit_role} if p.jit_role else None,
        "groups": c.get("groups"),
    }


def _secret_out(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": r["name"],
        "version": r["version"],
        "createdBy": r["created_by"],
        "createdAt": r["created_at"],
        "rotatedAt": r["rotated_at"],
    }


@dataclass
class SignInSettings:
    store: SignInStore
    members: Members
    secrets: SignInSecretStore
    dns: TxtResolver
    # Whether the installation has a SAML service provider key; without one, signing and encryption cannot be asked.
    sp_key_set: bool = False

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        await self.members.require_admin(actor, "settings", "view")
        return [provider_out(p) for p in await self.store.providers(actor.tenant_id)]

    async def secret_names(self, actor: Actor) -> list[str]:
        """The names a provider may give as `clientSecretRef`: the workspace's saved secrets, never their values."""
        await self.members.require_admin(actor, "settings", "view")
        return sorted(await self.secrets.names(actor.tenant_id))

    async def secrets_listed(self, actor: Actor) -> list[dict[str, Any]]:
        await self.members.require_admin(actor, "settings", "view")
        return [_secret_out(r) for r in await self.secrets.listed(actor.tenant_id)]

    async def save_secret(self, actor: Actor, name: str, value: str) -> dict[str, Any]:
        """Creates or replaces a secret a provider names; the value is sealed and never returned."""
        await self.members.require_admin(actor, "settings", "manage")
        saved = await self.secrets.save(actor.tenant_id, name, value, by=actor.user_id, request_id=actor.request_id)
        return _secret_out(saved)

    async def delete_secret(self, actor: Actor, name: str) -> None:
        """409 `secret_in_use` while a provider names it, so a sign-in never loses its secret by surprise."""
        await self.members.require_admin(actor, "settings", "manage")
        users = [
            p.id
            for p in await self.store.providers(actor.tenant_id)
            if p.kind == "oidc" and (p.config or {}).get("clientSecretRef") == name
        ]
        if users:
            raise Conflict(
                f"Sign-in provider {', '.join(users)} uses {name}. Point it at another secret first.",
                code="secret_in_use",
                details={"providers": users},
            )
        if not await self.secrets.delete(actor.tenant_id, name, by=actor.user_id, request_id=actor.request_id):
            raise NotFound("sign-in secret")

    async def verify_domain(self, actor: Actor, domain: str) -> dict[str, Any]:
        """Checks the claim's TXT record and marks it verified; 422 `domain_unverified` with what DNS held when the
        record is absent, 409 `domain_taken` when another workspace verified the domain first."""
        await self.members.require_admin(actor, "settings", "manage")
        claim = await self.store.claim(actor.tenant_id, domain)
        if claim is None:
            raise NotFound("sign-in domain")
        if claim.verified_at is None:
            answer = await self.dns.has_record(claim.domain, claim.token)
            if not answer.found:
                seen = ", ".join(answer.values) if answer.values else "no TXT records"
                raise Unprocessable(
                    f"No TXT record {record_value(claim.token)} on {claim.domain} (found {seen}"
                    f"{'; ' + answer.error if answer.error else ''}). DNS can take up to an hour to update.",
                    code="domain_unverified",
                    details={"found": answer.values},
                )
            try:
                await self.store.mark_verified(
                    actor.tenant_id,
                    claim.domain,
                    actor=actor.user_id,
                    at=_iso(datetime.now(UTC)),
                    request_id=actor.request_id,
                )
            except DomainTakenError as e:
                raise Conflict("Another workspace has verified this domain.", code="domain_taken") from e
        saved = await self.store.provider(actor.tenant_id, claim.provider_id)
        if saved is None:
            raise NotFound("sign-in provider")
        return provider_out(saved)

    async def save(self, actor: Actor, provider_id: str, body: dict[str, Any]) -> dict[str, Any]:
        await self.members.require_admin(actor, "settings", "manage")
        kind = str(body["kind"])
        config = self._config(kind, body, await self.secrets.names(actor.tenant_id))
        listed: list[Any] = body.get("domains") or []
        domains = [str(d).strip().lower() for d in listed]
        if kind == PASSWORD and domains:
            raise ValidationFailed("A password provider takes no domains.", code="domains_not_allowed")
        jit = body.get("jit")
        team, role = (jit.get("team"), str(jit["role"])) if jit else (None, None)
        if role is not None:
            if kind == PASSWORD:
                raise ValidationFailed("Only a company sign-in creates people.", code="jit_not_allowed")
            if role not in JIT_ROLES:
                raise ValidationFailed(f"A first sign-in may give {', '.join(JIT_ROLES)}.", code="jit_role")
        groups = body.get("groups")
        if groups and kind == PASSWORD:
            raise ValidationFailed("Only a company sign-in carries groups.", code="groups_not_allowed")
        rules: list[dict[str, Any]] = groups["map"] if groups else []
        if any(str(r["role"]) not in JIT_ROLES for r in rules):
            raise ValidationFailed(f"A group may give {', '.join(JIT_ROLES)}.", code="group_role")
        # Each team this provider sends people to adds members to it, so each takes that team's own right to add them.
        targets: set[str] = {str(r["team"]) for r in rules} | ({str(team)} if team else set[str]())
        for linked in sorted(targets):
            if not await self.store.team_exists(actor.tenant_id, linked):
                raise NotFound("team")
            await self.members.require_admin(
                Actor(actor.tenant_id, linked, actor.user_id, actor.request_id), "access", "create"
            )
        if groups:
            config["groups"] = {"source": groups.get("source"), "map": [dict(r) for r in rules]}
        if await self.store.verified_elsewhere(actor.tenant_id, domains):
            raise Conflict("Another workspace has verified one of these domains.", code="domain_taken")
        p = Provider(
            id=provider_id,
            tenant_id=actor.tenant_id,
            kind=kind,
            label=str(body["label"]),
            enabled=bool(body.get("enabled", True)),
            config=config,
            jit_team_id=str(team) if team else None,
            jit_role=role,
            domains=domains,
        )
        try:
            await self.store.save_provider(
                p, actor=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
            )
        except DomainTakenError as e:
            raise Conflict("Another workspace has verified one of these domains.", code="domain_taken") from e
        except DomainListedError as e:
            raise Conflict(
                f"{e.args[0]} is on another of this workspace's providers; remove it there first.", code="domain_taken"
            ) from e
        saved = await self.store.provider(actor.tenant_id, provider_id)
        if saved is None:
            raise NotFound("sign-in provider")
        return provider_out(saved)

    async def delete(self, actor: Actor, provider_id: str) -> None:
        await self.members.require_admin(actor, "settings", "manage")
        gone = await self.store.delete_provider(
            actor.tenant_id, provider_id, actor=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
        )
        if not gone:
            raise NotFound("sign-in provider")

    def _config(self, kind: str, body: dict[str, Any], secret_names: set[str]) -> dict[str, Any]:
        oidc, saml = body.get("oidc"), body.get("saml")
        if kind == "oidc":
            if not oidc or saml:
                raise ValidationFailed("An OIDC provider takes the oidc settings only.", code="config_kind")
            ref = oidc.get("clientSecretRef")
            if ref and ref not in secret_names:
                raise ValidationFailed(f"This workspace saved no sign-in secret named {ref}.", code="secret_missing")
            return {k: v for k, v in oidc.items() if v is not None}
        if kind == "saml":
            if not saml or oidc:
                raise ValidationFailed("A SAML provider takes the saml settings only.", code="config_kind")
            try:
                x509.load_pem_x509_certificate(str(saml["certificate"]).encode())
            except ValueError as e:
                raise ValidationFailed("The certificate is not a PEM X.509 certificate.", code="certificate") from e
            if (saml.get("signRequests") or saml.get("requireEncryption")) and not self.sp_key_set:
                raise ValidationFailed(
                    "Signed requests and encrypted assertions need the service provider key (OPS_SAML_SP_KEY).",
                    code="sp_key_missing",
                )
            return {k: v for k, v in saml.items() if v is not None}
        if oidc or saml:
            raise ValidationFailed("A password provider takes no settings.", code="config_kind")
        return {}
