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
  flag            an admin flag read in place of a cell: `is_admin` in Python, `.isAdmin` or `is_admin` read off a
                  caller or session in the console. None is allowed and no line can list one.
  role-set        a role tested against a written list of role names (`role in ("admin", "builder")`,
                  `['admin', 'owner'].includes(role)`). None is allowed and no line can list one.
  owner-compare   a record's owner or maker compared with the caller (`row.owner == me.sub`) outside ops_access and
                  a store. Those in the code today are counted in the lane's baseline file, which may only fall.
  policy-read     a policy's value read some other way than `ops_access.policies.policy(p, key)`: a token's
                  `.policies.get(`, or `BY_KEY[key].default` written at the call. Counted in the lane's baseline file.
  conflict        a 409 by its error code. Most say a record is in the wrong state, but one can refuse by who made a
                  record (a seeded one, a system one). Each code is classified once: `* conflict <code> 0 state` for a
                  state conflict, or a path line with a register row for one that decides access.

A refusal or conflict raised as a typed error counts as well: a class that subclasses Forbidden or Conflict, or that an
error mapper turns into one (`if isinstance(e, X): return Forbidden(...)`), is found wherever it is raised.

Each allowlist line is `path kind key count row  # outcome lane: reason`. The outcome is what the lane named does
with the line when it moves onto the standards: `keep` (with the reason it stays), `convert` (onto `can()` or
`policy()`) or `delete` (with its code). A line with a register row or `open` and no outcome fails. A finding beyond
its line's count fails, and so does a line whose count is above what the code holds now, so the list can only shrink:
lower the count or delete the line when an exception goes. Each row must be a row of the register (a resolved row
holds no lines), `open` for a policy default or `state` for a conflict. A line on a row whose status reads "no
decision" fails: the decision is written on the register first.

Role-name compares, owner compares and policy reads are also counted per lane in
`scripts/access-baselines/<lane>.txt` (`path kind key count`); a lane's total of a kind may only fall, against the
committed file and in every commit (`--commits`), and the lane takes its file to zero.

Every commit after the list began that adds a line with a register row needs an approving review on the pull request
from a maintainer (`--commits`, scripts/baseline_history.py).

  python3 scripts/check_access_exceptions.py            # exit 1 on a new, stale or unregistered exception
  python3 scripts/check_access_exceptions.py --list     # every finding with its line, listed or not
  python3 scripts/check_access_exceptions.py --commits  # exit 1 on an exception line added without the trailer
  python3 scripts/check_access_exceptions.py --self-test  # plants one of each shape; exit 1 if any passes
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "access-exceptions-allowlist.txt"
POLICIES = ROOT / "packages/ops_access/src/ops_access/policies.py"
REGISTER = "docs/architecture/roles-and-permissions.md#exceptions-register"
REGISTER_PAGE = ROOT / "docs/architecture/roles-and-permissions.md"
# One file per lane of the migration (docs/architecture/migration/README.md), holding the role-name compares, owner
# compares and policy reads in that lane's code today.
BASELINES = ROOT / "scripts/access-baselines"
LANES = ("components", "pilot", "platform", "kb", "tools", "agents", "console")
PILOT_SERVICES = ("documents", "files", "models", "runner")
# Kinds counted in a lane's file. A role-name compare is on the allowlist as well, with its register row.
BASELINED = ("role-name", "owner-compare", "policy-read")
# Kinds with a ceiling of zero: no allowlist line and no baseline row lets one through.
NEVER = ("flag", "role-set")
OUTCOMES = ("keep", "convert", "delete")
# The commit that began the list with the exceptions already in the code; lines added after it need the trailer.
LIST_BEGAN = "67f10685"

# The always-on baseline (roles-and-permissions.md, "How access is decided"): token identity, team and
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
    "key_revoked": "token identity",
    "key_expired": "token identity",
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
# A caller's subject compared with a service's; a table's `sub` column (`<table>.c.sub`) filtered by it is not one.
PY_SUB = re.compile(r"\b(?!c\.sub)\w+\.sub\s*(?:==|!=)\s*([\w\"':.-]+)")
TS_ROLE = re.compile(rf"([\w.?]+)\s*(?:===|!==|==|!=)\s*['\"]({ROLES})['\"]")
LOCKS = [
    ("protection-system", re.compile(r"protection\"?\)?\s*(?:==|!=)\s*[\"']system[\"']")),
    ("SYSTEM_TOOLS", re.compile(r"\bSYSTEM_TOOLS\b")),
    ("SYSTEM_ONLY", re.compile(r"\bSYSTEM_ONLY\b")),
    ("system-claim", re.compile(r"\.get\([\"']system[\"']\)\s*(?:is|==)")),
    # The dev header caller, which holds no role, passing rules a person with a role would meet.
    ("dev-caller", re.compile(r"auth_method\s*(?:==|!=)\s*[\"']dev[\"']")),
]


ACCESS_HOME = "packages/ops_access/"
PY_FLAG = re.compile(r"\bis_admin\b")
# A local named `isAdmin` holding a `useCan` answer is not a flag; one read off another object is.
TS_FLAG = re.compile(r"\.isAdmin\b|\bis_admin\b")
PY_ROLE_SET = re.compile(rf"([\w.\[\]\"']+)\s+(?:not\s+)?in\s+[\(\[\{{][^\)\]\}}]*[\"']({ROLES})[\"']")
TS_ROLE_SET = re.compile(rf"\[[^\]]*?['\"]({ROLES})['\"][^\]]*\]\.includes\(")
_OWNED = r"(?:owner|created_by|createdBy)[\w\"'\]\)\(.]*"
_CALLER = r"(?:me|p|who|actor|principal|caller|session|user)\??\.(?:sub|user_id|userId|name|email|id)\b"
OWNER_COMPARE = [
    re.compile(rf"{_OWNED}\s*(?:===?|!==?)\s*{_CALLER}"),
    re.compile(rf"\b{_CALLER}[\w.()]*\s*(?:===?|!==?)\s*[\w.\[\(\"']*(?:owner|created_by|createdBy)"),
]
# The one reader of a policy's value is `policy(p, key)` in this file.
POLICY_READ = re.compile(r"\.policies\.get\(|\.policies\[|\bBY_KEY\[[^\]]+\]\.default\b")


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
        # A refusal returned as a (403, "CODE", ...) tuple, which the gateway turns into its answer.
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) >= 2:
            status, code = node.value.elts[0], node.value.elts[1]
            if (
                isinstance(status, ast.Constant)
                and status.value == 403
                and isinstance(code, ast.Constant)
                and isinstance(code.value, str)
                and node.lineno not in seen
            ):
                seen.add(node.lineno)
                if code.value not in BASELINE:
                    out.append(Finding(rel, node.lineno, "refusal", code.value, lines[node.lineno - 1].strip()))
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
        found.extend(_shapes(rel, n, code, line, flag=PY_FLAG, role_set=PY_ROLE_SET))
    return found


def _shapes(
    rel: str, n: int, code: str, line: str, *, flag: re.Pattern[str], role_set: re.Pattern[str]
) -> list[Finding]:
    """The flag, role-set, owner-compare and policy-read shapes on one line. ops_access is where a grid, an owner and
    a policy are read, so nothing in it is one of these; a store's owner compare is a query's filter."""
    if rel.startswith(ACCESS_HOME):
        return []
    out: list[Finding] = []
    if flag.search(code):
        out.append(Finding(rel, n, "flag", "is_admin", line.strip()))
    for m in role_set.finditer(code):
        if role_set is TS_ROLE_SET or not NOT_A_ROLE.search(m.group(1).strip("\"'[]")):
            out.append(Finding(rel, n, "role-set", m.group(m.lastindex or 1), line.strip()))
    if "/store/" not in rel and any(rx.search(code) for rx in OWNER_COMPARE):
        out.append(Finding(rel, n, "owner-compare", "owner", line.strip()))
    if POLICY_READ.search(code):
        out.append(Finding(rel, n, "policy-read", "policies", line.strip()))
    return out


def _console(path: Path) -> list[Finding]:
    rel = path.relative_to(ROOT).as_posix()
    found: list[Finding] = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("//", 1)[0]
        for m in TS_ROLE.finditer(code):
            if not NOT_A_ROLE.search(m.group(1).split(".")[-1].rstrip("?")):
                found.append(Finding(rel, n, "role-name", m.group(2), line.strip()))
        found.extend(_shapes(rel, n, code, line, flag=TS_FLAG, role_set=TS_ROLE_SET))
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


def _fields(raw: str) -> tuple[list[str], str]:
    """A line's five fields and its outcome comment; no fields for a blank line or a comment."""
    line, _, note = raw.partition(" # ")
    line = line.strip()
    return ([] if line.startswith("#") else line.split()), note.strip()


def allowlist() -> dict[tuple[str, str, str], tuple[int, str]]:
    allowed: dict[tuple[str, str, str], tuple[int, str]] = {}
    for raw in ALLOWLIST.read_text().splitlines():
        fields, _ = _fields(raw)
        if not fields:
            continue
        path, kind, key, count, row = fields
        allowed[(path, kind, key)] = (int(count), row)
    return allowed


def outcome_problems() -> list[str]:
    """Lines with a register row or `open` that do not say what their lane does with them: `# keep <lane>: <reason>`,
    `# convert <lane>: <onto what>` or `# delete <lane>: <with what>`. A `state` conflict is no exception."""
    out: list[str] = []
    for raw in ALLOWLIST.read_text().splitlines():
        fields, note = _fields(raw)
        if len(fields) != 5 or fields[4] == "state":
            continue
        head, _, reason = note.partition(":")
        said = head.split()
        where = f"outcome {fields[0]}  {fields[1]} {fields[2]}"
        if len(said) != 2 or said[0] not in OUTCOMES or said[1] not in LANES:
            out.append(f"{where}: needs `# <{'|'.join(OUTCOMES)}> <lane>: <reason>` ({', '.join(LANES)})")
        elif not reason.strip():
            out.append(f"{where}: `{said[0]}` needs its reason after the colon")
    return out


def lane_of(rel: str) -> str | None:
    """The migration lane that owns a path; None for a service no lane names."""
    top, _, rest = rel.partition("/")
    if top == "apps":
        return "console"
    if top == "packages":
        return "components"
    name = rest.split("/", 1)[0].removesuffix("-service")
    return "pilot" if name in PILOT_SERVICES else name if name in LANES else None


def _rows(text: str) -> dict[tuple[str, str, str], int]:
    rows: dict[tuple[str, str, str], int] = {}
    for raw in text.splitlines():
        fields, _ = _fields(raw)
        if fields:
            path, kind, key, count = fields
            rows[(path, kind, key)] = int(count)
    return rows


def _totals(text: str) -> Counter[str]:
    totals: Counter[str] = Counter()
    for (_, kind, _), count in _rows(text).items():
        totals[kind] += count
    return totals


def committed_baseline(lane: str) -> str | None:
    """A lane's file at HEAD; None where it is not committed yet or there is no history to read."""
    name = (BASELINES / f"{lane}.txt").relative_to(ROOT).as_posix()
    shown = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT, capture_output=True, text=True, check=False)
    return None if shown.returncode else shown.stdout


def _rises(name: str, before: str, now: str) -> list[str]:
    was, held = _totals(before), _totals(now)
    return [
        f"rose  {name} {kind} rose from {was[kind]} to {held[kind]}; a lane's baseline may only fall"
        for kind in sorted(held)
        if held[kind] > was[kind]
    ]


def baseline_problems(counts: Counter[tuple[str, str, str]]) -> list[str]:
    """Role-name compares, owner compares and policy reads against their lane's file: one beyond its row, a row above
    what the code holds, a row in the wrong lane's file, a path no lane owns, and a total above the committed file's."""
    out: list[str] = []
    listed: dict[tuple[str, str, str], int] = {}
    for lane in LANES:
        path = BASELINES / f"{lane}.txt"
        if not path.exists():
            out.append(f"lane  {path.name} is missing; every lane has a baseline file, empty when it holds nothing")
            continue
        text = path.read_text()
        for k, count in _rows(text).items():
            if k[1] not in BASELINED or lane_of(k[0]) != lane:
                out.append(f"lane  {path.name} lists {k[0]} {k[1]}, which is not a {'/'.join(BASELINED)} of its lane")
            listed[k] = count
        before = committed_baseline(lane)
        if before is not None:
            out.extend(_rises(path.name, before, text))
    for k in sorted({*listed, *(k for k in counts if k[1] in BASELINED)}):
        lane = lane_of(k[0])
        if lane is None:
            out.append(f"lane  {k[0]}  {k[1]} {k[2]}: no migration lane owns this path; add its service to a lane")
        elif counts[k] < listed.get(k, 0):
            out.append(f"stale {k[0]}  {k[1]} {k[2]}: {lane}.txt lists {listed[k]}, found {counts[k]}; lower the row")
    return out


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
        parts, _ = _fields(raw)
        if len(parts) == 5:
            keys.add((parts[0], parts[1], parts[2]))
    return keys


def _row_problems(
    allowed: dict[tuple[str, str, str], tuple[int, str]], base: set[tuple[str, str, str]] | None = None
) -> list[str]:
    """Lines whose row is not in the register, is resolved, has no decision, or is not the right word for the line's
    kind; and a line for a kind that no line can list."""
    rows = register()
    problems: list[str] = []
    for (path, kind, key), (_, row) in allowed.items():
        if kind in NEVER or kind in BASELINED[1:]:
            where = "is never allowed" if kind in NEVER else "is counted in its lane's baseline file"
            problems.append(f"row   {path}  {kind} {key}: a {kind} {where}, not listed here")
        elif row == "open":
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
            added = base is not None and (path, kind, key) not in base
            when = "before a line is added" if added else "and the register records it before this passes"
            problems.append(f"row   {path}  {kind} {key}: {row} has no decision; a maintainer decides {when}")
    return problems


def commit_problems() -> list[str]:
    """Commits after the list began that add a line with a register row, which wait for a maintainer's review on the
    pull request (scripts/baseline_history.py), or add one on a row with no decision, which no review approves. An
    export without history (verify-head's one-commit copy) has nothing to check; verify-staged runs it on the repo."""
    began = baseline_history.history_start(LIST_BEGAN)
    known = ["git", "cat-file", "-e", f"{began}^{{commit}}"]
    if subprocess.run(known, cwd=ROOT, capture_output=True, check=False).returncode:
        return []
    log = subprocess.run(
        ["git", "log", "--format=%H", f"{began}..HEAD", "--", ALLOWLIST.name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    rows = register()
    out: list[str] = []
    awaiting: list[str] = baseline_history.list_rises(ROOT, began)
    for sha in log:
        # Added: a line whose five fields the parent's file does not hold. An outcome comment alone adds nothing; a
        # new line behind a comment, or a raised count, does.
        before = {tuple(_fields(raw)[0]) for raw in (_at(f"{sha}^", ALLOWLIST.name) or "").splitlines()}
        added = [
            " ".join(fields)
            for fields in (_fields(raw)[0] for raw in (_at(sha, ALLOWLIST.name) or "").splitlines())
            if len(fields) == 5 and tuple(fields) not in before and re.fullmatch(r"E\d+", fields[4])
        ]
        awaiting += [f"{sha[:8]} adds `{line.strip()}` to {ALLOWLIST.name}" for line in added]
        for line in added:
            row = line.split()[-1]
            if "no decision" in rows.get(row, "").lower():
                out.append(f"row     {sha[:8]} adds `{line.strip()}` on {row}, which has no decision")
    if not BASELINES.is_relative_to(ROOT):
        return [*out, *baseline_history.awaiting_review(awaiting)]
    folder = BASELINES.relative_to(ROOT).as_posix()
    touched = ["git", "log", "--format=%H", f"{began}..HEAD", "--", folder]
    for sha in subprocess.run(touched, cwd=ROOT, capture_output=True, text=True, check=True).stdout.split():
        for lane in LANES:
            name = f"{folder}/{lane}.txt"
            was = _at(f"{sha}^", name)
            if was is not None:
                awaiting.extend(f"{r} ({sha[:8]})" for r in _rises(f"{lane}.txt", was, _at(sha, name) or ""))
    return [*out, *baseline_history.awaiting_review(awaiting)]


def _at(rev: str, name: str) -> str | None:
    """A file as a commit holds it; None where the commit has no such file."""
    shown = subprocess.run(["git", "show", f"{rev}:{name}"], cwd=ROOT, capture_output=True, text=True, check=False)
    return None if shown.returncode else shown.stdout


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if "--commits" in argv:
        missing = commit_problems()
        print(
            "\n".join(missing)
            if missing
            else f"Every exception line added since {LIST_BEGAN} is approved or none was added"
        )
        return 1 if missing else 0
    found = findings()
    if "--list" in argv:
        for f in found:
            print(f"{f.path}:{f.line}  {f.kind}  {f.key}  {f.text[:110]}")
        return 0
    allowed = allowlist()
    counts = Counter((f.path, f.kind, f.key) for f in found)
    problems = [*_row_problems(allowed, committed()), *outcome_problems(), *baseline_problems(counts)]
    listed = {k: n for lane in LANES for k, n in _rows(_read(BASELINES / f"{lane}.txt")).items()}
    for f in found:
        k = (f.path, f.kind, f.key)
        if f.kind == "conflict" and ("*", f.kind, f.key) in allowed:
            continue
        if f.kind in BASELINED and counts[k] > listed.get(k, 0):
            problems.append(f"new   {f.path}:{f.line}  {f.kind} {f.key}: {f.text[:100]}")
        if f.kind not in BASELINED[1:] and counts[k] > allowed.get(k, (0, ""))[0]:
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
            "Move the rule into a roles-grid cell or a policy read by can(). If a maintainer decided it stays, add a "
            "row to the register and a line to access-exceptions-allowlist.txt; a maintainer reviews the line on the "
            "pull request."
        )
        return 1
    print(f"Access exceptions: {sum(counts.values())} findings, all in the register.")
    return 0


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


# What --self-test plants in a small clean tree, one at a time: the kind, the file, its text, and what the checker
# must say. Each is a decision taken outside can() that nothing lists.
PLANTS = (
    ("flag", "services/tools-service/src/t/a.py", "def f(me):\n    return me.is_admin\n", "flag is_admin"),
    ("flag", "apps/console/src/a.tsx", "const show = session.isAdmin;\n", "flag is_admin"),
    (
        "role-set",
        "services/kb-service/src/k/a.py",
        'def f(role):\n    return role in ("admin", "builder")\n',
        "role-set",
    ),
    ("role-set", "apps/console/src/b.ts", "const may = ['admin', 'owner'].includes(role);\n", "role-set admin"),
    (
        "owner-compare",
        "services/agents-service/src/a/a.py",
        "def f(me, row):\n    return row.owner == me.sub\n",
        "owner",
    ),
    (
        "policy-read",
        "services/files-service/src/f/a.py",
        'def f(p):\n    return p.policies.get("stepUp")\n',
        "policy-read",
    ),
    (
        "role-name",
        "services/platform-service/src/p/a.py",
        'def f(m):\n    return m.role == "admin"\n',
        "role-name admin",
    ),
)
_CLEAN_POLICIES = 'POLICIES = (Policy("stepUp", False, "x"),)\n'
_CLEAN_REGISTER = "## Exceptions register\n\n| Row | Exception | Status |\n|---|---|---|\n| E01 | x | {status} |\n"
_CLEAN_ALLOW = (
    "packages/ops_access/src/ops_access/policies.py policy-default stepUp=false 1 open  # keep platform: open\n"
    "services/tools-service/src/t/b.py lock SYSTEM_TOOLS 1 E01{note}\n"
)


def self_test() -> int:
    """Builds a small tree the checker passes, then plants one of each shape, a row with no decision and a line with
    no outcome, expecting exit 1 that names the plant each time. Exit 1 when the clean tree fails or a plant passes."""
    # A hook exports GIT_DIR, which would point the temp tree's git reads at this repository.
    os.environ.pop("GIT_DIR", None)
    failed: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        g = globals()
        g.update(
            ROOT=root,
            ALLOWLIST=root / ALLOWLIST.name,
            POLICIES=root / "packages/ops_access/src/ops_access/policies.py",
            REGISTER_PAGE=root / "register.md",
            BASELINES=root / "lanes",
        )

        def write(rel: str, text: str) -> Path:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return path

        def run() -> tuple[int, str]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main([])
            return code, out.getvalue()

        def clean(status: str = "decided", note: str = "  # keep tools: a system tool") -> None:
            write(ALLOWLIST.name, _CLEAN_ALLOW.format(note=note))
            write("register.md", _CLEAN_REGISTER.format(status=status))

        write("packages/ops_access/src/ops_access/policies.py", _CLEAN_POLICIES)
        write("services/tools-service/src/t/b.py", "SYSTEM_TOOLS = ()\n")
        for lane in LANES:
            write(f"lanes/{lane}.txt", "")
        clean()
        code, out = run()
        if code:
            failed.append(f"the clean tree fails:\n{out}")

        def expect(name: str, says: str) -> None:
            code, out = run()
            red = code == 1 and says in out
            print(f"{'red  ' if red else 'GREEN'} {name}: {says}")
            if not red:
                failed.append(f"{name} passed the checker (exit {code}):\n{out}")

        for kind, rel, text, says in PLANTS:
            planted = write(rel, text)
            expect(f"{kind} in {rel}", says)
            planted.unlink()
        clean(status="**no decision**")
        expect("no decision on a register row", "E01 has no decision")
        clean(note="")
        expect("outcome missing from a line", "outcome services/tools-service/src/t/b.py")
        clean()
        if run()[0]:
            failed.append("the tree is not clean again after the plants")
    print("\n".join(failed) if failed else f"Self-test: {len(PLANTS) + 2} plants, each turned the checker red.")
    return 1 if failed else 0


def _repo_python() -> None:
    """The scanned sources use the repository's Python (3.12 syntax, `type X = ...`), which an older interpreter's
    parser refuses: run again under the repository's environment, or say which Python it needs."""
    if sys.version_info >= (3, 12):  # noqa: UP036 - a hook or a person may run it with an older python3
        return
    venv = ROOT / ".venv" / "bin" / "python"
    if venv.exists():
        os.execv(venv, [str(venv), __file__, *sys.argv[1:]])
    if shutil.which("uv"):
        os.execvp("uv", ["uv", "run", "--project", str(ROOT), "python", __file__, *sys.argv[1:]])
    sys.exit(
        f"check_access_exceptions needs Python 3.12 (this is {sys.version.split()[0]}); run `uv run python {__file__}`"
    )


if __name__ == "__main__":
    _repo_python()
    sys.exit(main(sys.argv[1:]))
