"""uc-621, sdk layer: a builder runs the three foundation Example folders on the fake stack."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from usecase_harness import ROOT, check, finish

CHAT = ROOT / "examples/chat/01-ask-once"
KNOWLEDGE = ROOT / "examples/knowledge/01-search-a-page"
TOOLS = ROOT / "examples/tools/01-find-a-customer"


def _run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd or ROOT, text=True, capture_output=True, check=False)


def _setup(folder: Path) -> str:
    proc = _run([sys.executable, str(folder / "setup.py")])
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"{folder.name} setup exited {proc.returncode}: {out}")
    return out


def _pytest(folder: Path) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "pytest", "-q", str(folder / "test_example.py")])


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _yaml_only(folder: Path) -> bool:
    text = (folder / "test_example.py").read_text()
    return "outcome:" in text and "ops_ai" not in text and "folder" not in text


def main() -> None:
    chat_first = _setup(CHAT)
    check(
        "1 first chat setup prints READY and not MADE",
        "READY" in chat_first.splitlines() and "MADE" not in chat_first,
        chat_first,
    )
    chat_test = _pytest(CHAT)
    check(
        "2 chat test sends the fixture through the public SDK and sees a reply",
        chat_test.returncode == 0 and not _yaml_only(CHAT),
        chat_test.stdout + chat_test.stderr,
    )
    chat_bindings = _digest(CHAT / ".bindings.json")
    chat_again = _setup(CHAT)
    check(
        "3 second chat setup prints FOUND and leaves bindings unchanged",
        "FOUND" in chat_again and _digest(CHAT / ".bindings.json") == chat_bindings,
        chat_again,
    )

    kb_first = _setup(KNOWLEDGE)
    check(
        "4 first knowledge setup prints READY and not MADE",
        "READY" in kb_first.splitlines() and "MADE" not in kb_first,
        kb_first,
    )
    kb_test = _pytest(KNOWLEDGE)
    check(
        "5 knowledge test searches the handbook through the public SDK and sees a passage",
        kb_test.returncode == 0 and not _yaml_only(KNOWLEDGE),
        kb_test.stdout + kb_test.stderr,
    )
    kb_bindings = _digest(KNOWLEDGE / ".bindings.json")
    kb_again = _setup(KNOWLEDGE)
    check(
        "6 second knowledge setup prints FOUND and leaves bindings unchanged",
        "FOUND" in kb_again and _digest(KNOWLEDGE / ".bindings.json") == kb_bindings,
        kb_again,
    )

    tool_first = _setup(TOOLS)
    check(
        "7 first tool setup prints READY and not MADE",
        "READY" in tool_first.splitlines() and "MADE" not in tool_first,
        tool_first,
    )
    tool_test = _pytest(TOOLS)
    check(
        "8 tool test calls the sample-team read tool and sees ada@example.test",
        tool_test.returncode == 0 and not _yaml_only(TOOLS),
        tool_test.stdout + tool_test.stderr,
    )
    tool_bindings = _digest(TOOLS / ".bindings.json")
    tool_again = _setup(TOOLS)
    check(
        "9 second tool setup prints FOUND and leaves bindings unchanged",
        "FOUND" in tool_again and _digest(TOOLS / ".bindings.json") == tool_bindings,
        tool_again,
    )

    banned = ("approval", "roles", "rbac", "evaluation")
    readmes = "\n".join((folder / "README.md").read_text().lower() for folder in (CHAT, KNOWLEDGE, TOOLS))
    check(
        "10 none of the three READMEs teach approval, roles, or evaluation",
        not any(word in readmes for word in banned),
        readmes,
    )
    finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        check("1 first chat setup prints READY and not MADE", False, str(exc))
        finish()
