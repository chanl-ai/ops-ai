"""Message keys from packages/ops_email stay as they were (c-187): every fixture message keys and threads exactly as
`v1_keys.json` records, written by the v1 mailbox adapter before it was retired. A key that changes would make a
redelivered message start a second run, since the Email received trigger dedupes runs by it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_email import parse_item

MAILBOX = Path(__file__).resolve().parents[1] / "fixtures" / "mailbox"


def test_every_fixture_message_keys_and_references_as_the_v1_adapter_did() -> None:
    expected: dict[str, list[dict[str, Any]]] = json.loads((MAILBOX / "v1_keys.json").read_text())
    for name, rows in expected.items():
        loaded: Any = json.loads((MAILBOX / name).read_text())
        items = cast(list[dict[str, Any]], loaded if isinstance(loaded, list) else [loaded])
        assert len(items) == len(rows)
        for item, row in zip(items, rows, strict=True):
            msg = parse_item(item)
            if row["key"] is None:
                assert msg.removed
                continue
            assert (msg.key, list(msg.references)) == (row["key"], row["references"])
