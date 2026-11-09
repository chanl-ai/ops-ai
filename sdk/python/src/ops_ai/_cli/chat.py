"""`opsai chat`: chat with an agent as the chat screen does. A reply streams as it arrives, with each tool call, widget
and Connect card printed under it; the call log under the chat says whose sign-in each tool call used.

    opsai chat say --agent "Case helper" --test -m "Status of case 00001026?"
    opsai chat say --thread th_x -m "And its owner?"
    opsai chat say --connector GitHub -m "Open issues?"   # a new chat with only GitHub on
    opsai chat connected th_x Salesforce        # the Connect card's follow-up, once the person has signed in
    opsai chat approve th_x                     # the newest open approval widget; reject needs --reason
    opsai chat script docs/usecases/chat/salesforce-case-helper.yaml
    opsai chat evals docs/usecases/chat/assistant [--real]   # every script as its people; a scorecard (chat_script.py)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._chat import action_body, connect_card

from .chat_script import evals, run_script
from .common import MARK, client, console_url, emit, marked, parser, refuse, short, table, testing, values, verb_options
from .transcript import transcript


def main(argv: list[str]) -> int:
    ap = parser("opsai chat", "Chat with agents through the chat screen's routes.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("agents", parents=common, help="the agents New chat offers")
    threads = sub.add_parser("threads", parents=common, help="your conversations, newest first")
    threads.add_argument("--search")
    start = sub.add_parser("start", parents=common, help="start a conversation")
    _start_options(start)
    say = sub.add_parser("say", parents=common, help="send messages and stream each reply; starts a thread if none")
    _start_options(say)
    say.add_argument("--thread", help="continue this conversation")
    say.add_argument("-m", "--message", action="append", default=[])
    say.add_argument("--connected", metavar="APP", help="then send the Connect card's follow-up for APP")
    for name, text in (("show", "the conversation as the chat reads it"), ("calls", "its tool-call log")):
        sub.add_parser(name, parents=common, help=text).add_argument("thread")
    done = sub.add_parser("connected", parents=common, help="the Connect card's follow-up after signing in")
    done.add_argument("thread")
    done.add_argument("app", nargs="?", help="the app named on the card; the newest card's when left out")
    for name in ("approve", "reject", "submit"):
        act = sub.add_parser(name, parents=common, help=f"{name} a widget in the conversation")
        act.add_argument("thread")
        act.add_argument("widget", nargs="?", help="the widget's id; the newest open one when left out")
        if name == "reject":
            act.add_argument("--reason", required=True)
        if name == "submit":
            act.add_argument("--value", action="append", metavar="FIELD=VALUE", default=[])
    tr = sub.add_parser("transcript", parents=common, help="the conversation as Markdown to paste")
    tr.add_argument("--thread", required=True)
    tr.add_argument("--all-turns", action="store_true", help="every turn; the last one when left out")
    trs = sub.add_parser("transcripts", parents=common, help="a transcript of each of your matching conversations")
    trs.add_argument("--search", default=MARK.strip(), help="text the title holds (default: the test-data mark)")
    trs.add_argument("--all-turns", action="store_true")
    script = sub.add_parser("script", parents=common, help="a scripted conversation, PASS or FAIL per turn")
    script.add_argument("file")
    ev = sub.add_parser("evals", parents=common, help="every script in a folder as the people each names; a scorecard")
    ev.add_argument("folder")
    ev.add_argument("--real", action="store_true", help="only each script's real-model people, within --max-calls")
    ev.add_argument("--max-calls", type=int, default=10, help="model calls the real subset may spend (default 10)")
    ev.add_argument(
        "--only", action="append", metavar="SCRIPT", help="run only this script (its file name); repeatable"
    )
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except Exception as exc:
        return refuse(exc)


def _start_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--agent", help="the agent's id, slug or name; the team's default when left out")
    p.add_argument("--kb", action="append", help="a knowledge base to answer from (repeatable)")
    p.add_argument("--test", action="store_true", help="the agent page's Test panel: its newest version")
    p.add_argument(
        "--connector",
        "--connectors",
        dest="connector",
        action="append",
        metavar="APP",
        help="use only these connectors in the new chat, by name or id (repeatable, or comma-separated); "
        "the others are off for it",
    )


def _dispatch(ns: argparse.Namespace) -> int:
    if ns.verb == "evals":
        # Each script signs in as its own people, so no one client serves the whole run.
        return evals(ns, Path(ns.folder), real=ns.real, max_calls=ns.max_calls, only=ns.only)
    ops = client(ns)
    if ns.verb == "agents":
        return table(ns, ops.chat.agents(), "id", "name", "role")
    if ns.verb == "threads":
        return table(ns, ops.chat.threads(search=ns.search), "id", "title", "agentName", "lastMessageAt")
    if ns.verb == "start":
        return _say(ns, ops, [])
    if ns.verb == "say":
        if not ns.message and not ns.connected:
            raise ValueError("opsai chat say: give a message (-m) or --connected APP")
        return _say(ns, ops, [*ns.message, *([followup(ns.connected)] if ns.connected else [])])
    if ns.verb == "show":
        return _show(ns, ops.chat.get(ns.thread))
    if ns.verb == "calls":
        return table(ns, calls(ops, ns.thread), "title", "outcome", "credential", "actingFor", "latencyMs")
    if ns.verb == "connected":
        app = ns.app or (last_card(ops.chat.get(ns.thread)) or {}).get("connection") or "the app"
        seen = turn(ns, ops, ns.thread, followup(app))
        return 1 if seen["error"] else 0
    if ns.verb in ("approve", "reject", "submit"):
        message, widget = _widget(ops.chat.get(ns.thread), ns.widget)
        body = action_body(ns.verb, reason=getattr(ns, "reason", None), values=values(getattr(ns, "value", None)))
        done = ops.chat.act(ns.thread, message, widget, body)
        return emit(ns, done, text=f"{widget} {done.get('state', '')} {short(done.get('result') or '', 120)}".strip())
    if ns.verb == "transcript":
        return emit(ns, {"thread": ns.thread}, text=_transcript(ops, ns.thread, ns.all_turns))
    if ns.verb == "transcripts":
        found = [t for test in (False, True) for t in ops.chat.threads(pageSize=100, test=test)]
        hits = [t for t in found if ns.search.lower() in str(t.get("title") or "").lower()]
        texts = [_transcript(ops, str(t["id"]), ns.all_turns) for t in hits]
        return emit(ns, [t["id"] for t in hits], text="\n\n---\n\n".join(texts) or "(no matching conversations)")
    if ns.verb == "script":
        return 0 if run_script(ns, ops, Path(ns.file)).ok else 1
    return 2


def _transcript(ops: OpsAI, thread: str, all_turns: bool) -> str:
    me = ops.raw.platform.me_me()
    team = next((t["name"] for t in me.get("teams") or [] if t.get("id") == ops.config.team), ops.config.team or "-")
    return transcript(
        ops.chat.get(thread), person=me["user"]["name"], team=team, log=calls(ops, thread), all_turns=all_turns
    )


def followup(app: str) -> str:
    """The message the Connect card sends once its window says the person is connected."""
    return f"I connected {app}. Please go ahead."


def agent_id(ops: OpsAI, name: str | None, *, test: bool) -> str | None:
    """The agent by id, slug or name: from New chat's list, or for a test from the Agents page's, which holds agents
    never published."""
    if not name:
        return None
    agents = list(ops.agents.list(page_size=100)) if test else ops.chat.agents()
    wanted = name.lower()
    hits = [
        a
        for a in agents
        if wanted in (str(a.get("id")), str(a.get("slug", "")).lower(), str(a.get("name", "")).lower())
    ]
    if len(hits) != 1:
        names = ", ".join(f"{a.get('name')} ({a.get('id')})" for a in agents)
        raise ValueError(f"--agent {name} matches {len(hits)} of the agents this person may chat with: {names}")
    return str(hits[0]["id"])


def start_thread(ns: argparse.Namespace, ops: OpsAI, first: str | None = None) -> str:
    """The conversation to talk in: `--thread`, else a new one, titled as a test on a test run."""
    if getattr(ns, "thread", None):
        return str(ns.thread)
    title = marked(ns, short(first or "Chat from ops", 60)) if testing(ns) else None
    made = ops.chat.start(agent_id(ops, ns.agent, test=ns.test), kb_ids=ns.kb, test=ns.test, title=title)
    thread = str(made.get("id") or made.get("threadId"))
    where = console_url(f"/chat/{thread}")
    line(ns, f"thread {thread}" + (f"  {where}" if where else ""))
    if getattr(ns, "connector", None) or getattr(ns, "connector_off", None):
        keep = [n.strip() for v in getattr(ns, "connector", None) or [] for n in str(v).split(",") if n.strip()]
        narrow(ns, ops, thread, keep=keep or None, leave=getattr(ns, "connector_off", None))
    return thread


def narrow(
    ns: argparse.Namespace, ops: OpsAI, thread: str, *, keep: list[str] | None = None, leave: list[str] | None = None
) -> None:
    """As the composer's picker does: leaves every connector the chat holds out but `keep`, or leaves out `leave`
    (names or ids)."""
    held = [c for c in ops.chat.connectors(thread) if c["state"] != "off_for_team"]

    def names(c: dict[str, Any]) -> set[str]:
        return {str(c["appId"]).lower(), str(c["name"]).lower()}

    asked = {k.lower() for k in (keep or leave or [])}
    if missing := sorted(asked - {n for c in held for n in names(c)}):
        raise ValueError(f"this chat has no connector named {', '.join(missing)}")
    off = [str(c["appId"]) for c in held if bool(names(c) & asked) != bool(keep)]
    rows = ops.chat.set_connectors(thread, off=off)
    line(ns, "connectors " + ", ".join(f"{c['name']} {'on' if c['on'] else 'off'}" for c in rows))


def _say(ns: argparse.Namespace, ops: OpsAI, messages: list[str]) -> int:
    thread = start_thread(ns, ops, messages[0] if messages else None)
    turns = [turn(ns, ops, thread, text) for text in messages]
    if ns.as_json:
        return emit(ns, {"thread": thread, "turns": turns})
    if messages:
        for r in calls(ops, thread):
            line(ns, _log_line(r))
    return 1 if any(t["error"] for t in turns) else 0


def turn(ns: argparse.Namespace, ops: OpsAI, thread: str, text: str) -> dict[str, Any]:
    """One message and its streamed reply, printed as the chat shows it; answers what a script checks."""
    line(ns, f"\nyou > {text}")
    seen: dict[str, Any] = {"tools": [], "cards": [], "widgets": [], "text": "", "error": None, "phases": []}
    for e in ops.chat.say(thread, text):
        kind = e.get("type")
        if kind == "status":
            seen["phases"].append(e.get("phase"))
        elif kind == "tool_end":
            c = e["call"]
            seen["tools"].append(c)
            line(ns, f"  tool {c.get('label') or c.get('name')} [{c.get('status')}] {short(c.get('input'))}")
            line(ns, f"       → {short(c.get('output'))}")
            if card := connect_card(c):
                seen["cards"].append(card)
                reason = card.get("reason")
                names = ", ".join(str(a.get("account") or a.get("name")) for a in card.get("accounts") or [])
                what = (
                    f"Ask an admin {card.get('app')}"
                    if reason == "app_off"
                    else f"Which {card.get('app')} account: {names}"
                    if reason == "account_choice"
                    else f"Connect {card.get('connection')}"
                )
                line(ns, f"  CARD {what} ({card.get('reason')}): {card.get('message')}")
                line(ns, f"       open: {card.get('connectUrl')}")
        elif kind == "widget":
            w = e["widget"]
            seen["widgets"].append(w)
            line(ns, f"  widget {w.get('id')} {w.get('kind')} {short(w.get('title') or '', 80)} {w.get('state', '')}")
        elif kind == "text":
            seen["text"] += e.get("delta", "")
        elif kind == "replace":
            seen["text"] = e.get("text", "")
        elif kind == "error":
            seen["error"] = e.get("code") or e.get("message")
        elif kind == "done":
            seen["text"] = (e.get("message") or {}).get("content") or seen["text"]
    line(ns, f"agent > {seen['text'].strip()}" + (f"\n  ERROR {seen['error']}" if seen["error"] else ""))
    return seen


def calls(ops: OpsAI, thread: str) -> list[dict[str, Any]]:
    """The call log rows of the thread, as the Logs tab reads them."""
    return list(ops.usage.list(thread=thread, page=1, page_size=50))


def _log_line(r: dict[str, Any]) -> str:
    return (
        f"  log {r.get('title') or r.get('target')} {r.get('outcome')} as {r.get('credential') or '-'}"
        f" for {r.get('actingFor') or '-'} ({r.get('environment')}, {r.get('latencyMs')} ms)"
    )


def _show(ns: argparse.Namespace, thread: dict[str, Any]) -> int:
    lines = []
    for m in thread.get("messages") or []:
        lines.append(f"{m.get('role')} > {short(m.get('content') or '', 400)}")
        for c in m.get("toolCalls") or []:
            lines.append(f"  tool {c.get('name')} [{c.get('status')}] {short(c.get('input'))}")
            lines.append(f"       → {short(c.get('output'))}")
        for w in m.get("widgets") or []:
            lines.append(f"  widget {w.get('id')} {w.get('kind')} {w.get('state', '')}")
    return emit(ns, thread, text="\n".join(lines) or "(no messages)")


def last_card(thread: dict[str, Any]) -> dict[str, Any] | None:
    cards = [card for m in thread.get("messages") or [] for c in m.get("toolCalls") or [] if (card := connect_card(c))]
    return cards[-1] if cards else None


OPEN = ("pending", "awaiting_second", "open")


def _widget(thread: dict[str, Any], wanted: str | None) -> tuple[str, str]:
    """The message and widget an action goes to: the named widget, else the newest one still waiting."""
    found = [(str(m["id"]), w) for m in thread.get("messages") or [] for w in m.get("widgets") or []]
    for message, w in reversed(found):
        if (wanted and w.get("id") == wanted) or (not wanted and w.get("state") in OPEN):
            return message, str(w["id"])
    raise ValueError(f"no widget {wanted} in this conversation" if wanted else "no open widget in this conversation")


def check(ns: argparse.Namespace, name: str, ok: bool, why: str) -> bool:
    line(ns, f"  {'PASS' if ok else 'FAIL'} {name}" + ("" if ok else f": {why}"))
    return ok


def line(ns: argparse.Namespace, text: str) -> None:
    # A streamed turn prints as it goes; --json prints only the result, so standard output stays one JSON document.
    if not ns.as_json and not ns.quiet:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
