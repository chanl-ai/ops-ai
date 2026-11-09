"""The environment's embedding width is refused at start-up when no vector index could hold it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ops_service_kit.settings import MAX_EMBEDDING_WIDTH, Settings


def test_a_width_wider_than_the_vector_index_stops_start_up() -> None:
    assert Settings(embedding_width=MAX_EMBEDDING_WIDTH).embedding_width == MAX_EMBEDDING_WIDTH
    with pytest.raises(ValidationError, match="at most 1998 dimensions"):
        Settings(embedding_width=3072)
