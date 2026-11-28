#!/usr/bin/env python3
# ruff: noqa: E501  (each message carries the command that fixes it)
"""Keeps the release one path (docs/deploy/release.md). `make release-doctor` runs the static checks, which are in
`make checks`; `make release-doctor LIVE=1` adds the live ones, which read origin and GitHub (the release manager's tick).
Every failure is one line: what is wrong, then the one command that fixes it.

Static: no workflow, make target, script, guide, agent or skill file names a removed step of the old flows (the release
train, tagging develop, moving main by a push, keep-current) or a stale statement about what CI runs; the version file
equals both SDK versions; release.md lists exactly the release targets that exist and is at most 80 lines.
Live: at most one release or hotfix branch, with a version file that matches its name; every vX.Y.Z tag is reachable from main;
main's version file is that tag's, or the open release's; develop holds main; no merge-back pull request is unarmed; `release-gate` is a required check on main.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release

ROOT = Path(__file__).resolve().parents[1]
SELF = {"scripts/release_doctor.py", "scripts/tests/test_release.py"}
SKIP_DIRS = ("docs/plans/", "docs/usecases/", "changelog/", "node_modules/", "apps/docs/")
EXTS = (
    ".md",
    ".yml",
    ".yaml",
    ".mk",
    ".sh",
    ".py",
    ".mjs",
    ".json",
    ".ts",
    ".html",
    "Makefile",
    "pre-push",
    "pre-commit",
)

REMOVED = "the old release flows are gone; docs/deploy/release.md is the one path"
CI_STALE = "a stale statement about what CI runs; docs/architecture/delivery.md says what runs when"
BANNED: list[tuple[str, str]] = [
    (
        r"release/current|release-intake|release-cut|release-pr\b|release-main|release-version|hotfix-cut|release-tag"
        r"|merge-back\.yml",
        REMOVED,
    ),
    (r"keep-current|sync-prs", REMOVED),
    (r"holds? develop's tip|behind develop|stays? current with develop", CI_STALE),
    (r"\b(?:store-mssql|release-proof)\b[^\n|]{0,120}on every pull request", CI_STALE),
    (r"(?:make verify|ci-local FULL=1)[^\n|]{0,80}before (?:every|each) (?:commit|push)", CI_STALE),
    (r"before (?:every|each) (?:commit|push)[^\n|]{0,80}(?:make verify|ci-local FULL=1)", CI_STALE),
    (
        r"(?:BASE=|--base[ =]|since |merge-base )`?origin/main",
        "the base of a change is origin/develop (main holds only releases)",
    ),
]
RELEASE_DOC = "docs/deploy/release.md"
PACKAGE_TARGETS = {"release-package", "release-proof", "install-proof"}


def tracked() -> dict[str, str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    texts: dict[str, str] = {}
    for rel in out:
        if not rel or rel in SELF or rel.startswith(SKIP_DIRS) or not rel.endswith(EXTS):
            continue
        path = ROOT / rel
        if path.is_file():
            texts[rel] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def banned_hits(texts: dict[str, str]) -> list[str]:
    hits = []
    for rel, text in sorted(texts.items()):
        for n, line in enumerate(text.splitlines(), 1):
            for pattern, why in BANNED:
                m = re.search(pattern, line)
                if m:
                    hits.append(f"{rel}:{n} says '{m.group(0)}': {why}. Fix: reword it, or delete the line")
    return hits


def make_targets(texts: dict[str, str]) -> set[str]:
    return {
        m.group(1)
        for rel, t in texts.items()
        if rel.endswith((".mk", "Makefile"))
        for m in re.finditer(r"^([a-zA-Z][\w-]*):", t, re.M)
    }


def doc_problems(doc: str, targets: set[str], release_mk: str) -> list[str]:
    out = []
    mentioned = set(re.findall(r"make ([a-z][\w-]*)", doc))
    for t in sorted(mentioned - targets):
        out.append(f"{RELEASE_DOC} names `make {t}`, which does not exist. Fix: edit the page or add the target")
    owned = {m.group(1) for m in re.finditer(r"^([a-z][\w-]*):", release_mk, re.M)} - PACKAGE_TARGETS
    for t in sorted(owned - mentioned):
        out.append(f"{RELEASE_DOC} does not list `make {t}`. Fix: add it to the five steps")
    if doc.count("\n") + 1 > 80:
        out.append(f"{RELEASE_DOC} is over 80 lines. Fix: cut it to the five steps and the table")
    return out


def version_problems(version: str, ts: str, py: str, init: str | None, lock: str | None = None) -> list[str]:
    have = {"deploy/release/version": version, "sdk/typescript/package.json": ts, "sdk/python/pyproject.toml": py}
    if lock is not None:
        have["uv.lock"] = lock
    if init is not None:
        have["sdk/python/src/ops_ai/__init__.py"] = init
    if len(set(have.values())) == 1:
        return []
    shown = ", ".join(f"{k} {v}" for k, v in have.items())
    return [
        f"versions differ ({shown}). Fix: make release-start sets all of them; on develop, edit the odd ones to {version}"
    ]


def static_problems() -> list[str]:
    texts = tracked()
    problems = banned_hits(texts)

    def read(p: str) -> str:
        return (ROOT / p).read_text(encoding="utf-8")

    ts = json.loads(read("sdk/typescript/package.json"))["version"]
    py = re.search(r'^version = "([^"]*)"', read("sdk/python/pyproject.toml"), re.M)
    init = re.search(r'^__version__ = "([^"]*)"', read("sdk/python/src/ops_ai/__init__.py"), re.M)
    lock = re.search(r'^name = "ops-ai"\nversion = "([^"]*)"', read("uv.lock"), re.M)
    problems += version_problems(
        read("deploy/release/version").strip(),
        ts,
        py.group(1) if py else "?",
        init.group(1) if init else None,
        lock.group(1) if lock else "?",
    )
    problems += doc_problems(
        read(RELEASE_DOC), make_targets(texts) | make_targets({"Makefile": read("Makefile")}), read("make/release.mk")
    )
    return problems


def judge_live(state: dict) -> list[str]:
    """`state`: branches {name: version file text}, tags [names], off_main [vX.Y.Z tags that are not ancestors of main], main_version, develop_has_main bool, proofs {branch: (problem or None, push run id or None)}, merge_backs [{number, head, armed}]."""
    out = []
    branches = state["branches"]
    if len(branches) > 1:
        out.append(
            f"more than one release or hotfix branch ({', '.join(sorted(branches))}). Fix: git push origin --delete <the finished one>"
        )
    for name, have in branches.items():
        m = re.fullmatch(r"release/(\d+\.\d+\.\d+)", name)
        if m and have != m.group(1):
            out.append(
                f"{name}'s version file says {have}. Fix: git push the branch with the file set to {m.group(1)} (a pull request into it)"
            )
    released = sorted(
        (t[1:] for t in state["tags"] if re.fullmatch(r"v\d+\.\d+\.\d+", t) and t not in state["off_main"]),
        key=lambda v: tuple(map(int, v.split("."))),
    )
    for tag in state["off_main"]:
        out.append(
            f"{tag} is not reachable from main (only release-finish.yml tags, on main). "
            f"Fix: git push origin :refs/tags/{tag}"
        )
    if released:
        newest = released[-1]
        open_versions = {re.sub(r"^release/", "", b) for b in branches if b.startswith("release/")}
        main = state["main_version"]
        if main != newest and main not in open_versions:
            out.append(
                f"main's version file says {main} but the newest tag is v{newest} and no release/{main} is open. Fix: gh workflow run release-finish.yml -f branch=release/{main}"
            )
    if not state["develop_has_main"]:
        out.append(
            f"develop lacks commits of main (a merge-back is missing). Fix: gh workflow run release-finish.yml -f branch=release/{state['main_version']}"
        )
    for name, (why, run_id) in state["proofs"].items():
        if why:
            fix = f"gh run rerun {run_id} --failed" if run_id else f"git push origin {name}"
            out.append(f"{name}: release branch head has no green release-proof ({why}). Fix: {fix}")
    for pr in state["merge_backs"]:
        if not pr["armed"]:
            out.append(
                f"merge-back pull request #{pr['number']} ({pr['head']}) is not armed. Fix: gh pr merge --auto --merge {pr['number']}"
            )
    required = state.get("main_required", "not read")
    if required != "not read" and (required is None or "release-gate" not in required):
        out.append(
            "release-gate is not a required check on main (or its protection could not be read), so a release pull request "
            "can merge unproven. Fix: add `release-gate` to the required status checks of the main branch protection"
        )
    return out


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout


def proof_of(sha: str) -> tuple[str | None, str | None]:
    """The release-proof verdict of the push run of a commit: (why not, run id)."""
    runs = json.loads(
        sh("gh", "api", f"repos/{{owner}}/{{repo}}/actions/workflows/ci.yml/runs?event=push&head_sha={sha}&per_page=1")
    )["workflow_runs"]
    if not runs:
        return "no push run of that commit", None
    jobs = json.loads(sh("gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{runs[0]['id']}/jobs?per_page=100"))[
        "jobs"
    ]
    return release.proof_problem(jobs), str(runs[0]["id"])


def live_state() -> dict:
    sh("git", "fetch", "--quiet", "--tags", "origin", "main", "develop")
    listing = sh("git", "ls-remote", "--heads", "origin", "refs/heads/release/[0-9]*", "refs/heads/hotfix/*")
    branches = {}
    for line in listing.splitlines():
        name = line.split("refs/heads/", 1)[1]
        sh("git", "fetch", "--quiet", "--no-tags", "origin", name)
        branches[name] = sh("git", "show", f"origin/{name}:deploy/release/version").strip()
    tags = sh("git", "tag", "--list", "v[0-9]*").split()
    released = sorted(
        (t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)), key=lambda t: tuple(map(int, t[1:].split(".")))
    )

    def ancestor(a: str, b: str) -> bool:
        return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=ROOT, check=False).returncode == 0

    prs = json.loads(
        sh("gh", "pr", "list", "--base", "develop", "--state", "open", "--json", "number,headRefName,autoMergeRequest")
    )
    try:
        required = json.loads(
            sh(
                "gh",
                "api",
                "repos/{owner}/{repo}/branches/main/protection/required_status_checks",
                "--jq",
                "[.contexts[], .checks[].context]",
            )
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        required = None
    return {
        "main_required": required,
        "branches": branches,
        "proofs": {b: proof_of(sh("git", "rev-parse", f"origin/{b}").strip()) for b in branches},
        "tags": tags,
        "off_main": [t for t in released if not ancestor(t, "origin/main")],
        "main_version": sh("git", "show", "origin/main:deploy/release/version").strip(),
        "develop_has_main": ancestor("origin/main", "origin/develop"),
        "merge_backs": [
            {"number": p["number"], "head": p["headRefName"], "armed": p["autoMergeRequest"] is not None}
            for p in prs
            if p["headRefName"].startswith("merge-back/")
        ],
    }


def main(argv: list[str]) -> int:
    problems = static_problems()
    if "--live" in argv:
        problems += judge_live(live_state())
    for p in problems:
        print(f"release-doctor: {p}")
    print("release-doctor: " + (f"{len(problems)} problem(s)" if problems else "ok"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
