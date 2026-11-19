#!/usr/bin/env python3
"""Wait guard for agent sessions, enforced as a Claude Code PreToolUse hook on Bash.

Agents lost most of their hours waiting on whole suites and sleep polls. When CL_AGENT or CL_AGENT_RUN is set (a
Codeloop agent is running the command), this refuses:
- `pytest` with no named test file, and `make test PKG=...` (or `make -C <dir> test`) with no T=;
- an unfiltered `pnpm verify` (a commit's own hooks run it on the staged content, so `git commit` is untouched);
- `sleep N` over 60 seconds, and a sleep loop that cannot be shown to end within 60 seconds.
Each refusal is one line naming the command to run instead. Without those variables (the owner) nothing is refused.
CI and nightly runs keep the whole suites. Exit 2 blocks the call; stderr is the reason.
`python3 scripts/agent-guard.py --self-test` checks every rule.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

MAX_WAIT = 60
PYTEST_INSTEAD = "Run `make test PKG=<member> T=<file>` or `make test-impacted BASE=origin/main`."
WAIT_INSTEAD = f"Keep a sleep to {MAX_WAIT}s or less; wait on a named check (`make test PKG=<member> T=<file>`)."


def steps(command: str) -> list[list[str]]:
    """The command split into simple commands, quotes respected, so text inside a commit message is never a command."""
    # A heredoc body is data for the command that reads it, not commands.
    command = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\b", "", command, flags=re.DOTALL)
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    out: list[list[str]] = [[]]
    try:
        for tok in lex:
            if set(tok) <= set(";&|()\n"):
                out.append([])
            else:
                out[-1].append(tok)
    except ValueError:
        out = [[t for t in command.split() if t]]
    return [s for s in out if s]


def strip_prefix(words: list[str]) -> list[str]:
    """Drop VAR=value, `timeout N`, `uv run [opts]`, `python -m` and `env` in front of the real command."""
    w = list(words)
    while w:
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", w[0]) or w[0] == "env":
            w = w[1:]
        elif w[0] == "timeout" and len(w) > 2:
            w = w[2:] if not w[1].startswith("-") else w[3:]
        elif w[0] == "uv" and len(w) > 1 and w[1] == "run":
            w = w[2:]
            while w and w[0].startswith("-"):
                w = w[2:] if w[0] in ("--directory", "--project", "--with", "--python", "-p") else w[1:]
        elif w[0] in ("python", "python3") and w[1:2] == ["-m"]:
            w = w[2:]
        else:
            break
    return w


def seconds(arg: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", arg)
    return float(m[1]) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m[2]] if m else None


def sleep_total(words: list[str]) -> float:
    return sum(filter(None, (seconds(a) for a in words[1:])))


def loop_count(words: list[str]) -> int | None:
    """Iterations of a `for` loop whose list is `seq`, `{a..b}` or a literal list; None when it cannot be told."""
    text = " ".join(words)
    m = re.search(r"\bseq\s+(?:(\d+)\s+)?(\d+)\b", text)
    if m:
        return int(m[2]) - int(m[1] or 1) + 1
    m = re.search(r"\{(\d+)\.\.(\d+)\}", text)
    if m:
        return abs(int(m[2]) - int(m[1])) + 1
    m = re.search(r"\bfor\s+\w+\s+in\s+((?:[\w.-]+\s+)+?)(?:;|do\b)", text + " ;")
    return len(m[1].split()) if m else None


def check_pytest(w: list[str]) -> str | None:
    named = [a for a in w[1:] if not a.startswith("-") and (".py" in a or "::" in a)]
    return None if named else f"Refused: pytest with no test file runs the whole suite. {PYTEST_INSTEAD}"


def check_make(w: list[str]) -> str | None:
    targets = [a for a in w[1:] if not a.startswith("-") and "=" not in a]
    if "test" not in targets:
        return None
    vars_ = dict(a.split("=", 1) for a in w[1:] if "=" in a and not a.startswith("-"))
    if vars_.get("T"):
        return None
    if "PKG" in vars_ or "-C" in w:
        return f"Refused: `make test` with no T= runs a whole suite. {PYTEST_INSTEAD}"
    return None


def check_pnpm(w: list[str]) -> str | None:
    if w[1:2] == ["verify"] or w[1:3] == ["run", "verify"]:
        return (
            "Refused: a whole `pnpm verify` outside a commit. Run `make test-impacted BASE=origin/main`, "
            "or `pnpm --filter @ops-ai/console exec node --test <file>`; `git commit` runs the gates on what you stage."
        )
    return None


def check(command: str) -> str | None:
    if not (os.environ.get("CL_AGENT") or os.environ.get("CL_AGENT_RUN")):
        return None
    parsed = steps(command)
    for i, raw in enumerate(parsed):
        w = strip_prefix(raw)
        if not w:
            continue
        cmd = os.path.basename(w[0])
        found = None
        if cmd == "pytest":
            found = check_pytest(w)
        elif cmd == "make":
            found = check_make(w)
        elif cmd == "pnpm":
            found = check_pnpm(w)
        elif cmd == "sleep" and sleep_total(w) > MAX_WAIT:
            found = f"Refused: sleep over {MAX_WAIT} seconds. {WAIT_INSTEAD}"
        elif cmd in ("while", "until", "for"):
            found = check_loop(parsed[i:])
        if found:
            return found
    return None


def check_loop(rest: list[list[str]]) -> str | None:
    """A loop is judged on the sleep inside it: `for` by its iterations, while/until only if it cannot be bounded."""
    head: list[str] = []
    n = 0
    while n < len(rest) and rest[n][0] != "do":
        head += rest[n]
        n += 1
    body: list[list[str]] = []
    for step in rest[n:]:
        if step[0] == "done":
            break
        body.append(strip_prefix(step[1:] if step[0] == "do" else step))
    each = max((sleep_total(b) for b in body if b[:1] == ["sleep"]), default=0)
    if not each:
        return None
    if each > MAX_WAIT:
        return f"Refused: sleep over {MAX_WAIT} seconds in a loop. {WAIT_INSTEAD}"
    if head[0] == "for":
        count = loop_count(head)
        if count is None or count * each > MAX_WAIT:
            return f"Refused: a sleep loop that can run over {MAX_WAIT} seconds. {WAIT_INSTEAD}"
        return None
    return f"Refused: a while/until sleep loop has no {MAX_WAIT}-second limit. {WAIT_INSTEAD}"


def self_test() -> int:
    cases = [
        ("pytest", True),
        ("uv run pytest -q", True),
        ("cd services/x && uv run pytest tests", True),
        ("python -m pytest", True),
        ("uv run pytest tests/test_a.py", False),
        ("uv run pytest services/x/tests/test_a.py::test_b -q", False),
        ("make test PKG=services/platform-service", True),
        ("make test PKG=services/platform-service T=tests/test_a.py", False),
        ("make test PKG=services/platform-service T=", True),
        ("make -C services/kb-service test", True),
        ("make -C services/kb-service test T=tests/test_a.py", False),
        ("make test-impacted BASE=origin/main", False),
        ("make test", False),
        ("pnpm verify", True),
        ("pnpm run verify", True),
        ("pnpm --filter @ops-ai/console exec node --test src/lib/egress.test.ts", False),
        ("git commit -m 'run pnpm verify and pytest'", False),
        ("make commit MSG='sleep 300 then pytest' FILES=a", False),
        ("sleep 300", True),
        ("sleep 5m", True),
        ("sleep 30", False),
        ("sleep 60", False),
        ("sleep 30 && sleep 31", False),
        ("for i in $(seq 1 20); do sleep 30; done", True),
        ("for i in 1 2 3 4 5 6 7 8 9 10 11 12; do sleep 30; done", True),
        ("for i in 1 2 3; do sleep 10; done", False),
        ("while true; do curl -s x; sleep 5; done", True),
        ("until curl -s x; do sleep 2; done", True),
        ("python3 - <<'EOF'\nprint('pytest')\nEOF", False),
        ("echo pytest", False),
    ]
    os.environ["CL_AGENT"] = "builder-x"
    bad = [(c, want) for c, want in cases if (check(c) is not None) != want]
    for c, want in bad:
        print(f"FAIL {'refuse' if want else 'allow'}: {c!r}")
    os.environ.pop("CL_AGENT")
    owner = [c for c, want in cases if want and check(c) is not None]
    for c in owner:
        print(f"FAIL owner blocked: {c!r}")
    os.environ["CL_AGENT_RUN"] = "run-1"
    run = check("pytest") is None
    os.environ.pop("CL_AGENT_RUN")
    if run:
        print("FAIL CL_AGENT_RUN does not turn the guard on")
    total = len(cases) + 2
    failed = len(bad) + (1 if owner else 0) + (1 if run else 0)
    print(f"agent-guard: {total - failed} of {total} checks hold")
    return 1 if failed else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    reason = check((event.get("tool_input") or {}).get("command") or "")
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
