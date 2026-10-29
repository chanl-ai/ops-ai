"""One check's outcome: PASS or FAIL with its reason, the settings it would write, and the secrets no line may show."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from deps_doctor import mask


@dataclass
class Result:
    item: str
    ok: bool
    reason: str
    # Settings to write when the check passed, by name.
    settings: dict[str, str] = field(default_factory=dict[str, str])
    # Values that must never be printed: passwords, keys, credentials in a URL.
    secrets: tuple[str, ...] = ()
    # What the person answered for this item; a second run keeps hand-edited values while it is unchanged.
    answer: str = ""

    def line(self) -> str:
        text = mask(f"{'PASS' if self.ok else 'FAIL'}  {self.item}: {self.reason}")
        for secret in self.secrets:
            if secret:
                # Whole words only, so a short dev password (`ops`) does not blank a database name (`ops_runtime`).
                before = r"(?<!\w)" if re.match(r"\w", secret) else ""
                after = r"(?!\w)" if re.search(r"\w$", secret) else ""
                text = re.sub(before + re.escape(secret) + after, "***", text)
        return text

    def answer_hash(self) -> str:
        return hashlib.sha256(self.answer.encode()).hexdigest()[:12]
