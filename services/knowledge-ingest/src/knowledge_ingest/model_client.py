# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The one way ingestion code reaches a model.

ADR-0008: every model call goes through the AI gateway, which holds the keys. Strategies receive a
`ModelClient` and never construct a provider client, so the ingestion key, the source's budget and
redaction by sensitivity (spec 14.14) are applied in one place. The production implementation calls
the AI gateway and is not part of this library; `knowledge_ingest.testing.FakeModelClient` is the
only implementation shipped here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        """Return the model's text for `prompt`, using the bank alias `alias`."""
        ...
