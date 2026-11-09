"""Vectors with no model, for tests and the scripted provider: deterministic, so a test can predict which text is
nearest, and close for texts that share words or word parts, so a scripted meaning search behaves like a soft keyword
match. models-service's scripted provider answers with these, and a service's tests embed with them directly."""

from __future__ import annotations

import hashlib
import math
import re

# The width a scripted vector has when the caller names none: OpenAI's small embedding model's.
SCRIPTED_WIDTH = 1536
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    ]
)


def scripted_vector(text: str, width: int) -> list[float]:
    """A deterministic unit vector for `text`: each word's first six letters and its letter trigrams hashed into
    `width` signed buckets. Texts sharing words or word parts point the same way, so a scripted meaning search ranks
    "claims" near "claim" with no model, and a test can predict which passage is nearest."""
    v = [0.0] * width
    for word in _WORD.findall(text.lower()):
        if word in _STOP:
            continue
        padded = f"#{word}#"
        features = [(word[:6], 1.0)] + [(padded[i : i + 3], 0.3) for i in range(len(padded) - 2)]
        for feature, weight in features:
            h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
            v[h % width] += weight if h >> 63 else -weight
    norm = math.sqrt(sum(x * x for x in v))
    return [round(x / norm, 6) for x in v] if norm else v
