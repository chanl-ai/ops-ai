"""The end-clean check on a finished answer: deterministic, no model call (kernel.py runs it after the loop).

Each defect is a phrase the correction prompt names, so the one correction call is told exactly what to fix.
"""

from __future__ import annotations

import re

from .context import cited_numbers

# An error code: an upper-case token joined by underscores (CONNECTION_NOT_LINKED, RATE_LIMITED), an upper-case word
# of five or more letters straight after "error", or one inside braces. A plain upper-case word, or an id with
# hyphens (CUS-1002, SYN-2026-0006), is not one.
_CODE = re.compile(
    r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"
    r"|\berror\b[\s:=\"'(]*(?P<after>[A-Z]{5,})\b"
    r"|\{[^{}]*\b(?P<braced>[A-Z]{5,})\b[^{}]*\}",
    re.IGNORECASE,
)
# What a reply must not end on: a bare acknowledgement after the answer's last sentence or on its own line (not
# "the review is done."), or a dangling separator.
_STRAY = re.compile(r"(?:^|[.!?]\s+|\n\s*)(ok|okay|done)[.!]?\s*$", re.IGNORECASE)
_DANGLING = (":", ",", ";", "(", "-", "\u2014", "\u2013")
# A platform record id (case_0eef29f68716, th_4148e7b2edcd, fil_ac70…): a short prefix, an underscore, hex.
_RECORD_ID = re.compile(r"\b[a-z]{2,8}_[0-9a-f]{8,}\b")
_QUESTION = re.compile(r"\?\s*\**\s*$")


def error_code(text: str) -> str | None:
    """The first error code the text repeats, or None."""
    for m in _CODE.finditer(text):
        token = m.group("after") or m.group("braced") or m.group(0)
        # The case-insensitive match is only for "error"; the code itself must be written in capitals.
        if token.isupper():
            return token
    return None


def stray_ending(text: str) -> str | None:
    """The stray word or separator the reply ends on, or None when it ends on a sentence or a table."""
    body = text.rstrip()
    if not body:
        return None
    if body.endswith(_DANGLING):
        return body[-1]
    found = _STRAY.search(body)
    # "Done." alone is an answer; only a trailing "ok" after the real answer is stray.
    if found and body[: found.start(1)].strip():
        return found.group(1)
    return None


def internal_name(text: str, tools: frozenset[str]) -> str | None:
    """The first record id or tool name the reply shows the person, or None. The card names the record."""
    if (found := _RECORD_ID.search(text)) is not None:
        return found.group(0)
    return next((t for t in sorted(tools) if re.search(rf"\b{re.escape(t)}\b", text)), None)


def ends_in_question(text: str) -> bool:
    return bool(_QUESTION.search(text.rstrip()))


def defects(
    text: str, *, needs_citation: bool, all_reads_succeeded: bool, tools: frozenset[str] = frozenset()
) -> list[str]:
    """What is wrong with a finished answer, as phrases for the correction prompt; empty when it is clean.

    `needs_citation`: the turn had knowledge passages and called no tool, so its facts come from the passages.
    `all_reads_succeeded`: the turn called tools, every one a read and every one ok, so a question back is one the
    tools could have answered. `tools`: the names the turn offered, none of which a reply may show."""
    found: list[str] = []
    if (code := error_code(text)) is not None:
        found.append(f"repeats an error code ({code}): say what happened in plain words and the next step, no code")
    if (name := internal_name(text, tools)) is not None:
        found.append(f"shows an internal name ({name}): name the record by its title and never a tool")
    if (tail := stray_ending(text)) is not None:
        found.append(f"ends on a stray {tail!r}: end on a full sentence")
    if all_reads_succeeded and ends_in_question(text):
        found.append("ends by asking the person something although every lookup succeeded: answer with what you found")
    if needs_citation and not cited_numbers(text):
        found.append(
            "uses the knowledge passages without citing them: cite each fact with its [n], or say plainly that the "
            "passages do not answer the question"
        )
    return found


def correction_prompt(found: list[str]) -> str:
    return (
        "Your reply " + "; and ".join(found) + ". Write the whole reply again with only that fixed, using only what "
        "you already found. Do not mention this check."
    )
