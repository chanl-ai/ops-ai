"""Writes passed results to a settings file with install.sh's `setenv` rules: mode 600, every other line kept, and the
values written in-process, never on a command line. A comment per item records the answer that wrote its values, so a
second run with the same answer keeps a value the person edited by hand and a changed answer replaces it."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from setup.report import Result

MARK = "# setup "


def _marks(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        if line.startswith(MARK):
            parts = line[len(MARK) :].split()
            if len(parts) == 2:
                out[parts[0]] = parts[1]
    return out


def write(path: Path, results: list[Result]) -> list[str]:
    """Applies every passed result; answers which names were written. Failed results write nothing."""
    lines = path.read_text().splitlines() if path.exists() else []
    marks = _marks(lines)
    written: list[str] = []
    for r in results:
        if not r.ok or not r.settings:
            continue
        mark, unchanged = f"{MARK}{r.item.replace(' ', '_')} ", marks.get(r.item.replace(" ", "_")) == r.answer_hash()
        for name, value in r.settings.items():
            at = next((i for i, line in enumerate(lines) if line.startswith(f"{name}=")), None)
            if at is None:
                lines.append(f"{name}={value}")
            elif unchanged:
                continue
            else:
                lines[at] = f"{name}={value}"
            written.append(name)
        lines = [line for line in lines if not line.startswith(mark)] + [f"{mark}{r.answer_hash()}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as out:
        out.write("".join(f"{line}\n" for line in lines))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return written
