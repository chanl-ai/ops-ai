"""Every "not found" a service answers reads as one plain sentence. NotFound takes the name of the missing thing and
adds "was not found."; a caller that passes a whole sentence ends it with a full stop, or the person reads "No item
with that id. was not found.". By failure mode: the class doubling a sentence it is given; a caller passing a
sentence the class then extends; and a scan that reads no caller."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ops_service_kit.errors import NotFound

ROOT = Path(__file__).resolve().parents[2]
# The calls whose first argument becomes a NotFound message: the class and the services' helpers around it.
CALLS = {"NotFound", "not_found", "_not_found"}
# A message the class extended although it already says what is wrong: "No item ...", "... is off ...".
DOUBLED = re.compile(
    r"(\.\s*was not found\.$)|(^(No|There is no)\b.*was not found\.$)"
    r"|(\b(is|are) (not|off)\b.*was not found\.$)|(;.*was not found\.$)"
)


def _literal(node: ast.expr) -> str | None:
    """The message as written, each f-string expression read as X; None for a message built elsewhere."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "X" for v in node.values)
    return None


def _messages() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in sorted(ROOT.glob("services/*/src/**/*.py")) + sorted(ROOT.glob("packages/*/src/**/*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name in CALLS and (text := _literal(node.args[0])) is not None:
                out.append((f"{path.relative_to(ROOT)}:{node.lineno}", text))
    return out


def test_the_class_keeps_a_whole_sentence_and_names_a_missing_thing() -> None:
    assert NotFound("No item with that id.").message == "No item with that id."
    assert NotFound("Run").message == "Run was not found."


def test_every_caller_reads_as_one_sentence() -> None:
    found = _messages()
    assert len(found) > 100, "the scan read no callers"
    doubled = [f"{where}: {NotFound(text).message}" for where, text in found if DOUBLED.search(NotFound(text).message)]
    assert doubled == [], "\n".join(doubled)
