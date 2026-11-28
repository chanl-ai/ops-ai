"""`make release-start`, `hotfix-start`, `release-rc` and the finish step (scripts/release.py) on a scratch repository
with a fake `gh`, and the release doctor (scripts/release_doctor.py) on planted input.

Failure modes: a release starts while another branch exists, on a tag that exists or a red develop tip; the start
commit leaves out a version field or is cut from the wrong base; a hotfix is cut from develop instead of the tag; a
candidate is tagged before its staging deploy passed; a merged branch is tagged with a version its name disagrees with;
the doctor misses a stale mention, a version that differs, a missing tag, a missing merge-back or an unarmed one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SCRIPT = SCRIPTS / "release.py"
sys.path.insert(0, str(SCRIPTS))
import release  # noqa: E402
import release_doctor  # noqa: E402

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
state = json.loads(os.environ["FAKE_GH"])
if args[:2] == ["run", "list"]:
    workflow = args[args.index("--workflow") + 1]
    if workflow not in state["runs"]:
        sys.exit(f"HTTP 404: Not Found (https://api.github.com/repos/o/r/actions/workflows/{workflow})")
    print(json.dumps(state["runs"][workflow]))
elif args[:1] == ["api"] and args[1].endswith("/logs"):
    print(state["log"])
elif args[:2] == ["run", "view"]:
    print(json.dumps({"jobs": state["jobs"][args[2]]}))
elif args[:2] == ["pr", "list"]:
    print(json.dumps([]))
elif args[:2] == ["pr", "create"]:
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write("gh " + json.dumps(args) + chr(10))
    print("https://github.com/o/r/pull/1")
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
"""

FAKE_MAKE = """#!/bin/sh
echo "make $*" >> "$FAKE_LOG"
exit "${FAKE_MAKE_RC:-0}"
"""

IDENT = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **IDENT}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def release_repo(tmp: Path) -> Path:
    """origin with main at 1.0.0 tagged v1.0.0, and develop one commit ahead of it; the checkout is on develop."""
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    for path, text in {
        "sdk/python/pyproject.toml": '[project]\nname = "ops-ai"\nversion = "1.0.0"\n',
        "sdk/python/src/ops_ai/__init__.py": '__version__ = "1.0.0"\n',
        "sdk/typescript/package.json": '{\n  "name": "@chanl-ai/ops-ai",\n  "version": "1.0.0"\n}\n',
        "deploy/release/version": "1.0.0\n",
    }.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text)
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "origin", "HEAD:main", "HEAD:develop")
    git(work, "tag", "v1.0.0")
    git(work, "push", "-q", "origin", "v1.0.0")
    (work / "feature").write_text("x")
    git(work, "add", "feature")
    git(work, "commit", "-q", "-m", "feat: a feature")
    git(work, "push", "-q", "origin", "HEAD:develop")
    git(work, "fetch", "-q", "origin")
    return work


GREEN: dict[str, Any] = {"runs": {"ci.yml": [{"databaseId": 1, "conclusion": "success", "status": "completed"}]}}
STAGING_JOB = {"name": "staging / deploy", "conclusion": "success", "databaseId": 11}
DEPLOYED: dict[str, Any] = {**GREEN, "jobs": {"1": [STAGING_JOB]}, "log": "stg-deploy: click walk (41 OK, 0 FAIL)"}


def release_cmd(
    work: Path, tmp: Path, gh_state: dict[str, Any] | None = None, command: str = "start", **env_changes: str
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    env = {**os.environ, **IDENT, "PATH": f"{bin_dir}:{os.environ['PATH']}", "V": "1.1.0"}
    env |= {"FAKE_GH": json.dumps(gh_state if gh_state is not None else GREEN), "FAKE_LOG": str(tmp / "calls.log")}
    env.update(env_changes)
    return subprocess.run(
        [sys.executable, str(SCRIPT), command], cwd=work, capture_output=True, text=True, env=env, check=False
    )


def calls(tmp: Path) -> str:
    log = tmp / "calls.log"
    return log.read_text() if log.exists() else ""


def branches(work: Path) -> str:
    return git(work, "ls-remote", "--heads", "origin")


def test_start_pushes_one_version_commit_from_develop_and_opens_the_pull_request_into_main(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    preview = release_cmd(work, tmp_path)
    assert preview.returncode == 0 and "release/1.1.0" not in branches(work), preview.stderr
    done = release_cmd(work, tmp_path, DRY="0")
    assert done.returncode == 0, done.stderr
    git(work, "fetch", "-q", "origin")
    assert git(work, "rev-parse", "origin/release/1.1.0^") == git(work, "rev-parse", "origin/develop")
    for path in ("deploy/release/version", "sdk/python/src/ops_ai/__init__.py"):
        assert "1.1.0" in git(work, "show", f"origin/release/1.1.0:{path}")
    assert '"version": "1.1.0"' in git(work, "show", "origin/release/1.1.0:sdk/typescript/package.json")
    assert 'version = "1.1.0"' in git(work, "show", "origin/release/1.1.0:sdk/python/pyproject.toml")
    pr = calls(tmp_path)
    assert '"--base", "main"' in pr and '"--title", "release: 1.1.0"' in pr


@pytest.mark.parametrize(
    ("setup", "state", "named"),
    [
        ("branch", None, "release/1.0.5 exists"),
        ("tag", None, "v1.1.0 exists"),
        ("older", None, "not above the newest release"),
        ("", {"runs": {"ci.yml": [{"databaseId": 1, "conclusion": "failure", "status": "completed"}]}}, "failure"),
    ],
)
def test_start_refuses_another_branch_a_used_or_lower_version_and_a_red_develop(
    tmp_path: Path, setup: str, state: dict[str, Any] | None, named: str
) -> None:
    work = release_repo(tmp_path)
    if setup == "branch":
        git(work, "push", "-q", "origin", "HEAD:refs/heads/release/1.0.5")
    if setup == "tag":
        git(work, "tag", "v1.1.0")
        git(work, "push", "-q", "origin", "v1.1.0")
    env = {"V": "0.9.0"} if setup == "older" else {}
    run = release_cmd(work, tmp_path, state, DRY="0", **env)
    assert run.returncode == 1 and named in run.stderr, run.stderr
    assert "release/1.1.0" not in branches(work) and "pr" not in calls(tmp_path)


def test_a_hotfix_is_cut_from_the_newest_tag_not_develop_and_needs_a_name(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    assert release_cmd(work, tmp_path, command="hotfix-start", V="1.0.1", DRY="0").returncode == 1
    run = release_cmd(work, tmp_path, command="hotfix-start", V="1.0.1", NAME="login-loop", DRY="0")
    assert run.returncode == 0, run.stderr
    git(work, "fetch", "-q", "origin")
    assert git(work, "rev-parse", "origin/hotfix/login-loop^") == git(work, "rev-parse", "v1.0.0^{commit}")
    assert git(work, "show", "origin/hotfix/login-loop:deploy/release/version") == "1.0.1\n"
    assert '"--title", "hotfix: 1.0.1"' in calls(tmp_path)


def test_a_candidate_is_tagged_only_after_its_staging_deploy_and_walk_passed(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    assert release_cmd(work, tmp_path, DRY="0").returncode == 0
    unseen = release_cmd(work, tmp_path, {**GREEN, "jobs": {"1": []}}, command="rc", DRY="0")
    assert unseen.returncode == 1 and "no staging deploy" in unseen.stderr
    assert "-rc" not in git(work, "ls-remote", "--tags", "origin")
    for n in (1, 2):
        done = release_cmd(work, tmp_path, DEPLOYED, command="rc", DRY="0")
        assert done.returncode == 0, done.stderr
        assert f"v1.1.0-rc.{n}" in git(work, "ls-remote", "--tags", "origin")


def test_a_merged_branch_is_tagged_only_with_the_version_its_name_says() -> None:
    assert release.finish_tag("release/1.2.1", "1.2.1", ["v1.2.0"]) == "v1.2.1"
    assert release.finish_tag("hotfix/login-loop", "1.2.2", ["v1.2.1"]) == "v1.2.2"
    for branch, have, tags in (
        ("release/1.2.1", "1.2.0", []),
        ("release/1.2.1", "1.2.1", ["v1.2.1"]),
        ("feature/x", "1.2.1", []),
    ):
        with pytest.raises(release.Refusal):
            release.finish_tag(branch, have, tags)


def test_the_doctor_finds_a_stale_mention_a_differing_version_and_a_page_that_names_a_missing_target() -> None:
    texts = {
        "docs/a.md": "Open release/current and run release-intake.\nPlain line.",
        "make/x.mk": "Run `make verify` before every commit.",
        ".github/workflows/y.yml": "# BASE=origin/main",
    }
    assert [h.split(" says ")[0] for h in release_doctor.banned_hits(texts)] == [
        ".github/workflows/y.yml:1",
        "docs/a.md:1",
        "make/x.mk:1",
    ]
    assert release_doctor.version_problems("1.2.1", "1.0.0", "1.2.1", "1.2.1")
    assert not release_doctor.version_problems("1.2.1", "1.2.1", "1.2.1", None)
    mk = "release-start: x\nrelease-rc: y\nrelease-package: z\n"
    assert release_doctor.doc_problems("make release-start and make release-gone", {"release-start"}, mk) == [
        "docs/deploy/release.md names `make release-gone`, which does not exist. Fix: edit the page or add the target",
        "docs/deploy/release.md does not list `make release-rc`. Fix: add it to the five steps",
    ]


def test_the_live_doctor_names_the_missing_tag_merge_back_and_arming_with_the_command_that_fixes_each() -> None:
    state: dict[str, Any] = {
        "branches": {"release/1.2.2": "1.2.2", "hotfix/x": "1.2.1"},
        "tags": ["v1.2.0", "v1.2.1-rc.1"],
        "off_main": ["v1.2.2"],
        "main_version": "1.2.1",
        "develop_has_main": False,
        "merge_backs": [{"number": 7, "head": "merge-back/release-1.2.1", "armed": False}],
    }
    out = release_doctor.judge_live(state)
    assert [line.split(" ")[0] for line in out] == ["more", "v1.2.2", "main's", "develop", "merge-back"], out
    assert "git push origin :refs/tags/v1.2.2" in out[1]
    assert "gh workflow run release-finish.yml -f branch=release/1.2.1" in out[2]
    assert "gh pr merge --auto --merge 7" in out[4]
    assert (
        release_doctor.judge_live(
            {**state, "branches": {}, "tags": ["v1.2.1"], "off_main": [], "develop_has_main": True, "merge_backs": []}
        )
        == []
    )
