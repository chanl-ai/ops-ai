# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import pytest

from ops_files.repository import InMemoryFileRepository
from ops_files.scanning import EICAR
from ops_files.service import (
    DownloadTtlError,
    FileMissingError,
    FilesConfig,
    FileService,
    NotScannedError,
    QuarantinedError,
)
from tests.conftest import MAX_DOWNLOAD_SECONDS, RETENTION_CLASSES, Harness
from tests.support import upload

BODY = b"Fee schedule: annual fee 95.00\n"


def test_download_serves_the_uploaded_bytes(harness: Harness, service: FileService) -> None:
    """D1"""
    done = upload(service, harness, BODY, name="fees.pdf")
    status, content = harness.get(service.download_url(done.file.id, team="cards").url)
    assert (status, content) == (200, BODY)


def test_download_of_quarantined_file_refused(harness: Harness, service: FileService) -> None:
    """D2"""
    infected = upload(service, harness, b"attachment " + EICAR + b" trailer", name="invoice.pdf")
    assert infected.file.scan.status == "infected"
    with pytest.raises(QuarantinedError):
        service.download_url(infected.file.id, team="cards")
    # The asynchronous hook quarantines a file that was clean at upload.
    clean = upload(service, harness, BODY)
    service.add_reference(clean.file.id, team="cards", type="case", ref_id="case-1", name="Case 1")
    service.quarantine(clean.file.id, engine="clamav", detail="Win.Test.Signature")
    with pytest.raises(QuarantinedError):
        service.download_url(clean.file.id, team="cards")
    assert service.get(clean.file.id, team="cards").references[0].blocked == "Quarantined: Win.Test.Signature"


def test_download_before_scan_refused(harness: Harness) -> None:
    """D3"""
    config = FilesConfig(retention_classes=RETENTION_CLASSES, default_retention_class="standard")
    unscanned = FileService(harness.store, InMemoryFileRepository(), config)
    done = upload(unscanned, harness, BODY)
    assert done.file.scan.status == "pending"
    with pytest.raises(NotScannedError):
        unscanned.download_url(done.file.id, team="cards")


def test_cross_team_download_refused(harness: Harness, service: FileService) -> None:
    """D4"""
    done = upload(service, harness, BODY, team="cards")
    with pytest.raises(FileMissingError):
        service.download_url(done.file.id, team="lending")


def test_signed_get_lifetime_capped(harness: Harness, service: FileService) -> None:
    """D5"""
    done = upload(service, harness, BODY)
    with pytest.raises(DownloadTtlError):
        service.download_url(done.file.id, team="cards", expires_in=MAX_DOWNLOAD_SECONDS + 1)
    link = service.download_url(done.file.id, team="cards")
    # Read the lifetime from the signed URL itself, not from what the service says it asked for.
    assert harness.url_ttl(link.url) <= MAX_DOWNLOAD_SECONDS
