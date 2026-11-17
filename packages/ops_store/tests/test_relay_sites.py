"""The relay is built in one place: `ops_store.outbox.relay()` takes a service's routes and targets, so a fix to the
wiring lands once. A `Relay(...)` constructed anywhere else in source is a copy of that wiring.

`relay_sites/<service>.txt` lists the files that still build their own, one path a row, until each service moves onto
`relay()`. A row may only go: a new site fails here naming its line, and a listed file that no longer builds one fails
until its row is deleted. Tests are not scanned: they build a `Relay` to drive one pass."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted(p for p in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")) if p.is_dir())
OWNER = "packages/ops_store/src/ops_store/outbox.py"
BASELINES = Path(__file__).parent / "relay_sites"


def constructions(source: str) -> list[int]:
    """The lines that call `Relay(...)`, by its name or as an attribute (`outbox.Relay(...)`)."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name == "Relay":
                lines.append(node.lineno)
    return sorted(lines)


def sites() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for src in SOURCES:
        for path in src.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel != OWNER and (lines := constructions(path.read_text())):
                found[rel] = lines
    return found


def listed() -> set[str]:
    rows: set[str] = set()
    for path in sorted(BASELINES.glob("*.txt")):
        rows |= {r.strip() for r in path.read_text().splitlines() if r.strip() and not r.startswith("#")}
    return rows


def test_a_relay_is_constructed_only_in_the_outbox_module() -> None:
    found, waiting = sites(), listed()
    new = [f"{rel}:{line}" for rel, lines in sorted(found.items()) if rel not in waiting for line in lines]
    gone = sorted(waiting - set(found))
    assert new == [], (
        f"{len(new)} Relay(...) built outside ops_store.outbox; call ops_store.outbox.relay(engine, table, routes=..., "
        "targets=..., role=...) instead:\n" + "\n".join(new)
    )
    assert gone == [], "no longer builds a Relay; delete its row under tests/relay_sites/:\n" + "\n".join(gone)


def test_the_scan_finds_both_call_forms_and_ignores_other_uses_of_the_name() -> None:
    source = (
        "from ops_store import outbox\n"
        "from ops_store.outbox import Relay\n"
        "def a(e, t, s) -> Relay:\n"
        "    return Relay(e, t, s)\n"
        "def b(e, t, s):\n"
        "    return outbox.Relay(e, t, s)\n"
        "def c(e, t):\n"
        "    return outbox.relay(e, t, routes={}, targets={}, role=None)\n"
    )
    assert constructions(source) == [4, 6]


def test_a_baseline_only_falls_in_the_history() -> None:
    """A row raised, or a file added, in a commit with no `Standards-exception:` trailer: the working tree alone
    cannot show it, since the baseline and the code are changed together."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import baseline_history  # noqa: PLC0415

    assert (
        baseline_history.judged(
            baseline_history.problems(
                ROOT, "fb7c75814504a9958b6d5125f978febeba0556a5", ["packages/ops_store/tests/relay_sites"]
            )
        )
        == []
    )
