# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The install's own sender, picked from its settings (`Settings.mail_provider`): the mail the platform sends itself,
such as a password reset. Code names no provider; a deployment changes provider by changing a setting and its secrets.
Built once per process; a missing secret raises here, at start-up, never at the first message. Mail in is a team's
mailbox records, each read by its own provider, never a setting."""

from __future__ import annotations

import httpx

from ops_service_kit.settings import Settings

from .graph import GraphSender, GraphToken
from .outbound import (
    FolderSender,
    MailNotConfiguredError,
    MailSender,
    ResendSender,
    SmtpSender,
    UnconfiguredSender,
)


class EmailProviders:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._clients: list[httpx.AsyncClient] = []
        self._transport = transport
        self._graph: tuple[httpx.AsyncClient, GraphToken] | None = None
        if settings.mail_provider == "graph":
            missing = [
                n for n in ("graph_tenant_id", "graph_client_id", "graph_client_secret") if not getattr(settings, n)
            ]
            if missing:
                raise MailNotConfiguredError(f"Microsoft Graph needs {', '.join('OPS_' + n.upper() for n in missing)}.")
        if settings.environment != "dev" and settings.mail_provider == "fake":
            raise MailNotConfiguredError("mail_provider 'fake' is for dev only; it writes mail to a folder.")
        self._sender = self._build_sender()

    @classmethod
    def from_settings(cls, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> EmailProviders:
        return cls(settings, transport=transport)

    def _client(self, base_url: str) -> httpx.AsyncClient:
        client = httpx.AsyncClient(base_url=base_url, timeout=30, transport=self._transport)
        self._clients.append(client)
        return client

    def _graph_parts(self) -> tuple[httpx.AsyncClient, GraphToken]:
        if self._graph is None:
            s = self.settings
            assert s.graph_tenant_id and s.graph_client_id and s.graph_client_secret
            http = self._client(s.graph_url)
            token = GraphToken(
                http,
                login_url=s.graph_login_url,
                tenant=s.graph_tenant_id,
                client_id=s.graph_client_id,
                secret=s.graph_client_secret.get_secret_value(),
                scope=f"{s.graph_url.rstrip('/')}/.default",
            )
            self._graph = (http, token)
        return self._graph

    def _build_sender(self) -> MailSender:
        s = self.settings
        if s.mail_provider == "none":
            return UnconfiguredSender()
        if not s.mail_from:
            raise MailNotConfiguredError(f"mail_provider '{s.mail_provider}' needs OPS_MAIL_FROM.")
        if s.mail_provider == "fake":
            return FolderSender(s.mail_fake_out_dir, s.mail_from)
        if s.mail_provider == "smtp":
            if not s.smtp_host:
                raise MailNotConfiguredError("mail_provider 'smtp' needs OPS_SMTP_HOST.")
            return SmtpSender(
                s.smtp_host,
                s.smtp_port,
                s.mail_from,
                username=s.smtp_username,
                password=s.smtp_password.get_secret_value() if s.smtp_password else None,
                starttls=s.smtp_starttls,
            )
        if s.mail_provider == "resend":
            if not s.resend_api_key:
                raise MailNotConfiguredError("mail_provider 'resend' needs OPS_RESEND_API_KEY.")
            return ResendSender(self._client(s.resend_url), s.resend_api_key.get_secret_value(), s.mail_from)
        http, token = self._graph_parts()
        return GraphSender(http, token, s.mail_from)

    def sender(self) -> MailSender:
        return self._sender

    async def aclose(self) -> None:
        for c in self._clients:
            await c.aclose()
