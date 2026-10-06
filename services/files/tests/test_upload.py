# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import hashlib
import re

import pytest

from ops_files.service import (
    DigestMismatchError,
    FileMissingError,
    FileService,
    SizeMismatchError,
    TypeMismatchError,
)
from ops_files.storage.base import InvalidKeyError
from ops_files.storage.local import LocalObjectStore
from tests.conftest import Harness
from tests.support import ticket_for, upload

BODY = b"%PDF-1.7 card statement for October\n"


def test_upload_url_bound_to_its_key(harness: Harness, service: FileService) -> None:
    """U1"""
    harness.require_signatures()
    ticket = ticket_for(service, BODY)
    record = service.get(ticket.file_id, team="cards")
    assert record.storage is not None
    key = record.storage.key
    other = key.rsplit("/", 1)[0] + "/fil_other"
    status = harness.put(ticket.upload_url.replace(key, other), ticket.headers, BODY)
    assert status >= 400
    assert harness.store.head(other) is None


def test_upload_larger_than_declared_refused(harness: Harness, service: FileService) -> None:
    """U2"""
    ticket = ticket_for(service, BODY, size=10)
    status = harness.put(ticket.upload_url, ticket.headers, BODY)
    if status < 400:
        # The store accepted it (Azure Blob and moto cannot bind length); completion must catch it.
        with pytest.raises(SizeMismatchError):
            service.complete_upload(ticket.file_id, team="cards")
    record = service.get(ticket.file_id, team="cards")
    assert record.storage is not None
    assert harness.store.head(record.storage.key) is None


def test_upload_url_cannot_replace_completed_content(harness: Harness, service: FileService) -> None:
    """U3"""
    harness.require_signatures()
    ticket = ticket_for(service, BODY, digest=hashlib.sha256(BODY).hexdigest())
    assert harness.put(ticket.upload_url, ticket.headers, BODY) in (200, 201)
    done = service.complete_upload(ticket.file_id, team="cards")
    swapped = BODY.upper()
    assert len(swapped) == len(BODY)
    # Whoever reuses the URL leaves out the conditional header; only the signature or permission can stop it.
    reused = {k: v for k, v in ticket.headers.items() if k.lower() != "if-none-match"}
    assert harness.put(ticket.upload_url, reused, swapped) >= 400
    assert done.file.storage is not None
    assert b"".join(harness.store.iter_bytes(done.file.storage.key)) == BODY


def test_content_type_other_than_declared_refused(harness: Harness, service: FileService) -> None:
    """U4"""
    ticket = ticket_for(service, BODY, mime="application/pdf")
    headers = {**ticket.headers, "Content-Type": "text/html"}
    status = harness.put(ticket.upload_url, headers, BODY)
    if status < 400:
        with pytest.raises(TypeMismatchError):
            service.complete_upload(ticket.file_id, team="cards")
    record = service.get(ticket.file_id, team="cards")
    assert record.storage is not None
    assert harness.store.head(record.storage.key) is None


def test_digest_mismatch_detected(harness: Harness, service: FileService) -> None:
    """U5"""
    declared = hashlib.sha256(b"what the browser hashed").hexdigest()
    ticket = ticket_for(service, BODY, digest=declared)
    assert harness.put(ticket.upload_url, ticket.headers, BODY) in (200, 201)
    with pytest.raises(DigestMismatchError):
        service.complete_upload(ticket.file_id, team="cards")
    record = service.get(ticket.file_id, team="cards")
    assert record.storage is not None
    assert harness.store.head(record.storage.key) is None


def test_dedupe_never_crosses_teams(harness: Harness, service: FileService) -> None:
    """U6"""
    first = upload(service, harness, BODY, team="cards")
    second = upload(service, harness, BODY, team="lending")
    assert second.deduplicated is False
    assert second.file.id != first.file.id
    assert second.file.storage is not None
    assert second.file.storage.key.startswith("lending/")
    with pytest.raises(FileMissingError):
        service.get(first.file.id, team="lending")


def test_dedupe_within_team_reuses_object(harness: Harness, service: FileService) -> None:
    """U7"""
    first = upload(service, harness, BODY, name="a.pdf")
    ticket = ticket_for(service, BODY, name="b.pdf", digest=hashlib.sha256(BODY).hexdigest())
    pending = service.get(ticket.file_id, team="cards").storage
    assert pending is not None
    assert harness.put(ticket.upload_url, ticket.headers, BODY) in (200, 201)
    second = service.complete_upload(ticket.file_id, team="cards")
    assert second.deduplicated is True
    assert second.file.id == first.file.id
    assert harness.versions_left(pending.key) == 0


@pytest.mark.parametrize("name", ["../../../etc/passwd", "..\\..\\boot.ini", "a/../../b.pdf", "con\x00trol.pdf"])
def test_user_filename_never_in_storage_key(harness: Harness, service: FileService, name: str) -> None:
    """U8"""
    ticket = ticket_for(service, BODY, name=name, purpose="chat_attachment", mime="application/pdf")
    record = service.get(ticket.file_id, team="cards")
    assert record.storage is not None
    assert re.fullmatch(rf"cards/chat_attachment/\d{{4}}/\d{{2}}/{ticket.file_id}", record.storage.key)
    assert "/" not in record.name and "\\" not in record.name and "\x00" not in record.name
    with pytest.raises(InvalidKeyError):
        harness.store.presign_put("cards/../../etc/passwd", content_type="text/plain", max_bytes=1, expires_in=60)
    if isinstance(harness.store, LocalObjectStore):
        assert harness.put(ticket.upload_url, ticket.headers, BODY) == 200
        assert harness.store.path_of(record.storage.key).is_file()
