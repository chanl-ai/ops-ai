"""Write the output of OPS_SECRETS_CMD as a makefile fragment for make/env.mk, or write nothing.

The command is the person's own secrets manager export and prints KEY=value lines (dotenv format). make/env.mk calls
this only when OPS_SECRETS_CMD is set and OPS_NO_SECRETS_CMD is unset or 0. A failing command gets one warning line
on stderr and no file, so make carries on with .env and the environment. Values are never printed.

    python3 scripts/secrets_cmd_env.py <command> <output fragment>
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# Names make or the shell own: a secret with one of these names must not shadow them.
SKIPPED = {"PATH", "HOME", "SHELL", "PWD", "USER", "MAKEFLAGS", "MAKELEVEL", "MFLAGS", "MAKEFILES", "SHLVL"}
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "$": "$"}


def parse(text: str) -> dict[str, str]:
    """KEY=value lines. A double-quoted value unescapes \\n and friends; a single-quoted one is literal."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        name, sep, value = line.strip().partition("=")
        name = name.removeprefix("export ").strip()
        if not sep or not NAME.match(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), m.group(0)), value[1:-1])
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        found[name] = value
    return found


def fragment(secrets: dict[str, str], caller: Mapping[str, str]) -> str:
    """`override` and `export` lines: a define keeps newlines (key files) and `$` doubled keeps make from expanding
    it. `override` puts the command above .env; a name in the caller's environment is left out, so the caller wins."""
    out = []
    for name in sorted(secrets):
        if name in SKIPPED or name in caller:
            continue
        body = secrets[name].replace("$", "$$")
        if "\n" in body or body != body.strip() or body.startswith(("#", "-")):
            out.append(f"override define {name}\n{body}\nendef\nexport {name}\n")
        else:
            out.append(f"override {name} = {body.replace('#', chr(92) + '#')}\nexport {name}\n")
    return "".join(out)


def run(command: str, target: str) -> int:
    try:
        got = subprocess.run(command, shell=True, capture_output=True, text=True, check=False, timeout=30)
        if got.returncode != 0:
            raise RuntimeError("command failed")
        text = fragment(parse(got.stdout), os.environ)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        print("OPS_SECRETS_CMD failed; using .env and the environment", file=sys.stderr)
        return 0
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2]))
