"""The daily watch over SAML providers' certificates: re-reads each metadata URL, adding new signing certificates for
the same entity id, and tells a workspace's Security admins when a certificate is 30 and 7 days from its end, and when
it has ended, once each.

Security admins are the people who hold `settings.manage` in the workspace's Security team (`HolderStore`), so the
roles grid decides who is told. Each notice is audited and, when the installation sends mail, emailed to each of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_email import MailSender, OutboundMessage
from ops_service_kit.ids import new_id
from ops_service_kit.logging import get_logger

from .signin_settings import EXPIRING_DAYS, ProviderMetadata
from .store.audit import record
from .store.holders import HolderStore
from .store.signin import Provider, SignInStore
from .store.workspace import WorkspaceStore

log = get_logger(__name__)


@dataclass
class SecurityNotices:
    """Tells a workspace's Security admins something about its sign-in, audited, by mail when there is a sender."""

    store: SignInStore
    holders: HolderStore
    workspace: WorkspaceStore
    mail: MailSender | None
    console_url: str | None

    async def tell(self, tenant_id: str, *, action: str, target: str, subject: str, body: str, once: str = "") -> int:
        """Audits `action` on `target` and mails `subject` and `body` to each Security admin; returns how many were
        told. `once` makes the mail's key, so a retried notice is sent once and a different one is not taken for it."""
        team = await self.workspace.security_team(tenant_id)
        found: dict[str, Any] = await self.holders.holders(tenant_id, team, "settings", "manage") if team else {}
        people: list[dict[str, Any]] = found.get("holders", [])
        async with self.store.db.tenant_tx(tenant_id) as c:
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor="system",
                action=action,
                target_kind="signin_provider",
                target_id=target,
                request_id=new_id("req"),
                detail={"told": len(people), "subject": subject},
            )
        if self.mail is not None:
            link = f"\n\n{self.console_url.rstrip('/')}/settings/security/sign-in" if self.console_url else ""
            for person in people:
                await self.mail.send(
                    OutboundMessage(
                        key=f"{action}:{target}:{once}:{person['id']}",
                        to=(str(person["email"]),),
                        subject=subject,
                        body=body + link,
                    )
                )
        return len(people)


@dataclass
class SignInWatch:
    store: SignInStore
    metadata: ProviderMetadata
    notices: SecurityNotices

    async def once(self) -> int:
        """One pass over every SAML provider of an open workspace; returns how many notices it sent."""
        sent = 0
        for tenant_id, provider_id in await self.store.watched():
            p = await self.store.provider(tenant_id, provider_id)
            if p is None:
                continue
            try:
                sent += await self._one(p)
            except Exception as e:
                log.warning("signin_watch_failed", provider=p.id, error=type(e).__name__)
        return sent

    async def _one(self, p: Provider) -> int:
        sent = 0
        if p.config.get("metadataUrl"):
            for cert in await self.metadata.refresh(p, request_id=new_id("req")):
                sent += await self.notices.tell(
                    p.tenant_id,
                    action="signin.certificate_added",
                    target=p.id,
                    once=cert.fingerprint,
                    subject=f"{p.label} has a new signing certificate",
                    body=f"Ops AI now trusts a new certificate from {p.label}'s metadata, valid until "
                    f"{cert.not_after[:10]}. If your identity team did not add it, check the provider now.",
                )
            p = await self.store.provider(p.tenant_id, p.id) or p
        now = datetime.now(UTC)
        for cert in p.certificates:
            level = _due(cert.not_after, cert.warned, now)
            if level is None:
                continue
            ended = level == "expired"
            sent += await self.notices.tell(
                p.tenant_id,
                action="signin.certificate_expired" if ended else "signin.certificate_expiring",
                target=p.id,
                once=f"{cert.fingerprint}:{level}",
                subject=f"{p.label}'s signing certificate {'has ended' if ended else 'ends soon'}",
                body=(
                    f"The certificate {p.label} signs sign-ins with ended on {cert.not_after[:10]}. People cannot "
                    "sign in through it until you add the provider's new certificate on the Sign-in page."
                    if ended
                    else f"The certificate {p.label} signs sign-ins with ends on {cert.not_after[:10]}. Add the "
                    "provider's new certificate before then, or give Ops AI its metadata URL so it is read daily."
                ),
            )
            await self.store.mark_warned(p.tenant_id, p.id, cert.fingerprint, level)
        return sent


def _due(not_after: str, warned: str | None, now: datetime) -> str | None:
    """The notice a certificate is due, given the last one sent: "30", "7", "expired" or None."""
    end = datetime.fromisoformat(not_after.replace("Z", "+00:00"))
    order = ["30", "7", "expired"]
    if end <= now:
        level = "expired"
    elif end - now <= timedelta(days=EXPIRING_DAYS[1]):
        level = "7"
    elif end - now <= timedelta(days=EXPIRING_DAYS[0]):
        level = "30"
    else:
        return None
    return level if warned is None or order.index(level) > order.index(warned) else None
