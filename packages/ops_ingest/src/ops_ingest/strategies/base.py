# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""State shared by the strategies during one split."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import cast

from ops_ingest.model_client import ModelBudget, ModelClient
from ops_ingest.models import IngestSettings, IngestStrategy, Paragraph, Section
from ops_ingest.text import TokenCounter, approx_tokens


@dataclass
class SplitContext:
    settings: IngestSettings
    title: str
    count: TokenCounter = approx_tokens
    model: ModelClient | None = None
    notes: list[str] = field(default_factory=list[str])
    model_calls: int = 0
    removed_chars: int = 0
    # Questions written before for a piece of the same text, by piece_digest: reused, never asked for again.
    known_questions: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # The run's ceiling on model calls; None for no ceiling (a preview's sample).
    budget: ModelBudget | None = None

    def call_model(self, prompt: str, *, max_tokens: int) -> str:
        """The model's reply; raises ModelBudgetSpent past the run's ceiling, or the client's ModelUnavailable."""
        if self.model is None:
            raise RuntimeError("An AI step ran without a model client")
        if self.budget is not None:
            self.budget.take()
        self.model_calls += 1
        return self.model.complete(prompt, alias=self.settings.model, max_tokens=max_tokens)

    def uses(self, strategy: IngestStrategy) -> bool:
        return strategy in self.settings.strategies


def section_text(section: Section, *, include_tables: bool) -> str:
    parts: list[str] = []
    for block in section.blocks:
        if isinstance(block, Paragraph):
            parts.append(block.text)
        elif include_tables:
            parts.append(block.as_text())
    return "\n".join(parts)


def json_object(text: str) -> dict[str, object] | None:
    """The first JSON object in a model reply, tolerating prose or code fences around it; `None` if there is none."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        data: object = json.loads(match.group(0))
    except ValueError:
        return None
    return cast(dict[str, object], data) if isinstance(data, dict) else None


def json_list(value: object) -> list[object] | None:
    return cast(list[object], value) if isinstance(value, list) else None
