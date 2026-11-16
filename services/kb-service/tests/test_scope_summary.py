"""A source's scope line reads as a count in plain words."""

from datetime import UTC, datetime

import pytest

from ops_kb.service import scope_summary
from ops_kb.store.knowledge import SourceRow

AT = datetime(2026, 1, 1, tzinfo=UTC)


def file_source(file_ids: list[str]) -> SourceRow:
    return SourceRow(
        id="src_1", team_id="team_ops", type="file", name="Files", collection="", owner="o", sensitivity="internal",
        status="active", tags=[], file_ids=file_ids, file_names=None, created_by="o", created_at=AT,
        last_sync_at=None, last_run_status=None, config=None, lease_until=None, lease_owner=None, settings=None,
        last_good_sync_at=None, failing_since=None, failures_in_row=0, db_now=AT, item_counts={},
    )  # fmt: skip


@pytest.mark.parametrize(("n", "want"), [(0, "0 uploaded files"), (1, "1 uploaded file"), (2, "2 uploaded files")])
def test_file_source_scope_counts_files(n: int, want: str) -> None:
    assert scope_summary(file_source(["f"] * n)) == want
