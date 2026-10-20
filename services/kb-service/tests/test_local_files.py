"""The local file store keeps reading what it stored before c-094 (the files-service library's layout: a StoredFile
record with `storage.key`, the bytes at `objects/data/<key>`), so a stack that has not moved to files-service still
syncs its sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ops_kb.files import FileMissing, KnowledgeFiles

from .pdfs import RATES


def old_layout(root: Path, file_id: str, team: str, data: bytes) -> None:
    key = f"{team}/knowledge_source/2026/10/{file_id}"
    (root / "objects" / "data" / key).parent.mkdir(parents=True)
    (root / "objects" / "data" / key).write_bytes(data)
    (root / "records").mkdir(parents=True)
    record = {
        "id": file_id,
        "name": "rates.pdf",
        "mime": "application/pdf",
        "size": len(data),
        "digest": hashlib.sha256(data).hexdigest(),
        "team": team,
        "status": "available",
        "purpose": "knowledge_source",
        "storage": {"backend": "local", "container": "files", "key": key},
    }
    (root / "records" / f"{file_id}.json").write_text(json.dumps(record))


async def test_a_file_stored_in_the_old_layout_is_read_and_reused(tmp_path: Path) -> None:
    old_layout(tmp_path, "fil_0136d014cdf14bef", "team_ops", RATES)
    files = KnowledgeFiles(tmp_path)
    assert await files.read("local", "team_ops", "fil_0136d014cdf14bef") == ("rates.pdf", "application/pdf", RATES)
    again = await files.put("local", "team_ops", RATES, name="rates-copy.pdf", mime="application/pdf", actor="james")
    assert (again.file_id, again.deduplicated) == ("fil_0136d014cdf14bef", True)
    with pytest.raises(FileMissing):
        await files.read("local", "team_security", "fil_0136d014cdf14bef")


async def test_a_new_upload_is_read_back_in_the_digest_layout(tmp_path: Path) -> None:
    files = KnowledgeFiles(tmp_path)
    stored = await files.put("local", "team_ops", RATES, name="rates.pdf", mime="application/pdf", actor="james")
    assert (tmp_path / "blobs" / stored.digest).exists()
    assert await files.read("local", "team_ops", stored.file_id) == ("rates.pdf", "application/pdf", RATES)
