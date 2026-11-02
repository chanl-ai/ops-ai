"""uc-624, sdk layer: a builder proves the two public bridges on the fake stack."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from usecase_harness import ROOT, check, finish

C1 = ROOT / "examples/compositions/01-workflow-asks-agent"
C2 = ROOT / "examples/compositions/02-agent-starts-workflow"


def _clear(folder: Path) -> None:
    for name in (".bindings.json", ".ops-profile.json"):
        path = folder / name
        if path.is_file():
            path.unlink()


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
    return "outcome:" in text and "workflows.run" not in text and "chat_agent" not in text and "agents.chat" not in text


def main() -> None:
    _clear(C1)
    _clear(C2)
    first = _setup(C1)
    check(
        "1 first composition 1 setup prints READY and not MADE",
        "READY" in first.splitlines() and "MADE" not in first,
        first,
    )
    c1_test = _pytest(C1)
    c1_out = c1_test.stdout + c1_test.stderr
    check(
        "2 composition 1 test-run returns the cited answer and opens no human task",
        c1_test.returncode == 0 and not _yaml_only(C1),
        c1_out,
    )
    c1_bindings = _digest(C1 / ".bindings.json")
    again = _setup(C1)
    check(
        "3 second composition 1 setup prints FOUND and leaves bindings unchanged",
        "FOUND" in again and _digest(C1 / ".bindings.json") == c1_bindings,
        again,
    )

    w1_first = _setup(C2)
    check(
        "4 first composition 2 setup prints READY and not MADE",
        "READY" in w1_first.splitlines() and "MADE" not in w1_first,
        w1_first,
    )
    c2_test = _pytest(C2)
    c2_out = c2_test.stdout + c2_test.stderr
    check(
        "5 composition 2 chat starts the three-node workflow and opens no human task",
        c2_test.returncode == 0 and not _yaml_only(C2),
        c2_out,
    )
    c2_bindings = _digest(C2 / ".bindings.json")
    w1_again = _setup(C2)
    check(
        "6 second composition 2 setup prints FOUND and leaves bindings unchanged",
        "FOUND" in w1_again and _digest(C2 / ".bindings.json") == c2_bindings,
        w1_again,
    )
    finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        check("1 first composition 1 setup prints READY and not MADE", False, str(exc))
        finish()
