# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The one way ingestion code reaches a model.

ADR-0008: every model call goes through the AI gateway, which holds the keys. Strategies receive a
`ModelClient` and never construct a provider client, so the ingestion key, the source's budget and
redaction by sensitivity (spec 14.14) are applied in one place. The production implementation is
`ops_service_kit.model_calls.IngestModel`, on models-service; `ops_ingest.testing.FakeModelClient`
is the test double shipped here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        """Return the model's text for `prompt`, using the bank alias `alias`."""
        ...


class ModelUnavailable(Exception):
    """The model did not answer (down, out of budget, refused). An AI step stops asking and notes it; the pieces are
    indexed without what it would have added."""


class ModelBudgetSpent(Exception):
    """This run's ceiling on model calls is reached; an AI step stops asking and notes it."""


class ModelBudget:
    """A ceiling on model calls shared by every split of one run, so a large sync cannot spend without bound."""

    def __init__(self, calls: int) -> None:
        self.remaining = calls

    def take(self) -> None:
        if self.remaining <= 0:
            raise ModelBudgetSpent
        self.remaining -= 1
