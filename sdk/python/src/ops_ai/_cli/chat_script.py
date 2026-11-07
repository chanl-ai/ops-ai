"""Scripted conversations: `ops chat script FILE` runs one; `ops chat evals DIR` runs every script in a folder as
each person it names and prints a scorecard (`make assistant-evals`, docs/usecases/chat/assistant/).

A script is YAML or JSON: `agent` (the team's default when left out), `test`, `kb` (knowledge bases by name or id),
`as` (the people `evals` runs it as), `real` (who runs it in the real-model subset), and `turns`, each `say` or
`connected: true` with `expect`. Expectations a reply is checked against:

    tool            a tool name, or a list of names, each called
    noTool          no tool called
    card            a Connect card shown (true) or not (false)
    says            words the reply holds
    never           words the reply must not hold
    credential      the first call signed in as team or person
    noQuestion      no sentence of the reply ends in "?"
    noErrorCode     no error code (CONNECTION_NOT_LINKED, "Error: ...") in the reply
    endsClean       the reply ends on a sentence or a table, not on a stray "ok" or a separator
    cites           the reply cites its knowledge: [n] the chat turned into citations, or the document a
                    search_knowledge passage came from, or its knowledge base
    table           the reply drew a table
    maxSteps        at most this many model calls answered the turn
    noRepeatCalls   no call reached a system twice with the same input (a repeat the kernel answered is marked)
    noInternalIds   no record id (case_0eef29f68716) or snake_case name (find_cases, waiting_on_customer) in the reply
    noControls      the reply names no button or other control to press: the cards show their own
"""

from __future__ import annotations

import argparse
import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._io import load_data

from .common import client, short

QUESTION = re.compile(r"\?(?=[\s*_)\]\"']|$)")
CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\bError:")
STRAY = re.compile(r"(?:^|[.!?]\s+|\n\s*)(ok|okay|done)[.!]?\s*$", re.IGNORECASE)
CITE = re.compile(r"\[\d+\]")
# What a sentence or a table may end on, closing quotes included ("... from \u201cthe policy.\u201d").
RECORD_ID = re.compile(r"\b[a-z]{2,8}_[0-9a-f]{8,}\b|\b[a-z]+(?:_[a-z]+)+\b")
CONTROL = re.compile(r"\b(press|click|tap|buttons?)\b", re.IGNORECASE)
ENDINGS = (".", "!", "?", ")", "]", "*", "|", '"', "'", "\u201d", "\u2019", "\u00bb")


@dataclass
class Outcome:
    """One script run: whether every check passed, the model calls its turns used and the conversation."""

    ok: bool
    calls: int
    thread: str
    failed: list[str] = field(default_factory=list[str])


def ends_clean(text: str) -> bool:
    body = text.rstrip()
    if not body:
        return False
    stray = STRAY.search(body)
    return body.endswith(ENDINGS) and not (stray and body[: stray.start(1)].strip())


def reply_checks(want: dict[str, Any], seen: dict[str, Any], message: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Each expectation in `want` as (name, passed, what was seen instead), for the reply `seen` streamed and the
    stored `message` the chat reads back (its model calls, citations and drawn parts)."""
    text: str = seen["text"]
    names = [c.get("name") for c in seen["tools"]]
    out: list[tuple[str, bool, str]] = []
    wanted = want.get("tool")
    for tool in [wanted] if isinstance(wanted, str) else list(wanted or []):
        out.append((f"calls {tool}", tool in names, f"called {names or 'nothing'}"))
    if want.get("noTool"):
        out.append(("calls no tool", not names, f"called {names}"))
    if "card" in want:
        shown = "shown" if want["card"] else "not shown"
        out.append((f"Connect card {shown}", bool(seen["cards"]) == want["card"], f"{seen['cards']}"))
    for s in want.get("says", []):
        out.append((f"reply says {s!r}", s.lower() in text.lower(), short(text, 200)))
    for s in want.get("never", []):
        out.append((f"reply never says {s!r}", s.lower() not in text.lower(), short(text, 200)))
    if want.get("noQuestion"):
        out.append(("asks nothing back", QUESTION.search(text) is None, short(text, 200)))
    if want.get("noErrorCode"):
        code = CODE.search(text)
        out.append(("no error code", code is None, code.group(0) if code else ""))
    if want.get("endsClean"):
        out.append(("ends clean", ends_clean(text), repr(text[-40:])))
    if want.get("cites"):
        # [n] the chat turned into citations, or the document a search_knowledge passage of this turn came from.
        found = [
            str(p.get(k))
            for c in seen["tools"]
            for p in _passages(c)
            for k in ("title", "section", "knowledgeBase")
            if p.get(k)
        ]
        named = [f for f in found if f.lower() in text.lower()]
        cited = (bool(message.get("citations")) and CITE.search(text) is not None) or bool(named)
        out.append(("cites the knowledge", cited, f"citations {len(message.get('citations') or [])}, found {found}"))
    if want.get("table"):
        drawn = [p for p in message.get("parts") or [] if p.get("shape") in ("rows", "table")]
        out.append(("draws a table", bool(drawn), f"parts {[p.get('shape') for p in message.get('parts') or []]}"))
    if want.get("noRepeatCalls"):
        sent = [
            (c.get("name"), repr(c.get("input")))
            for c in seen["tools"]
            if not (isinstance(c.get("output"), dict) and "repeatOf" in c["output"])
        ]
        twice = sorted({k for k in sent if sent.count(k) > 1})
        out.append(("no call sent twice", not twice, f"{twice}"))
    if want.get("noInternalIds"):
        found = RECORD_ID.search(text)
        out.append(("no internal id or name", found is None, found.group(0) if found else ""))
    if want.get("noControls"):
        found = CONTROL.search(text)
        out.append(("names no control", found is None, short(text, 200)))
    if "maxSteps" in want:
        calls = int((message.get("usage") or {}).get("calls") or 0)
        out.append((f"at most {want['maxSteps']} steps", 0 < calls <= int(want["maxSteps"]), f"{calls} model calls"))
    return out


def _passages(call: dict[str, Any]) -> list[dict[str, Any]]:
    output = call.get("output")
    if call.get("name") != "search_knowledge" or not isinstance(output, dict):
        return []
    return [p for p in output.get("passages") or [] if isinstance(p, dict)]


def last_reply(ops: OpsAI, thread: str) -> dict[str, Any]:
    messages = [m for m in ops.chat.get(thread).get("messages") or [] if m.get("role") == "assistant"]
    return messages[-1] if messages else {}


def kb_ids(ops: OpsAI, wanted: list[str] | None) -> list[str] | None:
    """Knowledge bases by id or name: ids differ on every install, so a script names a base."""
    if not wanted:
        return None
    found = ops.raw.kb.knowledge_bases_list_knowledge_bases(page_size=100)
    rows: list[dict[str, Any]] = found if isinstance(found, list) else list(found.get("data") or [])
    by = {str(r["id"]): str(r["id"]) for r in rows} | {str(r["name"]).lower(): str(r["id"]) for r in rows}
    missing = [w for w in wanted if w not in by and w.lower() not in by]
    if missing:
        raise ValueError(f"no knowledge base {', '.join(missing)} for this person")
    return [by.get(w) or by[w.lower()] for w in wanted]


def run_script(ns: argparse.Namespace, ops: OpsAI, path: Path) -> Outcome:
    """One scripted conversation; prints each turn and PASS or FAIL per check."""
    from .chat import check, followup, line, start_thread, turn  # noqa: PLC0415 - chat imports this module

    spec = load_data(path)
    ns.agent, ns.test, ns.thread = spec.get("agent"), spec.get("test", False), None
    ns.kb = kb_ids(ops, spec.get("kb"))
    first = next((str(t["say"]) for t in spec["turns"] if t.get("say")), path.stem)
    thread, card, calls, failed = start_thread(ns, ops, first), None, 0, list[str]()
    for t in spec["turns"]:
        seen = turn(ns, ops, thread, t.get("say") or followup((card or {}).get("connection") or "the app"))
        card = seen["cards"][-1] if seen["cards"] else card
        message = last_reply(ops, thread)
        calls += int((message.get("usage") or {}).get("calls") or 0)
        want = t.get("expect", {})
        results = reply_checks(want, seen, message)
        if "credential" in want:
            from .chat import calls as call_log  # noqa: PLC0415

            used = [r.get("credential") for r in call_log(ops, thread)]
            results.append(
                (f"signed in as {want['credential']}", bool(used) and used[0] == want["credential"], f"{used}")
            )
        results.append(("no error", not seen["error"], str(seen["error"])))
        for name, passed, why in results:
            check(ns, name, passed, why)
            if not passed:
                failed.append(name)
    line(ns, f"\n{'PASS' if not failed else 'FAIL'} {path.name}  {thread}")
    return Outcome(not failed, calls, thread, failed)


def evals(ns: argparse.Namespace, folder: Path, *, real: bool, max_calls: int, only: list[str] | None = None) -> int:
    """Every script in `folder` as each person it names (`as`, else this command's own --as), then a scorecard. With
    `real`, only each script's `real` people, and a script starts only while the model calls already spent plus its
    turns' maxSteps stay within `max_calls`."""
    from .chat import line  # noqa: PLC0415

    rows: list[tuple[str, str, str, int, str]] = []
    spent = 0
    for path in sorted(folder.glob("*.y*ml")):
        if only and path.stem not in only:
            continue
        spec = load_data(path)
        people: list[str] = list(spec.get("real") or []) if real else list(spec.get("as") or [ns.as_role])
        for person in people:
            budget = sum(int((t.get("expect") or {}).get("maxSteps") or 1) for t in spec["turns"])
            if real and spent + budget > max_calls:
                rows.append((path.stem, person, "SKIP", 0, f"would pass {max_calls} model calls"))
                continue
            who = copy.copy(ns)
            who.as_role = person
            line(ns, f"\n=== {path.stem} as {person}")
            done = run_script(who, client(who), path)
            spent += done.calls
            rows.append((path.stem, person, "PASS" if done.ok else "FAIL", done.calls, done.thread))
    line(ns, "\nscript               person                               result  calls  thread")
    for script, person, result, used, where in rows:
        line(ns, f"{script:<20} {person:<36} {result:<7} {used:>5}  {where}")
    passed = sum(1 for r in rows if r[2] == "PASS")
    line(ns, f"\n{passed} of {len(rows)} passed, {spent} model calls" + (f" (cap {max_calls})" if real else ""))
    over = real and spent > max_calls
    if over:
        line(ns, f"FAIL: the real subset used {spent} model calls, over its cap of {max_calls}")
    return 0 if passed == len(rows) and not over else 1
