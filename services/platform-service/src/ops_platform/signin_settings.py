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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_service_kit.errors import Conflict, NotFound, TooLarge, Unprocessable, ValidationFailed
from ops_service_kit.ids import new_id
from ops_service_kit.public_address import AddressRefused
from ops_signin.dns import TxtResolver, record_value
from ops_signin.saml_metadata import IdpMetadata, MetadataCertificate, MetadataRefused, certificate_of, read_metadata

from .sso import saml_addresses
from .store.members import Actor
from .store.signin import (
    PASSWORD,
    SIGNIN_ROLES,
    DomainListedError,
    DomainTakenError,
    GroupRule,
    Provider,
    SignInStore,
    TrustedCertificate,
    group_settings,
)
from .store.signin_secrets import SignInSecretStore
from .teams import Members

# The membership roles a first SSO sign-in may give; admin is never one.
JIT_ROLES = SIGNIN_ROLES


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# A certificate this close to its end date is shown, and Security admins told, as expiring.
EXPIRING_DAYS = (30, 7)


def certificate_state(not_after: str, now: datetime) -> str:
    """`expired`, `expiring` (within the first warning) or `current`."""
    end = datetime.fromisoformat(not_after.replace("Z", "+00:00"))
    if end <= now:
        return "expired"
    return "expiring" if end - now <= timedelta(days=EXPIRING_DAYS[0]) else "current"


def trusted(cert: MetadataCertificate, source: str) -> TrustedCertificate:
    return TrustedCertificate(
        fingerprint=cert.fingerprint,
        pem=cert.pem,
        not_before=_iso(cert.not_before),
        not_after=_iso(cert.not_after),
        source=source,
        added_at="",
    )


def metadata_out(m: IdpMetadata) -> dict[str, Any]:
    return {
        "idpEntityId": m.entity_id,
        "ssoUrl": m.sso_url,
        "certificates": [
            {"fingerprint": x.fingerprint, "notBefore": _iso(x.not_before), "notAfter": _iso(x.not_after)}
            for x in m.certificates
        ],
    }


def _saml_out(p: Provider, public_url: str | None, console_url: str | None) -> dict[str, Any]:
    c = p.config
    now = datetime.now(UTC)
    certs = [
        {
            "fingerprint": x.fingerprint,
            "notBefore": x.not_before,
            "notAfter": x.not_after,
            "source": x.source,
            "addedAt": x.added_at,
            "state": certificate_state(x.not_after, now),
        }
        for x in p.certificates
    ]
    newest = next((x.pem for x in p.certificates if certificate_state(x.not_after, now) != "expired"), None)
    at = saml_addresses(public_url, p.sp_id) if public_url else {}
    tile = (
        f"{console_url.rstrip('/')}/sso?provider={p.sp_id}"
        if console_url and p.sp_id and c.get("tiles", True)
        else None
    )
    return {
        "idpEntityId": c.get("idpEntityId"),
        "ssoUrl": c.get("ssoUrl"),
        # The newest certificate still in its dates, for a console that reads one certificate.
        "certificate": newest or c.get("certificate"),
        "certificates": certs,
        "metadataUrl": c.get("metadataUrl"),
        "metadataReadAt": c.get("metadataReadAt"),
        "metadataError": c.get("metadataError"),
        "emailAttribute": c.get("emailAttribute"),
        "nameAttribute": c.get("nameAttribute"),
        "signRequests": bool(c.get("signRequests")),
        "requireEncryption": bool(c.get("requireEncryption")),
        "tiles": bool(c.get("tiles", True)),
        "spEntityId": at.get("entityId"),
        "acsUrl": at.get("acsUrl"),
        "spMetadataUrl": at.get("metadataUrl"),
        "signOnUrl": tile,
    }


def provider_out(p: Provider, public_url: str | None = None, console_url: str | None = None) -> dict[str, Any]:
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
        "saml": _saml_out(p, public_url, console_url) if p.kind == "saml" else None,
        "jit": {"team": p.jit_team_id, "role": p.jit_role} if p.jit_role else None,
        "groups": {
            **group_settings(c),
            "onMissing": group_settings(c).get("onMissing", "keep"),
            "map": [{"group": r.group, "team": r.team, "role": r.role} for r in p.group_rules],
        }
        if p.group_rules or c.get("groups")
        else None,
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
class ProviderMetadata:
    """Reads identity providers' SAML metadata: a URL through `fetch` (the public-address guard), or a file."""

    store: SignInStore
    # Fetches a URL an admin typed (sso.guarded_get bound to the service's client); raises ValueError when refused.
    fetch: Callable[[str], Awaitable[bytes]] | None

    async def read(self, url: str | None, xml: str | None) -> IdpMetadata:
        """The metadata at `url` or in `xml`. Raises Unprocessable (or TooLarge) with the reason's code."""
        try:
            if url is not None:
                if self.fetch is None:
                    raise MetadataRefused("metadata_unreadable", "Metadata URLs are not read on this installation.")
                try:
                    document = await self.fetch(url)
                except ValueError as e:
                    code = "metadata_address" if isinstance(e, AddressRefused) else "metadata_unreadable"
                    raise MetadataRefused(code, f"{e} Check the metadata URL.") from e
            else:
                document = (xml or "").encode()
            return read_metadata(document)
        except MetadataRefused as e:
            if e.code == "metadata_too_large":
                raise TooLarge(str(e), code=e.code) from e
            raise Unprocessable(str(e), code=e.code) from e

    async def refresh(self, p: Provider, *, request_id: str) -> list[TrustedCertificate]:
        """Re-reads a provider's metadata URL and adds its new signing certificates, only while the metadata names
        the entity id already saved: a hijacked metadata URL cannot add a signer for another entity. A failed read
        keeps every certificate already trusted and is shown on the provider. Returns the certificates added."""
        at = _iso(datetime.now(UTC))
        try:
            m = await self.read(str(p.config["metadataUrl"]), None)
        except (Unprocessable, TooLarge) as e:
            await self.store.metadata_read(p, at=at, error=str(e))
            return []
        if m.entity_id != p.config.get("idpEntityId"):
            await self.store.metadata_read(
                p, at=at, error=f"The metadata now names {m.entity_id}; nothing was added. Check the provider."
            )
            return []
        await self.store.metadata_read(p, at=at, error=None)
        return await self.store.add_certificates(
            p, [trusted(x, "metadata") for x in m.certificates], at=at, request_id=request_id
        )


@dataclass
class SignInSettings:
    store: SignInStore
    members: Members
    secrets: SignInSecretStore
    dns: TxtResolver
    # Whether the installation has a SAML service provider key; without one, signing and encryption cannot be asked.
    sp_key_set: bool = False
    # Where the addresses an identity provider is told about are built (platform-service's public URL, the console).
    public_url: str | None = None
    console_url: str | None = None
    # Reads providers' metadata (a URL through the public-address guard, or a file).
    metadata: ProviderMetadata | None = None

    async def read_metadata(self, actor: Actor, *, url: str | None, xml: str | None) -> dict[str, Any]:
        """What a provider's metadata says, for the admin to check before saving; saves nothing."""
        await self.members.require_admin(actor, "settings", "manage")
        return metadata_out(await self._reader().read(url, xml))

    async def refresh(self, actor: Actor, provider_id: str) -> dict[str, Any]:
        """Reads the provider's metadata URL now, as the daily watch does."""
        await self.members.require_admin(actor, "settings", "manage")
        p = await self.store.provider(actor.tenant_id, provider_id)
        if p is None or p.kind != "saml" or not p.config.get("metadataUrl"):
            raise NotFound("sign-in provider with a metadata URL")
        await self._reader().refresh(p, request_id=actor.request_id)
        saved = await self.store.provider(actor.tenant_id, provider_id)
        if saved is None:
            raise NotFound("sign-in provider")
        return self._out(saved)

    def _reader(self) -> ProviderMetadata:
        return self.metadata or ProviderMetadata(self.store, None)

    def _out(self, p: Provider) -> dict[str, Any]:
        return provider_out(p, self.public_url, self.console_url)

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        await self.members.require_admin(actor, "settings", "view")
        return [self._out(p) for p in await self.store.providers(actor.tenant_id)]

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
        return self._out(saved)

    async def save(self, actor: Actor, provider_id: str, body: dict[str, Any]) -> dict[str, Any]:
        await self.members.require_admin(actor, "settings", "manage")
        kind = str(body["kind"])
        config = self._config(kind, body, await self.secrets.names(actor.tenant_id))
        certificates = await self._certificates(config) if kind == "saml" else None
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
        if await self.store.verified_elsewhere(actor.tenant_id, domains):
            raise Conflict("Another workspace has verified one of these domains.", code="domain_taken")
        before = await self.store.provider(actor.tenant_id, provider_id)
        if groups:
            # Removal is the default for a new provider (decision D4); one saved before it keeps adding only, until an
            # admin chooses.
            kept = (group_settings(before.config).get("onMissing") if before else None) or (
                "keep" if before else "remove"
            )
            config["groups"] = {"source": groups.get("source"), "onMissing": groups.get("onMissing") or kept}
        # A provider keeps the addresses it was created with; a new company provider gets its own.
        sp_id = before.sp_id if before else (new_id("ssp") if kind != PASSWORD else None)
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
            sp_id=sp_id,
        )
        try:
            await self.store.save_provider(
                p,
                actor=actor.user_id,
                at=_iso(datetime.now(UTC)),
                request_id=actor.request_id,
                certificates=certificates,
                rules=[GroupRule(str(r["group"]), str(r["team"]), str(r["role"])) for r in rules],
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
        return self._out(saved)

    async def delete(self, actor: Actor, provider_id: str) -> None:
        await self.members.require_admin(actor, "settings", "manage")
        gone = await self.store.delete_provider(
            actor.tenant_id, provider_id, actor=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
        )
        if not gone:
            raise NotFound("sign-in provider")

    async def _certificates(self, config: dict[str, Any]) -> list[TrustedCertificate]:
        """The certificates a SAML save trusts: those typed or uploaded, and those its metadata URL lists, read now
        and only for the entity id being saved. Refused when none is within its dates. The list leaves `config`, which
        keeps the newest one only for a console that reads one certificate."""
        typed = [str(x) for x in [config.pop("certificate", None), *config.pop("certificates", [])] if x]
        certs = [trusted(certificate_of(pem), "manual") for pem in typed]
        if config.get("metadataUrl"):
            m = await self._reader().read(str(config["metadataUrl"]), None)
            if m.entity_id != config.get("idpEntityId"):
                raise Unprocessable(
                    f"The metadata names {m.entity_id}, not {config.get('idpEntityId')}.", code="metadata_entity"
                )
            certs += [
                trusted(x, "metadata") for x in m.certificates if x.fingerprint not in {c.fingerprint for c in certs}
            ]
            config["metadataReadAt"], config["metadataError"] = _iso(datetime.now(UTC)), None
        now = datetime.now(UTC)
        live = [c for c in certs if certificate_state(c.not_after, now) != "expired"]
        if not live:
            raise ValidationFailed(
                "Every certificate given has expired. Download the provider's current certificate or metadata.",
                code="certificate_expired",
            )
        config["certificate"] = max(live, key=lambda c: c.not_after).pem
        return certs

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
            extra: list[Any] = saml.get("certificates") or []
            listed: list[str] = [str(x) for x in [saml.get("certificate"), *extra] if x]
            if not listed and not saml.get("metadataUrl"):
                raise ValidationFailed("Give the provider's metadata URL or its certificate.", code="certificate")
            for pem in listed:
                try:
                    certificate_of(pem)
                except MetadataRefused as e:
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
