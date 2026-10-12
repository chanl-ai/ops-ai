# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Token approximation and sentence and word splitting.

Token counts are approximate: about one token per four characters, with every word costing at least
one. The real count comes from the embedding alias's tokenizer, reported by the AI gateway (spec
14.3); the splitter takes a counter so that one can be passed in once the gateway exposes it. Every
size decision in this package uses the same counter, so a chunk the splitter sized never measures
larger than `size` afterwards.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

TokenCounter = Callable[[str], int]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def word_tokens(word: str) -> int:
    return max(1, math.ceil((len(word) + 1) / 4))


def approx_tokens(text: str) -> int:
    return sum(word_tokens(w) for w in text.split())


def split_sentences(text: str) -> list[str]:
    """Split at sentence ends, keeping the punctuation with its sentence."""
    out: list[str] = []
    for block in text.split("\n"):
        out.extend(s.strip() for s in _SENTENCE_END.split(block) if s.strip())
    return out


def split_words_to_size(text: str, size: int, count: TokenCounter = approx_tokens) -> list[str]:
    """Split one over-long piece of text at word boundaries into pieces of at most `size` tokens."""
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = [*current, word]
        if current and count(" ".join(candidate)) > size:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current = candidate
    if current:
        pieces.append(" ".join(current))
    return pieces


def pack_sentences(text: str, size: int, overlap: int, count: TokenCounter = approx_tokens) -> list[str]:
    """Pack sentences into chunks of at most `size` tokens, carrying up to `overlap` tokens forward.

    A sentence longer than `size` is cut at word boundaries first, so no chunk exceeds `size`.
    """
    units: list[str] = []
    for sentence in split_sentences(text):
        if count(sentence) > size:
            units.extend(split_words_to_size(sentence, size, count))
        else:
            units.append(sentence)

    chunks: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and count(" ".join([*current, unit])) > size:
            chunks.append(" ".join(current))
            carried: list[str] = []
            for previous in reversed(current):
                if count(" ".join([previous, *carried])) > overlap:
                    break
                carried.insert(0, previous)
            current = carried
            # The carried overlap plus the next unit may not fit; drop overlap rather than exceed size.
            while current and count(" ".join([*current, unit])) > size:
                current.pop(0)
        current.append(unit)
    if current:
        chunks.append(" ".join(current))
    return chunks


def snake_case(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name.strip())
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    return s.strip("_").lower()
