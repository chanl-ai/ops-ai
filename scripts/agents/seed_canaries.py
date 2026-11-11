"""Plant known bugs on a throwaway branch and score what a finder reports against them: the recall measure of the
finder scorecard.

`plant` makes a worktree on a new branch from HEAD, applies five to eight canaries from the catalogue below (each a
small, realistic fault: a role gate missing in the console, a wrong plural, text that clips at phone width, a raw id
shown to a person, a swallowed error, a broken empty state, a write route with no guard, a test that cannot fail),
commits them as ordinary-looking changes, and writes the answer key outside the worktree, in a folder the finder is
never pointed at. `score` reads a finder's report and the key, and prints caught, missed and false findings with
recall and precision. A finding counts as caught when it names the canary's file and a line within three of the
planted one, or the canary's own words.

  python3 scripts/agents/seed_canaries.py plant [--count 6] [--seed 7] [--branch canary/<hex>] [--key-dir DIR]
  python3 scripts/agents/seed_canaries.py score --report findings.md --key DIR/<branch>.json
  python3 scripts/agents/seed_canaries.py list                  the catalogue, and which entries fit this checkout
  python3 scripts/agents/seed_canaries.py remove --branch NAME  drop the worktree and the branch
  python3 scripts/agents/seed_canaries.py --self-test           the catalogue on a fixture tree, planted and scored

The catalogue is generic: each entry names what to look for by pattern, and the profile's "Layers" and "Console"
tables say which folders are the console, the services and the tests, so another repository plants the same kinds
of bug in its own files. An entry that finds no place to land is skipped and said so.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_profile import Profile, load


@dataclass
class Canary:
    """One bug kind: where it can land (a layer and a regex over file text), and how the text changes."""

    id: str
    title: str
    layer: str
    file_glob: str
    find: str  # regex over the file; the first match on a line is the planting site
    replace: str  # replacement (regex groups allowed)
    risk: str  # low | security-data-permissions-api | needs-a-decision
    words: str  # what a correct finding says, for scoring by words


CATALOGUE: list[Canary] = [
    Canary(
        "missing-role-gate",
        "A console control shown to every role: the `can()` or role check around it is removed",
        "console",
        "apps/console/src/**/*.tsx",
        r"\{can\(([^)]*)\) && ",
        "{true && ",
        "low",
        "role gate removed; shown to every role; server still refuses",
    ),
    Canary(
        "wrong-plural",
        "A count reads `1 items`: the plural helper is replaced by a fixed plural",
        "console",
        "apps/console/src/**/*.tsx",
        r"plural\(([^,()]+),\s*(['\"][a-z]+['\"])(?:,\s*['\"][a-z]+['\"])?\)",
        r"`${\1} \2s`",
        "low",
        "wrong plural; 1 items; plural()",
    ),
    Canary(
        "clipped-at-390",
        "A fixed width that clips at phone width: a responsive class becomes a fixed pixel width",
        "console",
        "apps/console/src/**/*.tsx",
        r'className="([^"]*\b)max-w-(?:md|lg|xl|2xl|3xl)\b',
        r'className="\1w-[880px]',
        "low",
        "clipped at 390; fixed width; overflow",
    ),
    Canary(
        "raw-id-shown",
        "A person sees a record id where its name belongs",
        "console",
        "apps/console/src/**/*.tsx",
        r"\{(\w+)\.name\}",
        r"{\1.id}",
        "low",
        "raw id shown; .id instead of .name",
    ),
    Canary(
        "swallowed-error",
        "A failed request is caught and dropped, so the screen shows nothing",
        "console",
        "apps/console/src/**/*.ts*",
        r"\} catch \((\w+)\) \{\n(\s*)(throw \1;|throw new \w+Error\([^\n]*\);)",
        r"} catch (\1) {\n\2return undefined as never;",
        "security-data-permissions-api",
        "swallowed error; catch returns nothing; error state never shown",
    ),
    Canary(
        "broken-empty-state",
        "The empty state is never reached: the list is read as non-empty when it has no rows",
        "console",
        "apps/console/src/**/*.tsx",
        r"\.length === 0\b",
        ".length < 0",
        "low",
        "empty state never shows; length < 0",
    ),
    Canary(
        "unguarded-write",
        "A write route no longer checks what the caller may do",
        "service",
        "services/*/src/**/*.py",
        r"\n(\s+)(who|principal|caller|current)\.require_\w+\([^\n]*\)\n",
        r"\n\1pass  # access decided by the caller\n",
        "security-data-permissions-api",
        "unguarded write; require_ removed; any member can write",
    ),
    Canary(
        "test-cannot-fail",
        "A test's assertion is replaced by a tautology, so it passes whatever the code does",
        "tests-python",
        "services/*/tests/test_*.py",
        r"\n(\s+)assert (resp|response|r|res)\.status_code == (40[0-9]|403|401)\b",
        r"\n\1assert \3 == \3",
        "low",
        "test cannot fail; tautology; status_code assertion removed",
    ),
    Canary(
        "team-scope-dropped",
        "A query loses its team filter, so another team's rows come back",
        "service",
        "services/*/src/**/*.py",
        r"\.where\(([\w.]+)\.team_id == ([\w.]+)\)",
        r".where(\1.team_id == \1.team_id)",
        "security-data-permissions-api",
        "team scope dropped; other team's rows; team_id filter",
    ),
]


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check).stdout


def matches(path: str, pattern: str) -> bool:
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def line_at(text: str, m: re.Match[str]) -> int:
    """The line a match changes: the one after a leading newline in the pattern, else the one it starts on."""
    return text[: m.start()].count("\n") + 1 + m.group(0).startswith("\n")


def sites(root: Path, canary: Canary, files: list[str]) -> list[tuple[str, int]]:
    """Every (file, line) where the canary could be planted."""
    out: list[tuple[str, int]] = []
    regex = re.compile(canary.find)
    for rel in files:
        if not matches(rel, canary.file_glob):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in regex.finditer(text):
            out.append((rel, line_at(text, m)))
    return out


def plant_one(root: Path, canary: Canary, rel: str, line: int) -> int:
    """Applies the canary's first match at or after `line` and returns the line the change starts on."""
    path = root / rel
    text = path.read_text(encoding="utf-8")
    regex = re.compile(canary.find)
    for m in regex.finditer(text):
        at = line_at(text, m)
        if at >= line:
            new = text[: m.start()] + m.expand(canary.replace) + text[m.end() :]
            path.write_text(new, encoding="utf-8")
            return at
    raise ValueError(f"{canary.id}: no site left in {rel} at or after line {line}")


def plant(profile: Profile, count: int, seed: int | None, branch: str | None, key_dir: Path) -> dict[str, object]:
    root = profile.root
    rng = random.Random(seed)
    branch = branch or f"canary/{secrets.token_hex(3)}"
    worktree = Path(tempfile.mkdtemp(prefix="ops-canary-")) / "tree"
    git(root, "worktree", "add", "-q", "-b", branch, str(worktree), "HEAD")
    files = [f for f in git(worktree, "ls-files").splitlines() if f]
    planted: list[dict[str, object]] = []
    skipped: list[str] = []
    order = list(CATALOGUE)
    rng.shuffle(order)
    for canary in order:
        if len(planted) >= count:
            break
        where = sites(worktree, canary, files)
        if not where:
            skipped.append(canary.id)
            continue
        rel, line = rng.choice(where)
        try:
            at = plant_one(worktree, canary, rel, line)
        except ValueError as e:
            skipped.append(f"{canary.id} ({e})")
            continue
        planted.append(
            {
                "id": canary.id,
                "file": rel,
                "line": at,
                "risk": canary.risk,
                "words": canary.words,
                "title": canary.title,
            }
        )
    if len(planted) < min(count, 5):
        git(root, "worktree", "remove", "--force", str(worktree))
        git(root, "branch", "-D", branch)
        sys.exit(
            f"only {len(planted)} canaries could land here (skipped: {', '.join(skipped)}); "
            "the catalogue needs entries for this tree"
        )
    # One ordinary-looking commit per file, so the diff reads like a day's work and not like a list of bugs.
    for rel in sorted({p["file"] for p in planted}):  # type: ignore[misc]
        git(worktree, "add", rel)
        author = ["-c", "user.name=canary", "-c", "user.email=canary@example.test"]
        # The planted commit skips the hooks on purpose: the branch is a throwaway and must look like ordinary work.
        subprocess.run(
            ["git", *author, "commit", "-q", "--no-verify", "-m", f"chore: tidy {Path(rel).stem}"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
    key_dir.mkdir(parents=True, exist_ok=True)
    key = key_dir / f"{branch.replace('/', '-')}.json"
    record = {"branch": branch, "worktree": str(worktree), "canaries": planted, "skipped": skipped}
    key.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"branch": branch, "worktree": str(worktree), "planted": len(planted), "skipped": skipped, "key": str(key)}


FILE_LINE = re.compile(r"([\w./-]+\.(?:py|tsx|ts|mjs|js))(?::(\d+))?")


def score(report_text: str, key: dict[str, object], tolerance: int = 3) -> dict[str, object]:
    """Caught, missed and false findings. A finding is one line of the report naming a file (and maybe a line); it
    is matched to the one planted canary in that file nearest its line (within `tolerance`), or to the one whose
    words it says when it names no line; each finding and each canary count once."""
    canaries: list[dict[str, object]] = key["canaries"]  # type: ignore[assignment]
    findings = [ln.strip() for ln in report_text.splitlines() if FILE_LINE.search(ln) and ln.strip()]
    caught: list[dict[str, object]] = []
    taken: set[int] = set()
    false: list[str] = []
    for finding in findings:
        low = finding.lower()
        best: tuple[int, int, int] | None = None  # (said words? 0 first, distance, canary index)
        for m in FILE_LINE.finditer(finding):
            for j, canary in enumerate(canaries):
                if j in taken:
                    continue
                file = str(canary["file"])
                if not (file.endswith(m.group(1)) or m.group(1).endswith(file)):
                    continue
                said = any(w.strip().lower() in low for w in str(canary["words"]).split(";"))
                if m.group(2) is None:
                    if not said:
                        continue
                    distance = tolerance
                else:
                    distance = abs(int(m.group(2)) - int(canary["line"]))  # type: ignore[arg-type]
                    if distance > tolerance:
                        continue
                candidate = (0 if said else 1, distance, j)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            false.append(finding[:160])
        else:
            taken.add(best[2])
            caught.append({**canaries[best[2]], "finding": finding[:160]})
    missed = [c for j, c in enumerate(canaries) if j not in taken]
    total = len(canaries)
    return {
        "caught": caught,
        "missed": missed,
        "false": false,
        "recall": round(100 * len(caught) / total) if total else None,
        "precision": round(100 * len(caught) / (len(caught) + len(false))) if caught or false else None,
    }


def markdown(s: dict[str, object]) -> str:
    caught: list[dict[str, object]] = s["caught"]  # type: ignore[assignment]
    missed: list[dict[str, object]] = s["missed"]  # type: ignore[assignment]
    false: list[str] = s["false"]  # type: ignore[assignment]
    lines = [f"# Finder score: recall {s['recall']}%, precision {s['precision']}%", "", "## Caught"]
    lines += [f"- {c['id']} at {c['file']}:{c['line']} ({c['risk']}): {c['finding']}" for c in caught] or ["- none"]
    lines += ["", "## Missed"]
    lines += [f"- {c['id']} at {c['file']}:{c['line']} ({c['risk']}): {c['title']}" for c in missed] or ["- none"]
    lines += ["", "## False (reported, not planted; judge each by hand)"]
    lines += [f"- {f}" for f in false] or ["- none"]
    return "\n".join(lines) + "\n"


def self_test() -> bool:
    """Plants the catalogue on a fixture tree and scores a report that catches some, misses one and adds a false one."""
    tmp = Path(tempfile.mkdtemp(prefix="ops-canary-selftest-"))
    try:
        (tmp / "apps/console/src/x").mkdir(parents=True)
        (tmp / "services/s/src/m").mkdir(parents=True)
        (tmp / "services/s/tests").mkdir(parents=True)
        (tmp / "apps/console/src/x/page.tsx").write_text(
            'export function Page({ team, rows }) {\n  return (<div className="mx-auto max-w-lg">\n'
            "    {can('write') && <button>Edit</button>}\n    <h1>{team.name}</h1>\n"
            "    <p>{plural(rows.length, 'item')}</p>\n    {rows.length === 0 && <Empty />}\n  </div>);\n}\n"
        )
        (tmp / "apps/console/src/x/load.ts").write_text(
            "export async function load(id: string) {\n  try {\n    return await api.get(id);\n"
            "  } catch (e) {\n    throw e;\n  }\n}\n"
        )
        (tmp / "services/s/src/m/routes.py").write_text(
            "async def delete_thing(who, store, thing_id):\n    who.require_builder()\n"
            "    rows = select(Thing).where(Thing.team_id == who.team_id)\n    return rows\n"
        )
        (tmp / "services/s/tests/test_routes.py").write_text(
            "def test_member_is_refused(client):\n    resp = client.delete('/v1/things/1')\n"
            "    assert resp.status_code == 403\n"
        )
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp, check=True)
        author = ["-c", "user.name=t", "-c", "user.email=t@example.test"]
        subprocess.run(["git", *author, "add", "."], cwd=tmp, check=True)
        subprocess.run(["git", *author, "commit", "-q", "-m", "fixture"], cwd=tmp, check=True)
        from project_profile import parse  # noqa: PLC0415

        profile = parse("# p\n", tmp / "p.md", tmp)
        result = plant(profile, count=len(CATALOGUE), seed=1, branch="canary/selftest", key_dir=tmp / "keys")
        key = json.loads(Path(str(result["key"])).read_text())
        ids = {c["id"] for c in key["canaries"]}
        diff = git(tmp, "diff", "HEAD", "canary/selftest")
        by_id = {c["id"]: c for c in key["canaries"]}
        report = "\n".join(
            [
                f"- apps/console/src/x/page.tsx:{by_id['wrong-plural']['line']} shows '1 items': wrong plural",
                f"- services/s/src/m/routes.py:{by_id['unguarded-write']['line']} delete has no require_ check",
                "- services/s/src/m/routes.py:40 a line nobody planted",
            ]
        )
        s = score(report, key)
        caught_ids = {c["id"] for c in s["caught"]}
        git(tmp, "worktree", "remove", "--force", key["worktree"])
        cases = [
            ("every catalogue entry lands on the fixture", ids == {c.id for c in CATALOGUE}, sorted(ids)),
            ("the key is written outside the worktree", not str(result["key"]).startswith(key["worktree"])),
            ("the branch holds the planted changes as commits", "require_builder" in diff and "1 files" not in diff),
            (
                "the branch moved past the fixture's commit",
                git(tmp, "rev-parse", "canary/selftest") != git(tmp, "rev-parse", "main"),
            ),
            ("a finding with the file and a near line is caught", caught_ids == {"wrong-plural", "unguarded-write"}),
            ("the rest are missed", len(s["missed"]) == len(key["canaries"]) - 2),
            (
                "a finding nobody planted is false",
                s["false"] == ["- services/s/src/m/routes.py:40 a line nobody planted"],
            ),
            ("recall and precision follow", s["recall"] == round(200 / len(key["canaries"])) and s["precision"] == 67),
        ]
        git(tmp, "branch", "-D", "canary/selftest")
    finally:
        subprocess.run(["rm", "-rf", str(tmp)], check=False)
    for case in cases:
        ok = case[1]
        print(f"{'PASS' if ok else 'FAIL'} {case[0]}{'' if ok or len(case) < 3 else f': {case[2]}'}")
    return all(c[1] for c in cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=["plant", "score", "list", "remove"])
    parser.add_argument("--count", type=int, default=6, help="canaries to plant, five to eight")
    parser.add_argument("--seed", type=int, help="pick the same sites again")
    parser.add_argument("--branch", help="the canary branch (default canary/<hex>)")
    parser.add_argument("--key-dir", help="where the answer key goes (default: .logs/agents/canary-keys)")
    parser.add_argument("--report", help="score: the finder's report file")
    parser.add_argument("--key", help="score: the answer key file")
    parser.add_argument("--profile")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1
    profile = load(args.profile)
    if args.command == "list":
        files = [f for f in git(profile.root, "ls-files").splitlines() if f]
        for c in CATALOGUE:
            print(f"{c.id:22} {c.risk:32} sites here: {len(sites(profile.root, c, files)):4}  {c.title}")
        return 0
    if args.command == "plant":
        if not 5 <= args.count <= 8:
            sys.exit("--count is five to eight")
        key_dir = Path(args.key_dir) if args.key_dir else profile.root / ".logs" / "agents" / "canary-keys"
        r = plant(profile, args.count, args.seed, args.branch, key_dir)
        print(f"branch {r['branch']} in {r['worktree']}: {r['planted']} canaries planted")
        print(f"answer key {r['key']}: keep it from the finder")
        if r["skipped"]:
            print(f"skipped: {', '.join(r['skipped'])}")  # type: ignore[arg-type]
        return 0
    if args.command == "score":
        if not (args.report and args.key):
            sys.exit("score needs --report and --key")
        s = score(Path(args.report).read_text(encoding="utf-8"), json.loads(Path(args.key).read_text(encoding="utf-8")))
        print(markdown(s))
        return 0
    if args.command == "remove":
        if not args.branch:
            sys.exit("remove needs --branch")
        for line in git(profile.root, "worktree", "list", "--porcelain").split("\n\n"):
            if f"branch refs/heads/{args.branch}" in line:
                path = line.split("\n")[0].split(" ", 1)[1]
                git(profile.root, "worktree", "remove", "--force", path)
        git(profile.root, "branch", "-D", args.branch)
        print(f"removed {args.branch}")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
