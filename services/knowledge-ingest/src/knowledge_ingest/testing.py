# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Test doubles. `FakeModelClient` records every call so tests can assert what reached the model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelCall:
    prompt: str
    alias: str
    max_tokens: int


@dataclass
class FakeModelClient:
    """Answers each prompt with `respond(prompt)`, or with the next scripted reply."""

    replies: list[str] = field(default_factory=list[str])
    respond: Callable[[str], str] | None = None
    calls: list[ModelCall] = field(default_factory=list[ModelCall])

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        self.calls.append(ModelCall(prompt=prompt, alias=alias, max_tokens=max_tokens))
        if self.respond is not None:
            return self.respond(prompt)
        if not self.replies:
            raise AssertionError("FakeModelClient ran out of scripted replies")
        return self.replies.pop(0)
