"""A conversation as Markdown to paste: who chatted with which agent on which model, then each turn as the person's
message, one line of the steps the agent took (each tool in words, its key argument, what came back, whose sign-in
it used, and a mark when it failed or was refused), the reply, and one line per card or table. It reads what the
chat screen reads (the thread, its call log and the person), and prints no ids but the thread's."""

from __future__ import annotations

import textwrap
from typing import Any, cast

from ops_ai._chat import connect_card

WIDTH = 100
REFUSED = ("deny", "denied", "refused", "blocked")


def _wrap(text: str) -> str:
    """Each paragraph wrapped at word boundaries; a word longer than a line stays whole."""
    paragraphs = [p.strip() for p in str(text or "").split("\n")]
    return "\n".join(
        textwrap.fill(p, WIDTH, break_long_words=False, break_on_hyphens=False) if p else "" for p in paragraphs
    ).strip()


def _words(value: Any, n: int = 60) -> str:
    """A value on one line, shortened at a word boundary."""
    text = " ".join(str(value).split())
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def _argument(args: Any) -> str:
    """The call's key argument: its first text value, else its first value, as `name value`."""
    if not isinstance(args, dict) or not args:
        return ""
    items = list(cast(dict[str, Any], args).items())
    key, value = next(((k, v) for k, v in items if isinstance(v, str) and v), items[0])
    return f" ({key.replace('_', ' ')} {_words(str(value).replace('_', ' '), 40)})"


def _result(call: dict[str, Any]) -> str:
    out = call.get("output")
    if isinstance(out, dict):
        out = cast(dict[str, Any], out)
        for key in ("summary", "text", "message", "answer"):
            if out.get(key):
                return _words(out[key])
        for key in ("records", "rows", "items", "data", "results"):
            if isinstance(out.get(key), list):
                return f"{len(out[key])} rows"
        return "done"
    if isinstance(out, list):
        return f"{len(out)} rows"
    return _words(out) if out else "no result"


def _error(call: dict[str, Any]) -> str:
    out = call.get("output")
    err = out.get("error") if isinstance(out, dict) else None
    if isinstance(err, dict):
        err = err.get("error") if isinstance(err.get("error"), dict) else err
        return _words(err.get("message") or err.get("code") or "error")
    return _words(err or "error")


def _signed_in(call: dict[str, Any], row: dict[str, Any] | None, person: str) -> str:
    """Whose sign-in the call used: the call log's, or the person's own for Ops AI's tools, which act with their
    access and reach no app."""
    if row and row.get("credential"):
        return " · as the team" if row["credential"] == "team" else f" · as {person}"
    return f" · as {person}" if call.get("server") == "ops" else ""


def step(call: dict[str, Any], row: dict[str, Any] | None, person: str) -> str:
    """One tool call in words."""
    name = str(call.get("label") or call.get("name") or "a tool")
    where = f"{name}{_argument(call.get('input'))}"
    if card := connect_card(call):
        return f"{where} → refused: connect {card.get('connection') or 'the app'} first"
    refused = row is not None and str(row.get("decision") or "").lower() in REFUSED
    if refused:
        return f"{where} → refused: {_words(row.get('reason') or row.get('outcome') or 'not allowed')}"
    if call.get("status") in ("failed", "error"):
        return f"{where} → failed: {_error(call)}{_signed_in(call, row, person)}"
    return f"{where} → {_result(call)}{_signed_in(call, row, person)}"


def _count(data: Any) -> str:
    if isinstance(data, list):
        return f"{len(data)} rows"
    if isinstance(data, dict):
        rows = cast(dict[str, Any], data).get("rows") or cast(dict[str, Any], data).get("items")
        if isinstance(rows, list):
            return f"{len(rows)} rows"
    return ""


def shown(message: dict[str, Any]) -> list[str]:
    """Each card or table the reply drew, as `kind: title (n rows)`."""
    lines = []
    for part in message.get("parts") or []:
        if not isinstance(part, dict) or part.get("type") in ("text", "markdown"):
            continue
        hint = part.get("hint") or {}
        kind = "table" if part.get("shape") == "rows" else str(part.get("shape") or part.get("type") or "card")
        title = hint.get("title") or part.get("title") or kind.capitalize()
        count = _count(part.get("data") if "data" in part else part.get("rows"))
        lines.append(f"{kind}: {title}" + (f" ({count})" if count else ""))
    for w in message.get("widgets") or []:
        count = _count(w.get("rows"))
        title = w.get("title") or str(w.get("kind") or "card").capitalize()
        lines.append(f"{w.get('kind') or 'card'}: {title}" + (f" ({count})" if count else ""))
    return lines


def turns(thread: dict[str, Any]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Each person's message with the replies that followed it."""
    out: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for m in thread.get("messages") or []:
        if m.get("role") == "user":
            out.append((m, []))
        elif out:
            out[-1][1].append(m)
    return out


def _stats(replies: list[dict[str, Any]]) -> str:
    calls = sum(int((r.get("usage") or {}).get("calls") or 0) for r in replies)
    tools = sum(len(r.get("toolCalls") or []) for r in replies)
    seconds = sum(float((r.get("usage") or {}).get("seconds") or 0) for r in replies)
    return f"{_n(calls, 'model call')}, {_n(tools, 'tool call')}, {seconds:.1f} s"


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def transcript(
    thread: dict[str, Any], *, person: str, team: str, log: list[dict[str, Any]], all_turns: bool = False
) -> str:
    """The Markdown transcript; the last turn unless `all_turns`."""
    every = turns(thread)
    first = 0 if all_turns else max(len(every) - 1, 0)
    replies = [r for _, rs in every for r in rs]
    model = next((r.get("model") for r in reversed(replies) if r.get("model")), None) or "-"
    stats = "; ".join(f"turn {i + 1}: {_stats(rs)}" for i, (_, rs) in enumerate(every) if i >= first)
    lines = [
        f"**{_words(thread.get('title') or 'Chat', 80)}** · thread {thread.get('id')}",
        f"{person} ({team}) with {thread.get('agentName') or 'the agent'} on `{model}` · {stats or 'no replies'}",
    ]
    # The call log names no tool-call ids, so each call takes the next logged row for its tool, oldest first.
    queue: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(log, key=lambda r: str(r.get("at") or "")):
        queue.setdefault(str(row.get("target") or ""), []).append(row)
    for i, (message, rs) in enumerate(every):
        calls = [c for r in rs for c in r.get("toolCalls") or []]
        logged = [_next(queue, str(c.get("name"))) for c in calls]
        if i < first:
            continue
        lines += ["", _wrap(f"**Person:** {message.get('content') or ''}")]
        if calls:
            steps = "; ".join(step(c, row, person) for c, row in zip(calls, logged, strict=True))
            lines += ["", f"<sub>Steps: {steps}</sub>"]
        for r in rs:
            lines += ["", _wrap(f"**Assistant:** {r.get('content') or r.get('error') or '(no reply)'}")]
            lines += [f"- {s}" for s in shown(r)]
        if not rs:
            lines += ["", "**Assistant:** (no reply yet)"]
    return "\n".join(lines)


def _next(queue: dict[str, list[dict[str, Any]]], tool: str) -> dict[str, Any] | None:
    rows = queue.get(tool)
    return rows.pop(0) if rows else None
