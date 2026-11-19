"""`make release-pr` (scripts/release.py pr) driven through its command line on a scratch repository with a fake `gh`.

Failure modes: a release PR opens on a branch head whose CI or staging deploy with its click walk did not succeed; the
body leaves out the merged pull requests or the SDK version, so the reviewer cannot see what ships; a release branch
ships with a deploy/release/version other than its name, so installs and the release proof ask for the wrong images;
a cut leaves the version file as develop had it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "release.py"

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
state = json.loads(os.environ["FAKE_GH"])
if args[:2] == ["run", "list"]:
    print(json.dumps(state["runs"][args[args.index("--workflow") + 1]]))
elif args[:2] == ["run", "view"] and "--job" in args:
    print(state["log"])
elif args[:2] == ["run", "view"]:
    print(json.dumps({"jobs": state["jobs"][args[2]]}))
elif args[:2] == ["pr", "list"]:
    print(json.dumps([]))
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
"""


def git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def release_repo(tmp: Path) -> Path:
    """origin with main, and develop holding one merged pull request that raised the SDK version."""
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    (work / "sdk/python").mkdir(parents=True)
    (work / "sdk/typescript").mkdir(parents=True)
    (work / "sdk/python/pyproject.toml").write_text('[project]\nname = "ops-ai"\nversion = "1.0.0"\n')
    (work / "sdk/typescript/package.json").write_text('{"name": "@chanl-ai/ops-ai", "version": "1.0.0"}\n')
    (work / "deploy/release").mkdir(parents=True)
    (work / "deploy/release/version").write_text("1.1.0\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "origin", "HEAD:main")
    git(work, "checkout", "-q", "-b", "feature")
    (work / "sdk/python/pyproject.toml").write_text('[project]\nname = "ops-ai"\nversion = "1.1.0"\n')
    (work / "sdk/typescript/package.json").write_text('{"name": "@chanl-ai/ops-ai", "version": "1.1.0"}\n')
    git(work, "commit", "-q", "-am", "feat(sdk): add runs.cancel")
    git(work, "checkout", "-q", "-b", "develop", "main")
    git(
        work,
        "merge",
        "-q",
        "--no-ff",
        "feature",
        "-m",
        "Merge pull request #12 from chanl-ai/feat/sdk-runs-cancel",
        "-m",
        "feat(sdk): add runs.cancel",
    )
    git(work, "push", "-q", "origin", "develop")
    git(work, "push", "-q", "origin", "develop:release/1.1.0")
    return work


def release_pr(
    work: Path, tmp: Path, gh_state: dict, command: str = "pr", **env_changes: str
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "V": "1.1.0",
        "FAKE_GH": json.dumps(gh_state),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    env.update(env_changes)
    return subprocess.run(
        [sys.executable, str(SCRIPT), command], cwd=work, capture_output=True, text=True, env=env, check=False
    )


STAGING_JOB = {"name": "staging / deploy", "conclusion": "success", "databaseId": 11}
READY = {
    "runs": {"ci.yml": [{"databaseId": 1, "conclusion": "success", "status": "completed"}], "deploy-staging.yml": []},
    "jobs": {"1": [STAGING_JOB]},
    "log": "stg-deploy: click walk (41 OK, 0 FAIL)",
}


def ready(**changes: object) -> dict:
    return {**READY, **changes}


@pytest.mark.parametrize(
    ("state", "named"),
    [
        (
            ready(
                runs={**READY["runs"], "ci.yml": [{"databaseId": 1, "conclusion": "failure", "status": "completed"}]}
            ),
            "ci.yml",
        ),
        (ready(jobs={"1": []}), "no staging deploy"),
        (ready(jobs={"1": [{**STAGING_JOB, "conclusion": "failure"}]}), "failure"),
        (ready(log="stg-deploy: click walk skipped (SKIP_WALK=1)"), "click walk"),
        (ready(log="stg-deploy: click walk (40 OK, 1 FAIL)"), "1 FAIL"),
    ],
)
def test_it_refuses_unless_ci_and_the_staging_deploy_with_its_walk_succeeded(
    tmp_path: Path, state: dict, named: str
) -> None:
    run = release_pr(release_repo(tmp_path), tmp_path, state)
    assert run.returncode == 1
    assert named in run.stderr
    assert "release: 1.1.0" not in run.stdout


def test_it_prints_the_title_and_body_when_ready(tmp_path: Path) -> None:
    run = release_pr(release_repo(tmp_path), tmp_path, READY)
    assert run.returncode == 0, run.stderr
    assert "release: 1.1.0 (develop → main)" in run.stdout
    assert "#12 feat(sdk): add runs.cancel" in run.stdout
    assert "sdk/**: changed" in run.stdout
    assert "python ops-ai 1.0.0 -> 1.1.0" in run.stdout
    assert "typescript @chanl-ai/ops-ai 1.0.0 -> 1.1.0" in run.stdout
    assert "merge commit" in run.stdout


def test_it_refuses_a_release_branch_whose_version_file_is_not_its_version(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    (work / "deploy/release/version").write_text("0.1.0\n")
    git(work, "commit", "-q", "-am", "chore: old version")
    git(work, "push", "-q", "-f", "origin", "HEAD:release/1.1.0")
    pr = release_pr(work, tmp_path, READY)
    assert pr.returncode == 1
    assert "says 0.1.0, not 1.1.0" in pr.stderr
    check = release_pr(work, tmp_path, READY, "check-version", BRANCH="release/1.1.0")
    assert check.returncode == 1
    assert "says 0.1.0, not 1.1.0" in check.stderr
    assert release_pr(work, tmp_path, READY, "check-version", BRANCH="release/0.1.0").returncode == 0


def test_the_cut_sets_the_version_file_in_one_commit_on_develop(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    run = release_pr(work, tmp_path, READY, "cut", V="1.2.0", DRY="0")
    assert run.returncode == 0, run.stderr
    git(work, "fetch", "-q", "origin", "release/1.2.0")
    assert git(work, "show", "origin/release/1.2.0:deploy/release/version") == "1.2.0\n"
    assert git(work, "rev-parse", "origin/release/1.2.0^").strip() == git(work, "rev-parse", "origin/develop").strip()
