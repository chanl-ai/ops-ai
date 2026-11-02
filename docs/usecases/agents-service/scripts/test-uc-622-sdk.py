"""uc-622, sdk layer: a builder asks the first three published Agent Examples on the fake stack."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from usecase_harness import ROOT, check, finish

A1 = ROOT / "examples/agents/01-answer-from-instructions"
A2 = ROOT / "examples/agents/02-cite-the-handbook"
A3 = ROOT / "examples/agents/03-look-up-a-customer"


def _run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd or ROOT, text=True, capture_output=True, check=False)


def _setup(folder: Path) -> str:
    proc = _run([sys.executable, str(folder / "setup.py")])
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"{folder.name} setup exited {proc.returncode}: {out}")
    return out


def _pytest(folder: Path) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "pytest", "-v", str(folder / "test_example.py")])


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _yaml_only(folder: Path) -> bool:
    text = (folder / "test_example.py").read_text()
    return "outcome:" in text and "ops.agents.chat" not in text and "chat_agent" not in text


def main() -> None:
    first = _setup(A1)
    check(
        "1 first A1 setup prints READY and not MADE",
        "READY" in first.splitlines() and "MADE" not in first,
        first,
    )
    a1_test = _pytest(A1)
    check(
        "2 A1 test chats through the public SDK and sees a reply",
        a1_test.returncode == 0 and not _yaml_only(A1),
        a1_test.stdout + a1_test.stderr,
    )
    a1_bindings = _digest(A1 / ".bindings.json")
    again = _setup(A1)
    check(
        "3 second A1 setup prints FOUND and leaves bindings unchanged",
        "FOUND" in again and _digest(A1 / ".bindings.json") == a1_bindings,
        again,
    )

    kb_first = _setup(A2)
    check(
        "4 first A2 setup prints READY and reuses the handbook",
        "READY" in kb_first.splitlines() and "MADE" not in kb_first,
        kb_first,
    )
    a2_test = _pytest(A2)
    a2_out = a2_test.stdout + a2_test.stderr
    check(
        "5 A2 test cites the R1 handbook page through ops.agents.chat",
        a2_test.returncode == 0 and not _yaml_only(A2),
        a2_out,
    )
    check(
        "6 A2 missing-page fixture takes the documented no-answer",
        a2_test.returncode == 0 and "test_missing_page_takes_the_documented_no_answer" in a2_out,
        a2_out,
    )
    a2_bindings = _digest(A2 / ".bindings.json")
    kb_again = _setup(A2)
    check(
        "7 second A2 setup prints FOUND and leaves bindings unchanged",
        "FOUND" in kb_again and _digest(A2 / ".bindings.json") == a2_bindings,
        kb_again,
    )

    tool_first = _setup(A3)
    check(
        "8 first A3 setup prints READY and reuses search_customers",
        "READY" in tool_first.splitlines() and "MADE" not in tool_first,
        tool_first,
    )
    a3_test = _pytest(A3)
    a3_out = a3_test.stdout + a3_test.stderr
    check(
        "9 A3 test calls the R1 read tool and a missing customer fails as documented",
        a3_test.returncode == 0 and not _yaml_only(A3),
        a3_out,
    )
    a3_bindings = _digest(A3 / ".bindings.json")
    tool_again = _setup(A3)
    check(
        "10 second A3 setup prints FOUND and leaves bindings unchanged",
        "FOUND" in tool_again and _digest(A3 / ".bindings.json") == a3_bindings,
        tool_again,
    )
    finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        check("1 first A1 setup prints READY and not MADE", False, str(exc))
        finish()
