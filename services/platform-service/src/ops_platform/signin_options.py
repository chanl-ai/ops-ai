"""What sign-in needs from settings beyond the database, gathered once at start-up (c-188)."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from pydantic import SecretStr

from ops_email import MailSender
from ops_service_kit.settings import Settings
from ops_signin.dns import TxtResolver


@dataclass(frozen=True)
class Limits:
    """How many wrong passwords lock a person and for how long, and how many reset links one person is sent (c-196)."""

    max_failures: int = 5
    failure_window_s: int = 900
    lockout_s: int = 900
    resets_per_window: int = 3
    reset_window_s: int = 3600


@dataclass(frozen=True)
class SignInOptions:
    """What sign-in needs from settings beyond the database: the work factor, where people come back to, the mail
    sender for reset links, the secrets providers name and the resolver that proves a domain. `transport` reaches
    identity providers in tests."""

    password_iterations: int
    password_min_length: int
    flow_ttl_s: int
    reset_ttl_s: int
    public_url: str | None = None
    console_url: str | None = None
    secrets: dict[str, SecretStr] = field(default_factory=dict[str, SecretStr])
    mail: MailSender | None = None
    transport: httpx.AsyncBaseTransport | None = None
    dns: TxtResolver = field(default_factory=TxtResolver)
    limits: Limits = field(default_factory=Limits)
    # The SAML service provider's key and certificate, PEM (c-197); both or neither.
    saml_sp_key: SecretStr | None = None
    saml_sp_certificate: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings, *, mail: MailSender | None = None) -> SignInOptions:
        return cls(
            password_iterations=settings.password_hash_iterations,
            password_min_length=settings.password_min_length,
            flow_ttl_s=settings.signin_flow_seconds,
            reset_ttl_s=settings.password_reset_seconds,
            public_url=settings.platform_public_url,
            console_url=settings.console_url,
            secrets=settings.signin_secrets,
            mail=mail,
            dns=TxtResolver(settings.signin_dns_servers, timeout_s=settings.signin_dns_timeout_seconds),
            saml_sp_key=settings.saml_sp_key,
            saml_sp_certificate=settings.saml_sp_certificate,
            limits=Limits(
                max_failures=settings.signin_max_failures,
                failure_window_s=settings.signin_failure_window_seconds,
                lockout_s=settings.signin_lockout_seconds,
                resets_per_window=settings.password_reset_max_per_window,
                reset_window_s=settings.password_reset_window_seconds,
            ),
        )
