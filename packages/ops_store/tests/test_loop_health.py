"""Every background process has a test that a failing pass shows on `/health/background`: without one, a loop that
swallows its errors, or never reaches its heartbeat, reads as running while its work has stopped.

The test is a call to `ops_store.testing.loop_reports_failure(client, "<key>", trip)` in the tests of the service
that runs the process (`services/<service>-service/tests`). The keys checked are those on `PROCESSES` and those a
service registers with `background.retention(..., key=..., service=...)`.

`loop_health/<service>.txt` lists the keys still waiting for their test, one a row. A row may only go: a process with
no test and no row fails here, and so does a row whose key has its test or is no longer a process."""

from __future__ import annotations

import ast
from pathlib import Path

from ops_store.background import PROCESSES

ROOT = Path(__file__).resolve().parents[3]
BASELINES = Path(__file__).parent / "loop_health"


def _name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _text(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _calls(folder: Path, name: str) -> list[ast.Call]:
    out: list[ast.Call] = []
    for path in sorted(folder.rglob("*.py")):
        out += [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Call) and _name(n) == name]
    return out


def keys_with_a_test(source: str) -> set[str]:
    """The keys a test file hands to `loop_reports_failure`, as its second argument or `key=`."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _name(node) == "loop_reports_failure":
            named = next((kw.value for kw in node.keywords if kw.arg == "key"), None)
            key = _text(named if named is not None else node.args[1] if len(node.args) > 1 else None)
            if key is not None:
                keys.add(key)
    return keys


def processes() -> dict[str, set[str]]:
    """Service -> its process keys: the listed ones and the retention sweeps registered in source."""
    by_service: dict[str, set[str]] = {}
    for p in PROCESSES:
        by_service.setdefault(p.service, set()).add(p.key)
    for src in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")):
        for call in _calls(src, "retention"):
            given = {kw.arg: _text(kw.value) for kw in call.keywords}
            key, service = given.get("key"), given.get("service")
            if key and service:
                by_service.setdefault(service, set()).add(key)
    return by_service


def covered(service: str) -> set[str]:
    tests = ROOT / "services" / f"{service}-service" / "tests"
    keys: set[str] = set()
    for path in sorted(tests.rglob("*.py")) if tests.is_dir() else []:
        keys |= keys_with_a_test(path.read_text())
    return keys


def waiting(service: str) -> set[str]:
    path = BASELINES / f"{service}.txt"
    rows = path.read_text().splitlines() if path.exists() else []
    return {r.strip() for r in rows if r.strip() and not r.startswith("#")}


def test_every_process_has_a_test_that_its_failure_shows_on_health() -> None:
    problems: list[str] = []
    everything = processes()
    for service in sorted(set(everything) | {p.stem for p in BASELINES.glob("*.txt")}):
        keys, have, rows = everything.get(service, set()), covered(service), waiting(service)
        problems += [
            f"{service}: {key} has no loop_reports_failure test under services/{service}-service/tests"
            for key in sorted(keys - have - rows)
        ]
        problems += [
            f"{service}: {key} has its test or is no longer a process; delete its row in loop_health/{service}.txt"
            for key in sorted(rows & have | rows - keys)
        ]
    assert problems == [], f"{len(problems)} background processes with no failure test:\n" + "\n".join(problems)


def test_the_scan_reads_the_key_in_both_argument_forms() -> None:
    source = (
        "async def test_a(client):\n"
        "    await loop_reports_failure(client, 'files_relay', trip)\n"
        "async def test_b(client):\n"
        "    await testing.loop_reports_failure(client, key='files_retention', trip=trip)\n"
        "async def test_c(client, key):\n"
        "    await loop_reports_failure(client, key, trip)\n"
    )
    assert keys_with_a_test(source) == {"files_relay", "files_retention"}
