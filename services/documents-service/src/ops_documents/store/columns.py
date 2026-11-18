# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""How a row model reads a JSON column kept as text (database portability D5): `Annotated[T, JSON_TEXT]`."""

from __future__ import annotations

import json

from pydantic import BeforeValidator


def _loads(raw: object) -> object:
    """The column's text read as JSON, and empty text as none. A value that is not text is a row built in code with
    the value already in hand, so it is taken as it is."""
    if isinstance(raw, str):
        return json.loads(raw) if raw else None
    return raw


JSON_TEXT = BeforeValidator(_loads)
