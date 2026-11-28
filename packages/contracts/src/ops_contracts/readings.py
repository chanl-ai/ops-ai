"""A file's shared reading as documents-service and its callers agree on it: the events that report its end, the key
each is posted under, and which pages a read with page or token limits keeps. documents-service writes the events and
trims its own reads with these; the workflow engine parks on the same key and trims Full text the same way."""

from __future__ import annotations

from collections.abc import Sequence

FINISHED = "reading.finished"
FAILED = "reading.failed"
# Characters counted as one token for maxTokens.
CHARS_PER_TOKEN = 4


def event_key(
    name: str, *, digest: str, reader_version: str, settings_key: str, file_id: str, described: int | None = None
) -> str:
    """The key a reading's end is posted under for one file holding its bytes: unique per file and outcome. A retry
    that describes more pages is posted again under the count of pages a model has described (`described`), which
    grows with every such retry, so each is its own event and one delivered twice keeps one key."""
    key = f"{name}:{digest}:{reader_version}:{settings_key}:{file_id}"
    return key if described is None else f"{key}:m{described}"


def within(
    pages: Sequence[tuple[int, str]], max_pages: int | None, max_tokens: int | None
) -> tuple[list[int], dict[str, int | bool]]:
    """The page numbers a read keeps of `pages` ((number, text) in any order): the first `max_pages`, then as many as
    fit under `max_tokens`. What it says about them: nothing when no limit cut a page, else `readPages`, and `partial`
    whenever a token ceiling was given."""
    numbers = sorted(n for n, _ in pages)
    texts = dict(pages)
    keep = numbers
    said: dict[str, int | bool] = {}
    if max_pages:
        keep = [n for n in keep if n <= max_pages]
    if max_tokens:
        budget, used, fits = max_tokens * CHARS_PER_TOKEN, 0, list[int]()
        for n in keep:
            used += len(texts[n])
            if used > budget:
                break
            fits.append(n)
        said["partial"] = len(fits) < len(keep)
        keep = fits
    if not said and len(keep) == len(numbers):
        return keep, {}
    said["readPages"] = len(keep)
    return keep, said
