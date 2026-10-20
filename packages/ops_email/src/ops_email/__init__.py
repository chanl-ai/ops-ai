# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Email in and out behind two protocols, `MailSource` and `MailSender`, with providers picked from settings
(`EmailProviders`). Holds no service's rules: a consumer decides what a message starts and what a send is for."""

from __future__ import annotations

from .graph import GraphMailSource, GraphSender, GraphToken, message_key, parse_item, references
from .imap import ImapMailSource, parse_message
from .inbound import (
    CursorRefusedError,
    DeltaPage,
    EmailFilter,
    IdleSource,
    InboundAttachment,
    InboundMessage,
    MailboxNotConfiguredError,
    MailSource,
    drain,
    normalise_message_id,
    text_at,
)
from .outbound import (
    FolderSender,
    MailNotConfiguredError,
    MailSender,
    MemorySender,
    OutboundAttachment,
    OutboundMessage,
    ResendSender,
    SmtpSender,
    UnconfiguredSender,
)
from .providers import EmailProviders

__all__ = [
    "CursorRefusedError",
    "DeltaPage",
    "EmailFilter",
    "EmailProviders",
    "FolderSender",
    "GraphMailSource",
    "GraphSender",
    "GraphToken",
    "IdleSource",
    "ImapMailSource",
    "InboundAttachment",
    "InboundMessage",
    "MailNotConfiguredError",
    "MailSender",
    "MailSource",
    "MailboxNotConfiguredError",
    "MemorySender",
    "OutboundAttachment",
    "OutboundMessage",
    "ResendSender",
    "SmtpSender",
    "UnconfiguredSender",
    "drain",
    "message_key",
    "normalise_message_id",
    "parse_item",
    "parse_message",
    "references",
    "text_at",
]
