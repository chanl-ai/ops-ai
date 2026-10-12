# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Malware scanning contract. Production engines (ClamAV, Defender, ICAP) implement `Scanner`; this module
holds only the protocol and a fake that detects the EICAR test string."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ScanResult:
    status: Literal["clean", "infected", "failed"]
    engine: str
    detail: str | None = None


class Scanner(Protocol):
    @property
    def engine(self) -> str: ...

    def scan(self, chunks: Iterable[bytes]) -> ScanResult: ...


# Assembled from parts so this source file is not itself flagged by a scanner on a developer machine.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$" + b"H+H*"


class EicarScanner:
    """Finds the EICAR test string anywhere in the stream, including across chunk boundaries."""

    @property
    def engine(self) -> str:
        return "eicar-fake"

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        tail = b""
        for chunk in chunks:
            window = tail + chunk
            if EICAR in window:
                return ScanResult("infected", self.engine, "EICAR-Test-File")
            tail = window[-(len(EICAR) - 1) :]
        return ScanResult("clean", self.engine)
