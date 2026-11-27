"""A paused Strands run as bytes the kernel stores opaquely (`Interrupt.history`), so any server can resume it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

LOOP = "strands"
# Raised when the snapshot's shape changes; a pause written under another version is refused, never half-read.
VERSION = 1


@dataclass(frozen=True)
class PausedRun:
    snapshot: dict[str, Any]
    interrupt_id: str
    tool_call_id: str


def encode(run: PausedRun) -> bytes:
    return json.dumps(
        {
            "loop": LOOP,
            "version": VERSION,
            "snapshot": run.snapshot,
            "interruptId": run.interrupt_id,
            "toolCallId": run.tool_call_id,
        }
    ).encode()


def decode(blob: bytes) -> PausedRun:
    data = json.loads(blob)
    if data.get("loop") != LOOP or data.get("version") != VERSION:
        raise ValueError(f"not a Strands pause of version {VERSION}")
    return PausedRun(data["snapshot"], data["interruptId"], data["toolCallId"])
