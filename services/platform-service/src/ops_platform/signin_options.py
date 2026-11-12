"""What sign-in needs from settings beyond the database, gathered once at start-up."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from pydantic import SecretStr

from ops_email import MailSender
from ops_service_kit.settings import Settings
from ops_signin.dns import TxtResolver


@dataclass(frozen=True)
class Limits:
    """How many wrong passwords lock a person and for how long, and how many reset links one person is sent."""

    max_failures: int = 5
    failure_window_s: int = 900
    lockout_s: int = 900
    resets_per_window: int = 3
    reset_window_s: int = 3600


@dataclass(frozen=True)
class SignInOptions:
    """What sign-in needs from settings beyond the database: the work factor, where people come back to, the mail
    sender for reset links and the resolver that proves a domain. `transport` reaches
    identity providers in tests."""

    password_iterations: int
    password_min_length: int
    flow_ttl_s: int
    reset_ttl_s: int
    public_url: str | None = None
    console_url: str | None = None
    # tools-service's public base: a team's MCP address, the resource an assistant's grant is for, is under it.
    mcp_url: str | None = None
    # The install's proxies (forms_trusted_proxies): registration and sign-in start limits count the caller behind them.
    trusted_proxies: list[str] = field(default_factory=lambda: ["127.0.0.1/32"])
    mail: MailSender | None = None
    transport: httpx.AsyncBaseTransport | None = None
    dns: TxtResolver = field(default_factory=TxtResolver)
    limits: Limits = field(default_factory=Limits)
    # The SAML service provider's key and certificate, PEM; both or neither.
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
            mcp_url=settings.tools_public_url,
            trusted_proxies=settings.forms_trusted_proxies,
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
