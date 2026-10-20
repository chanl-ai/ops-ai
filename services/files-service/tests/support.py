# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import hashlib

from ops_files.models import CompletedUpload, FilePurpose, UploadRequest, UploadTicket
from ops_files.service import FileService
from tests.conftest import Harness


def ticket_for(
    service: FileService,
    body: bytes,
    *,
    team: str = "cards",
    name: str = "statement.pdf",
    purpose: FilePurpose = "case_attachment",
    mime: str = "application/pdf",
    digest: str | None = None,
    size: int | None = None,
    retention_class: str | None = None,
) -> UploadTicket:
    request = UploadRequest(
        name=name,
        size=size if size is not None else len(body),
        mime=mime,
        purpose=purpose,
        digest=digest,
        retention_class=retention_class,
    )
    return service.create_upload(request, team=team, actor="analyst-1")


def upload(
    service: FileService,
    harness: Harness,
    body: bytes,
    *,
    team: str = "cards",
    name: str = "statement.pdf",
    purpose: FilePurpose = "case_attachment",
    retention_class: str | None = None,
) -> CompletedUpload:
    """Create a ticket, PUT the bytes to the presigned URL as a client would, and complete."""
    ticket = ticket_for(
        service,
        body,
        team=team,
        name=name,
        purpose=purpose,
        digest=hashlib.sha256(body).hexdigest(),
        retention_class=retention_class,
    )
    status = harness.put(ticket.upload_url, ticket.headers, body)
    assert status in (200, 201), f"{harness.name}: upload returned {status}"
    return service.complete_upload(ticket.file_id, team=team)
