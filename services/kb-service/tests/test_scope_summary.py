"""A source's scope line reads as a count in plain words."""

import pytest

from ops_kb.service import scope_summary


@pytest.mark.parametrize(("n", "want"), [(0, "0 uploaded files"), (1, "1 uploaded file"), (2, "2 uploaded files")])
def test_file_source_scope_counts_files(n: int, want: str) -> None:
    assert scope_summary({"type": "file", "file_ids": ["f"] * n}) == want
