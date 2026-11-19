"""Refuse a use-case script that writes outside the one output root.

Every file a use case writes (screenshots, logs, model-rule files, fixtures) goes under evidenceDir() in
packages/usecase-runner/src/harness.ts, or evidence_dir() in docs/usecases/lib/usecase_harness.py: OPS_EVIDENCE_DIR,
default .logs/usecases/, then <uc-id>/. A script that writes into docs/, test-results/ or /tmp leaves the tree dirty
after a run and invites a commit of meaningless image changes. A temp dir (tmpdir, mkdtemp, tempfile) is allowed for
scratch files that nothing reads afterwards.

  python3 scripts/check_usecase_outputs.py [--root <tree>]

A write is a call that creates a file or folder (screenshot path, writeFileSync, mkdirSync, write_text, open for
write, shutil.copy*). Its path must be built from evidenceDir/evidence_dir, a temp dir, or a name assigned from one.
A string naming a known output folder (docs/console/proposed, test-results, docs/plans, /tmp) also fails.
docs/usecases/lib/capture_demo.mjs is exempt: it is the demo-capture tool, not a use case.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EXEMPT = {"docs/usecases/lib/capture_demo.mjs"}
SUFFIXES = {".mjs", ".js", ".ts", ".py", ".sh"}

# A path expression holding one of these is rooted: the output root, or a temp dir.
SAFE_CALLS = re.compile(
    r"\b(evidenceDir|evidence_dir|tmpdir|mkdtemp|mkdtempSync|tempfile|TemporaryDirectory|gettempdir)\b"
)
# Names the Python harness exports that already sit under the output root.
SAFE_IMPORTS = {"LOG_DIR", "EVIDENCE_ROOT", "EVIDENCE"}
# A literal naming where a script used to put its output.
OUTPUT_LITERAL = re.compile(
    r"""["'`][^"'`\n]*(docs/console/proposed|docs/plans/|\.logs/usecase\b|/tmp/)|["'`](?:\./)?test-results\b"""
)

JS_CALLS = ("writeFileSync", "appendFileSync", "mkdirSync", "createWriteStream", "copyFileSync", "cpSync")
PY_METHODS = ("write_text", "write_bytes", "mkdir", "touch")
PY_FUNCS = ("copy", "copy2", "copyfile", "copytree", "move")

KEYWORDS = {
    "const",
    "let",
    "var",
    "await",
    "new",
    "return",
    "if",
    "else",
    "for",
    "in",
    "of",
    "true",
    "false",
    "null",
    "undefined",
    "None",
    "True",
    "False",
    "not",
    "and",
    "or",
    "is",
    "as",
    "with",
    "def",
    "lambda",
    "str",
    "Path",
    "os",
    "process",
    "env",
    "join",
    "resolve",
    "dirname",
    "basename",
    "f",
    "r",
    "b",
    "string",
    "recursive",
    "parents",
    "exist_ok",
}


def strip_strings(text: str) -> str:
    """The expression without quoted text, keeping what template and f-string holes interpolate."""
    out: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            j = i + 1
            while j < len(text) and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            body = text[i + 1 : j]
            prefix = text[i - 1] if i else ""
            if c == "`" or prefix in "fF":
                out.append(" ".join(re.findall(r"\$?\{([^{}]*)\}", body)))
            out.append(" ")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def idents(expr: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z_]\w*", strip_strings(expr)) if t not in KEYWORDS}


def balanced_args(text: str, open_at: int) -> str:
    """Text inside the parentheses that open at `open_at`."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] in "([{":
            depth += 1
        elif text[i] in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : i]
    return text[open_at + 1 :]


def split_top(args: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote = ""
    for c in args:
        if quote:
            cur.append(c)
            if c == quote:
                quote = ""
        elif c in "'\"`":
            quote = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur).strip())
    return parts


def receiver(text: str, dot: int) -> str:
    """The expression a method is called on, read backwards from the dot."""
    i = dot
    while i > 0:
        c = text[i - 1]
        if c in ")]":
            depth = 0
            while i > 0:
                i -= 1
                if text[i] in ")]":
                    depth += 1
                elif text[i] in "([":
                    depth -= 1
                    if depth == 0:
                        break
        elif c.isalnum() or c in "_.":
            i -= 1
        else:
            break
    return text[i:dot]


ASSIGN = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)?[ \t]*([A-Za-z_]\w*)(?:\s*:\s*[^=\n]+?)?[ \t]*=(?!=)[ \t]*(.+)$", re.M
)
WITH_AS = re.compile(r"\bwith\s+(.+?)\s+as\s+([A-Za-z_]\w*)")
IMPORT_NAMES = re.compile(r"^\s*(?:from\s+\S+\s+import\s+\(?|import\s+\{)([^)}]*)", re.M)


TUPLE_ASSIGN = re.compile(r"^[ \t]*([A-Za-z_]\w*(?:[ \t]*,[ \t]*[A-Za-z_]\w*)+)[ \t]*=(?!=)[ \t]*(.+)$", re.M)
FOR_IN = re.compile(r"^[ \t]*for[ \t]+(\(?[A-Za-z_]\w*(?:[ \t]*,[ \t]*[A-Za-z_]\w*)*\)?)[ \t]+in[ \t]+(.+?):?$", re.M)
PY_DEF = re.compile(r"\bdef\s+\w+\s*\(([^)]*)\)")
JS_FUNC = re.compile(r"\bfunction\s*\w*\s*\(([^)]*)\)|\(([^()]*)\)\s*(?::\s*[\w<>\[\]| ]+)?\s*=>|\b(\w+)\s*=>")
# A path handed in by the caller (an argument, a command-line value) is checked where the caller builds it.
HANDED_IN = {"argv", "ns", "args"}


def parameters(text: str) -> set[str]:
    names: set[str] = set(HANDED_IN)
    for m in PY_DEF.finditer(text):
        names |= {t for part in m.group(1).split(",") for t in re.findall(r"^\s*\*{0,2}([A-Za-z_]\w*)", part)}
    for m in JS_FUNC.finditer(text):
        group = m.group(1) or m.group(2) or m.group(3) or ""
        names |= {t for part in group.split(",") for t in re.findall(r"^\s*(?:\.\.\.)?([A-Za-z_]\w*)", part)}
    return names


def statement(text: str, start: int) -> str:
    """From `start` to the end of the statement: the line's end once every bracket it opened is closed."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] in "([{":
            depth += 1
        elif text[i] in ")]}":
            depth -= 1
        elif text[i] == "\n" and depth <= 0:
            return text[start:i]
    return text[start:]


def safe_names(text: str) -> set[str]:
    """Names assigned, directly or through other names, from the output root or a temp dir; also parameters."""
    pairs = [(m.group(1), statement(text, m.start(2))) for m in ASSIGN.finditer(text)]
    for m in TUPLE_ASSIGN.finditer(text):
        pairs += [(n.strip(), statement(text, m.start(2))) for n in m.group(1).split(",")]
    for m in FOR_IN.finditer(text):
        pairs += [(n.strip(), m.group(2)) for n in m.group(1).strip("()").split(",")]
    pairs += [(m.group(2), m.group(1)) for m in WITH_AS.finditer(text)]
    safe: set[str] = set(SAFE_IMPORTS) | parameters(text)
    changed = True
    while changed:
        changed = False
        for name, rhs in pairs:
            if name not in safe and (SAFE_CALLS.search(strip_strings(rhs)) or idents(rhs) & safe):
                safe.add(name)
                changed = True
    return safe


def rooted(expr: str, safe: set[str]) -> bool:
    return bool(SAFE_CALLS.search(strip_strings(expr))) or bool(idents(expr) & safe)


def writes(text: str) -> list[tuple[int, str, str]]:
    """(offset, what, path expression) for each call that makes a file or folder."""
    found: list[tuple[int, str, str]] = []
    for m in re.finditer(r"\.screenshot\(", text):
        args = balanced_args(text, m.end() - 1)
        given = [a for a in split_top(args.strip().strip("{}")) if a.startswith("path")]
        found.append((m.start(), "screenshot", given[0].split(":", 1)[1].strip() if given else ""))
    for m in re.finditer(r"\b(" + "|".join(JS_CALLS) + r")\(", text):
        args = split_top(balanced_args(text, m.end() - 1))
        target = args[1] if m.group(1) in ("copyFileSync", "cpSync") and len(args) > 1 else args[0]
        found.append((m.start(), m.group(1), target))
    for m in re.finditer(r"\bopenSync\(([^)]*)\)", text):
        args = split_top(m.group(1))
        if len(args) > 1 and re.search(r"['\"][wa]", args[1]):
            found.append((m.start(), "openSync", args[0]))
    for m in re.finditer(r"\.(" + "|".join(PY_METHODS) + r")\(", text):
        found.append((m.start(), m.group(1), receiver(text, m.start())))
    for m in re.finditer(r"(?<![\w.])open\(", text):
        args = split_top(balanced_args(text, m.end() - 1))
        if len(args) > 1 and re.search(r"['\"][wax]", args[1]):
            found.append((m.start(), "open", args[0]))
    for m in re.finditer(r"\.open\((['\"][wax][^)]*)\)", text):
        found.append((m.start(), "open", receiver(text, m.start())))
    for m in re.finditer(r"\bshutil\.(" + "|".join(PY_FUNCS) + r")\(", text):
        args = split_top(balanced_args(text, m.end() - 1))
        if len(args) > 1:
            found.append((m.start(), f"shutil.{m.group(1)}", args[1]))
    return found


def problems_in(path: Path, rel: str) -> list[str]:
    text = path.read_text(errors="replace")
    safe = safe_names(text)

    def line_of(off: int) -> int:
        return text.count("\n", 0, off) + 1

    out: list[str] = []
    for off, what, expr in writes(text):
        if not rooted(expr, safe):
            shown = " ".join(expr.split())[:70]
            out.append(
                f"{rel}:{line_of(off)}: {what} writes to `{shown}`, not built from evidenceDir/evidence_dir or temp dir"
            )
    own = re.search(r"uc-(\d+)", path.name)
    for m in re.finditer(r"""\bevidence_?[Dd]ir\(\s*['"](?:uc-)?(\d+)['"]""", text):
        if own and m.group(1) != own.group(1):
            out.append(
                f"{rel}:{line_of(m.start())}: writes under case {m.group(1)}; a script uses its own id, {own.group(1)}"
            )
    for i, line in enumerate(text.splitlines(), 1):
        if OUTPUT_LITERAL.search(line) and not line.lstrip().startswith(("//", "#", "*")):
            out.append(f"{rel}:{i}: names an output folder outside the root; build it from evidenceDir/evidence_dir")
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path(".")
    found: list[str] = []
    for p in sorted((root / "docs" / "usecases").rglob("*")):
        rel = str(p.relative_to(root))
        if p.suffix in SUFFIXES and p.is_file() and rel not in EXEMPT:
            found += problems_in(p, rel)
    for line in found:
        print(f"check-usecase-outputs: {line}")
    if found:
        print(f"check-usecase-outputs: {len(found)} problems")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
