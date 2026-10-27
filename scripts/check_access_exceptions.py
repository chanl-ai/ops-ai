"""Fails on access decisions taken outside `can()` that the access register does not record (CLAUDE.md rule 2).

Who may do what is decided by `ops_access.can` over the roles grid and Govern > Policies, with open defaults
(`docs/architecture/roles-and-permissions.md`). This script finds the code shapes that decide access some other
way and compares them with `access-exceptions-allowlist.txt`, where each line names its row in that page's
"Exceptions register". It reads source text only: no imports, no database, no model.

  refusal         a 403 raised or returned outside packages/ops_access, packages/ops_identity and a store, keyed by its
                  error code. Codes of the always-on baseline (BASELINE below) pass without a line.
  role-name       a role name or a service name compared as a string (`role == "admin"`, `svc.sub != "service:x"`,
                  `r === 'viewer'`), in Python and the console.
  lock            a record or tool locked by being system (`protection == "system"`, `SYSTEM_TOOLS`, a `system` claim),
                  and the dev header caller's pass (`auth_method == "dev"`).
  policy-default  each policy in packages/ops_access/src/ops_access/policies.py with its default. Every policy is
                  listed: `open` for an open default, a register row for one that holds something back. A new policy or
                  a changed default fails until it is listed.
  conflict        a 409 by its error code. Most say a record is in the wrong state, but one can refuse by who made a
                  record (a seeded one, a system one). Each code is classified once: `* conflict <code> 0 state` for a
                  state conflict, or a path line with a register row for one that decides access.

A refusal or conflict raised as a typed error counts as well: a class that subclasses Forbidden or Conflict, or that an
error mapper turns into one (`if isinstance(e, X): return Forbidden(...)`), is found wherever it is raised.

Each allowlist line is `path kind key count row`. A finding beyond its line's count fails, and so does a line whose
count is above what the code holds now, so the list can only shrink: lower the count or delete the line when an
exception goes. Each row must be a row of the register (a resolved row holds no lines), `open` for a policy default or
`state` for a conflict. Every commit after the list began that adds a line with a register row must carry a
`Standards-exception:` trailer, the owner's approval through the orchestrator (`--commits`).

  python3 scripts/check_access_exceptions.py            # exit 1 on a new, stale or unregistered exception
  python3 scripts/check_access_exceptions.py --list     # every finding with its line, listed or not
  python3 scripts/check_access_exceptions.py --commits  # exit 1 on an exception line added without the trailer
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "access-exceptions-allowlist.txt"
POLICIES = ROOT / "packages/ops_access/src/ops_access/policies.py"
REGISTER = "docs/architecture/roles-and-permissions.md#exceptions-register"
REGISTER_PAGE = ROOT / "docs/architecture/roles-and-permissions.md"
# The commit that began the list with the exceptions already in the code; lines added after it need the trailer.
LIST_BEGAN = "67f10685"
TRAILER = "Standards-exception:"
# Who approves an exception line: the trailer names them, so a trailer anyone could write does not pass.
APPROVER = "approved by proto-orch"
# Commits whose added lines were approved after they landed, each with the approval and the fix-forward commit that
# records it; an exact sha, never a pattern.
APPROVED_AFTER = {
    # E09 dev-caller moved from agents auth.py into ops_store.isolation (c-409); same decision, total unchanged.
    "07770915": (
        "Standards-exception: E09 dev-caller moved into ops_store.isolation in 07770915; approved by proto-orch"
    ),
}

# The always-on baseline the owner set (roles-and-permissions.md, "How access is decided"): token identity, team and
# tenant isolation, scoped service and API key tokens, the embed's configured origins, and secrets kept hidden. A 403
# with one of these codes is that baseline, not an exception.
BASELINE = {
    "team_forbidden": "team isolation",
    "team_required": "team isolation",
    "team_mismatch": "team isolation",
    "tenant_required": "tenant isolation",
    "scope_required": "scoped service token",
    "event_not_owned": "scoped service token",
    "key_target": "scoped API key",
    "api_key_refused": "token identity",
    "widget_key_other_deployment": "scoped API key",
    "not_the_invitee": "token identity",
    "key_not_registered": "token identity",
    "origin_required": "embed origin from config",
    "origin_mismatch": "embed origin from config",
    "origin_not_allowed": "embed origin from config",
    "secret_refused": "secrets hidden",
}
# Where a refusal belongs: the one access check, the token checks under it, and store guards.
REFUSAL_HOMES = ("packages/ops_access/", "packages/ops_identity/", "packages/ops_store/")
ROLES = "admin|owner|builder|approver|reviewer|viewer|chat_user|security_admin"
# Left-hand names that hold something other than a person's role (a message's role, a node's kind).
NOT_A_ROLE = re.compile(r"(kind|type|status|variant|mode|tab|view|sort|shape|step)$", re.IGNORECASE)
PY_ROLE = [
    re.compile(rf"([\w.\[\]\"']+)\s*(?:==|!=)\s*[\"']({ROLES})[\"']"),
    re.compile(rf"[\"']({ROLES})[\"']\s*(?:==|!=)\s*([\w.]+)"),
]
PY_SUB = re.compile(r"\b\w+\.sub\s*(?:==|!=)\s*([\w\"':.-]+)")
TS_ROLE = re.compile(rf"([\w.?]+)\s*(?:===|!==|==|!=)\s*['\"]({ROLES})['\"]")
LOCKS = [
    ("protection-system", re.compile(r"protection\"?\)?\s*(?:==|!=)\s*[\"']system[\"']")),
    ("SYSTEM_TOOLS", re.compile(r"\bSYSTEM_TOOLS\b")),
    ("SYSTEM_ONLY", re.compile(r"\bSYSTEM_ONLY\b")),
    ("system-claim", re.compile(r"\.get\([\"']system[\"']\)\s*(?:is|==)")),
    # The dev header caller, which holds no role, passing rules a person with a role would meet.
    ("dev-caller", re.compile(r"auth_method\s*(?:==|!=)\s*[\"']dev[\"']")),
]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    key: str
    text: str


def _skipped(rel: str) -> bool:
    return any(part in rel for part in ("/tests/", "/migrations/", "/mock/", "/__pycache__/")) or rel.endswith(".d.ts")


def _python_files() -> list[Path]:
    roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")]
    return sorted(p for r in roots for p in r.rglob("*.py") if not _skipped(p.relative_to(ROOT).as_posix()))


def _console_files() -> list[Path]:
    roots = [ROOT / "apps/console/src", ROOT / "apps/embed/src"]
    files = [p for r in roots if r.exists() for p in [*r.rglob("*.ts"), *r.rglob("*.tsx")]]
    return sorted(p for p in files if not _skipped(p.relative_to(ROOT).as_posix()))


def _code(call: ast.Call) -> str:
    """The error code a refusal carries: its `code=` keyword, else the first string after a 403, else `forbidden`."""
    for kw in call.keywords:
        if kw.arg == "code" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    args = call.args
    for i, a in enumerate(args):
        if isinstance(a, ast.Constant) and a.value == 403:
            nxt = args[i + 1] if i + 1 < len(args) else None
            if isinstance(nxt, ast.Constant) and isinstance(nxt.value, str):
                return nxt.value
    return "forbidden"


def _is_403(call: ast.Call) -> bool:
    name = _name(call)
    if name == "Forbidden":
        return True
    consts = [a for a in call.args if isinstance(a, ast.Constant)]
    consts += [kw.value for kw in call.keywords if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)]
    return any(c.value == 403 for c in consts) and name not in ("error_responses",)


# Error classes raised in place of Forbidden or Conflict, by class name: (status, code). Filled by _typed() before the
# files are read, since a class is often mapped in one module and raised in another.
TYPED: dict[str, tuple[int, str]] = {}


def _typed(trees: list[ast.AST]) -> dict[str, tuple[int, str]]:
    """Classes that subclass Forbidden or Conflict, and classes an error mapper turns into one of them."""
    out: dict[str, tuple[int, str]] = {}
    status = {"Forbidden": 403, "Conflict": 409}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                    if name in status:
                        out[node.name] = (status[name], "forbidden" if name == "Forbidden" else "conflict")
            # if isinstance(e, A | B): return Forbidden(..., code=...)
            if isinstance(node, ast.If) and isinstance(node.test, ast.Call) and _name(node.test) == "isinstance":
                made = next(
                    (
                        n.value
                        for n in node.body
                        if isinstance(n, ast.Return) and isinstance(n.value, ast.Call) and _name(n.value) in status
                    ),
                    None,
                )
                if made is None or len(node.test.args) < 2:
                    continue
                code = _code(made) if _name(made) == "Forbidden" else _conflict_code(made)
                for cls in _names(node.test.args[1]):
                    out[cls] = (status[_name(made)], code)
    return out


def _names(node: ast.expr) -> list[str]:
    """The class names in `A`, `A | B` or `(A, B)`."""
    if isinstance(node, ast.BinOp):
        return [*_names(node.left), *_names(node.right)]
    if isinstance(node, ast.Tuple):
        return [n for e in node.elts for n in _names(e)]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    return [node.id] if isinstance(node, ast.Name) else []


def _conflict_code(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "code" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return "conflict"


def _conflicts(rel: str, tree: ast.AST, lines: list[str]) -> list[Finding]:
    """Every 409 by its code: Conflict(...) raised or returned, and a typed 409 raised."""
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node)
        if name == "Conflict":
            code = _conflict_code(node)
        elif TYPED.get(name, (0, ""))[0] == 409 and _raised(tree, node):
            code = TYPED[name][1]
        else:
            continue
        out.append(Finding(rel, node.lineno, "conflict", code, lines[node.lineno - 1].strip()))
    return out


def _raised(tree: ast.AST, call: ast.Call) -> bool:
    return any(isinstance(n, ast.Raise) and n.exc is call for n in ast.walk(tree))


def _refusals(rel: str, tree: ast.AST, lines: list[str]) -> list[Finding]:
    if rel.startswith(REFUSAL_HOMES) or "/store/" in rel:
        return []
    out: list[Finding] = []
    seen: set[int] = set()
    for node in ast.walk(tree):
        # A typed error an error mapper turns into a 403, raised under its own class name.
        exc = node.exc if isinstance(node, ast.Raise) else None
        if isinstance(exc, ast.Call) and TYPED.get(_name(exc), (0, ""))[0] == 403:
            call = exc
            if call.lineno not in seen:
                seen.add(call.lineno)
                code = TYPED[_name(call)][1]
                if code not in BASELINE:
                    out.append(Finding(rel, call.lineno, "refusal", code, lines[call.lineno - 1].strip()))
            continue
        # A raised Forbidden, or a response built with status 403 (an exception handler, a gateway refusal).
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            call = node.exc
        elif isinstance(node, ast.Call) and _name(node) != "Forbidden":
            call = node
        else:
            continue
        if not _is_403(call) or call.lineno in seen:
            continue
        seen.add(call.lineno)
        code = _code(call)
        if code in BASELINE:
            continue
        out.append(Finding(rel, call.lineno, "refusal", code, lines[call.lineno - 1].strip()))
    return out


def _name(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")


def _python(path: Path) -> list[Finding]:
    rel = path.relative_to(ROOT).as_posix()
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)
    found = [*_refusals(rel, tree, lines), *_conflicts(rel, tree, lines)]
    for n, line in enumerate(lines, 1):
        code = line.split("#", 1)[0]
        for rx in PY_ROLE:
            for m in rx.finditer(code):
                left, role = (m.group(1), m.group(2)) if rx is PY_ROLE[0] else (m.group(2), m.group(1))
                if not NOT_A_ROLE.search(left.strip("\"'[]")):
                    found.append(Finding(rel, n, "role-name", role, line.strip()))
        for _ in PY_SUB.finditer(code):
            found.append(Finding(rel, n, "role-name", "service-sub", line.strip()))
        for key, rx in LOCKS:
            if rx.search(code) and not rel.startswith("packages/ops_access/src/ops_access/__init__"):
                found.append(Finding(rel, n, "lock", key, line.strip()))
    return found


def _console(path: Path) -> list[Finding]:
    rel = path.relative_to(ROOT).as_posix()
    found: list[Finding] = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("//", 1)[0]
        for m in TS_ROLE.finditer(code):
            if not NOT_A_ROLE.search(m.group(1).split(".")[-1].rstrip("?")):
                found.append(Finding(rel, n, "role-name", m.group(2), line.strip()))
    return found


def _policies() -> list[Finding]:
    rel = POLICIES.relative_to(ROOT).as_posix()
    out: list[Finding] = []
    for node in ast.walk(ast.parse(POLICIES.read_text())):
        if isinstance(node, ast.Call) and _name(node) == "Policy" and len(node.args) >= 2:
            key, default = ast.literal_eval(node.args[0]), ast.literal_eval(node.args[1])
            value = json.dumps(default, separators=(",", ":"), sort_keys=True)
            out.append(Finding(rel, node.lineno, "policy-default", f"{key}={value}", f"{key} defaults to {value}"))
    return out


def findings() -> list[Finding]:
    TYPED.clear()
    TYPED.update(_typed([ast.parse(p.read_text()) for p in _python_files()]))
    return [
        *(f for p in _python_files() for f in _python(p)),
        *(f for p in _console_files() for f in _console(p)),
        *_policies(),
    ]


def allowlist() -> dict[tuple[str, str, str], tuple[int, str]]:
    allowed: dict[tuple[str, str, str], tuple[int, str]] = {}
    for raw in ALLOWLIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, kind, key, count, row = line.split()
        allowed[(path, kind, key)] = (int(count), row)
    return allowed


def register() -> dict[str, str]:
    """Each Exceptions register row id with its Status cell."""
    rows: dict[str, str] = {}
    section = REGISTER_PAGE.read_text().split("## Exceptions register", 1)[-1].split("\n## ", 1)[0]
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"E\d+", cells[0]):
            rows[cells[0]] = cells[-1]
    return rows


def committed() -> set[tuple[str, str, str]] | None:
    """The lines of the allowlist at HEAD, which a line being added is not among; None where there is no history to
    read (verify-head's export). verify-staged passes the repository's GIT_DIR into its export."""
    shown = subprocess.run(
        ["git", "show", f"HEAD:{ALLOWLIST.name}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if shown.returncode:
        return None
    keys: set[tuple[str, str, str]] = set()
    for raw in shown.stdout.splitlines():
        parts = raw.split()
        if len(parts) == 5 and not raw.startswith("#"):
            keys.add((parts[0], parts[1], parts[2]))
    return keys


def _row_problems(
    allowed: dict[tuple[str, str, str], tuple[int, str]], base: set[tuple[str, str, str]] | None = None
) -> tuple[list[str], list[str]]:
    """Lines whose row is not in the register, is resolved, or is not the right word for the line's kind, and a line
    being added on a row with no decision; and the lines already there resting on a row with no decision, which go to
    the owner but do not fail."""
    rows = register()
    problems: list[str] = []
    owner: list[str] = []
    for (path, kind, key), (_, row) in allowed.items():
        if row == "open":
            if kind != "policy-default":
                problems.append(f"row   {path}  {kind} {key}: `open` names only a policy's open default")
        elif row == "state":
            if kind != "conflict":
                problems.append(f"row   {path}  {kind} {key}: `state` names only a conflict that is a record's state")
        elif row not in rows:
            problems.append(f"row   {path}  {kind} {key}: {row} is not a row of the register")
        elif "resolved" in rows[row].lower():
            problems.append(f"row   {path}  {kind} {key}: {row} is resolved, so the line goes")
        elif "no decision" in rows[row].lower():
            if base is not None and (path, kind, key) not in base:
                problems.append(
                    f"row   {path}  {kind} {key}: {row} has no decision; the owner decides before a line is added"
                )
            else:
                owner.append(f"{row} {path} {kind} {key}")
    return problems, owner


def commit_problems() -> list[str]:
    """Commits after the list began that add a line with a register row and carry no Standards-exception: trailer
    naming its approver, or add one on a row with no decision. An export without history (verify-head's one-commit copy)
    has nothing to check; verify-staged runs it on the repo."""
    known = ["git", "cat-file", "-e", f"{LIST_BEGAN}^{{commit}}"]
    if subprocess.run(known, cwd=ROOT, capture_output=True, check=False).returncode:
        return []
    log = subprocess.run(
        ["git", "log", "--format=%H", f"{LIST_BEGAN}..HEAD", "--", ALLOWLIST.name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    rows = register()
    out: list[str] = []
    for sha in log:
        diff = subprocess.run(
            ["git", "show", "--format=", "--unified=0", sha, "--", ALLOWLIST.name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        added = [
            line[1:]
            for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++") and re.search(r"\sE\d+\s*$", line)
        ]
        message = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
        approved = APPROVED_AFTER.get(sha[:8], "")
        lines = [*message.splitlines(), approved]
        if added and not any(line.startswith(TRAILER) and APPROVER in line for line in lines):
            for line in added:
                out.append(f"trailer {sha[:8]} adds `{line.strip()}` with no {TRAILER} trailer saying {APPROVER}")
        for line in added:
            row = line.split()[-1]
            if "no decision" in rows.get(row, "").lower():
                out.append(f"row     {sha[:8]} adds `{line.strip()}` on {row}, which has no decision")
    return out


def main(argv: list[str]) -> int:
    if "--commits" in argv:
        missing = commit_problems()
        print(
            "\n".join(missing)
            if missing
            else f"Every exception line added since {LIST_BEGAN} carries {TRAILER} {APPROVER}"
        )
        return 1 if missing else 0
    found = findings()
    if "--list" in argv:
        for f in found:
            print(f"{f.path}:{f.line}  {f.kind}  {f.key}  {f.text[:110]}")
        return 0
    allowed = allowlist()
    counts = Counter((f.path, f.kind, f.key) for f in found)
    problems, owner = _row_problems(allowed, committed())
    for f in found:
        k = (f.path, f.kind, f.key)
        if f.kind == "conflict" and ("*", f.kind, f.key) in allowed:
            continue
        if counts[k] > allowed.get(k, (0, ""))[0]:
            problems.append(f"new   {f.path}:{f.line}  {f.kind} {f.key}: {f.text[:100]}")
    codes = Counter(f.key for f in found if f.kind == "conflict")
    for k, (count, row) in allowed.items():
        if k[0] == "*":
            if not codes[k[2]]:
                problems.append(f"stale *  {k[1]} {k[2]}: no 409 carries this code now; delete the line")
        elif counts[k] < count:
            problems.append(f"stale {k[0]}  {k[1]} {k[2]}: listed {count} ({row}), found {counts[k]}; lower the line")
    if problems:
        print(f"Access decided outside can() and not in the register ({REGISTER}):")
        print("\n".join(dict.fromkeys(problems)))
        print(
            "Move the rule into a roles-grid cell or a policy read by can(). If the owner decided it stays, add a row "
            "to the register and a line to access-exceptions-allowlist.txt with a Standards-exception: trailer."
        )
        return 1
    for line in owner:
        print(f"no decision, for the owner: {line}")
    print(f"Access exceptions: {sum(counts.values())} findings, all in the register.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
