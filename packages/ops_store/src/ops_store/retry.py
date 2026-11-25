"""Full jitter for every retry wait: the engine's step and pass retries (ops_engine) and the outbox relay draw each
wait from [0, its span), so many callers that failed together do not try again together. A retry-after the other side
named is the floor."""

from __future__ import annotations

import random

# Draws the share of the span a wait takes. Tests replace it to pin each wait to its whole span.
jitter = random.random


def jittered(span: float, floor: float | None = None) -> float:
    """A wait drawn over `span`, never shorter than `floor`."""
    return max(span * jitter(), floor or 0.0)
