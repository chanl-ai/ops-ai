# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ops_files.service import (
    FileHeldError,
    FileReferencedError,
    FileRetainedError,
    FileService,
    RetentionChangeError,
)
from ops_files.storage.base import ObjectExistsError, ObjectLockedError, RetentionShortenError
from tests.conftest import Harness
from tests.support import upload

BODY = b"Signed loan agreement, page 1\n"


def test_delete_while_referenced_refused(harness: Harness, service: FileService) -> None:
    """L1"""
    done = upload(service, harness, BODY, retention_class="standard")
    service.add_reference(done.file.id, team="cards", type="case", ref_id="case-9", name="Case 9")
    with pytest.raises(FileReferencedError):
        service.delete(done.file.id, team="cards")
    service.remove_reference(done.file.id, team="cards", type="case", ref_id="case-9")
    service.delete(done.file.id, team="cards")


def test_delete_while_held_refused(harness: Harness, service: FileService) -> None:
    """L2"""
    harness.require_worm()
    done = upload(service, harness, BODY, retention_class="standard")
    service.set_legal_hold(done.file.id, team="cards", on=True, by="legal-1", reason="Litigation 2026-14")
    with pytest.raises(FileHeldError):
        service.delete(done.file.id, team="cards")
    assert done.file.storage is not None
    # Storage refuses as well, so a caller that skips the service cannot delete held bytes.
    with pytest.raises(ObjectLockedError):
        harness.store.delete(done.file.storage.key)


def test_delete_within_retention_refused(harness: Harness, service: FileService) -> None:
    """L3"""
    done = upload(service, harness, BODY, retention_class="case-7y")
    with pytest.raises(FileRetainedError):
        service.delete(done.file.id, team="cards")


def test_retention_not_shortened_on_locked_file(harness: Harness, service: FileService) -> None:
    """L4"""
    harness.require_worm()
    done = upload(service, harness, BODY, purpose="evidence_bundle", retention_class="evidence-10y")
    assert done.file.immutable is True
    for weaker in ("evidence-1y", "standard"):
        with pytest.raises(RetentionChangeError):
            service.set_retention(done.file.id, team="cards", class_id=weaker)
    assert service.get(done.file.id, team="cards").retention.class_id == "evidence-10y"


def test_storage_refuses_shorter_retention(harness: Harness, service: FileService) -> None:
    """L5"""
    harness.require_worm()
    done = upload(service, harness, BODY, purpose="evidence_bundle", retention_class="evidence-10y")
    assert done.file.storage is not None
    key = done.file.storage.key
    info = harness.store.head(key)
    assert info is not None and info.retention_until is not None
    with pytest.raises(RetentionShortenError):
        harness.store.set_retention(key, datetime.now(UTC) + timedelta(days=30), "compliance")
    with pytest.raises(RetentionShortenError):
        harness.store.set_retention(key, info.retention_until + timedelta(days=1), "governance")


def test_delete_removes_every_version(harness: Harness, service: FileService) -> None:
    """L6"""
    done = upload(service, harness, BODY, retention_class="standard")
    assert done.file.storage is not None
    service.delete(done.file.id, team="cards")
    assert harness.versions_left(done.file.storage.key) == 0


def test_copy_never_overwrites(harness: Harness, service: FileService) -> None:
    """L7"""
    first = upload(service, harness, BODY, retention_class="standard")
    second = upload(service, harness, BODY + b"page 2\n", retention_class="standard")
    assert first.file.storage is not None and second.file.storage is not None
    with pytest.raises(ObjectExistsError):
        harness.store.copy(first.file.storage.key, second.file.storage.key)
    assert b"".join(harness.store.iter_bytes(second.file.storage.key)) == BODY + b"page 2\n"
