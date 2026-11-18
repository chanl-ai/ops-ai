"""`make release-pr` (scripts/release.py pr) driven through its command line on a scratch repository with a fake `gh`.

Failure modes: a release PR opens on a branch head whose CI or staging deploy with its click walk did not succeed; the
body leaves out the merged pull requests or the SDK version, so the reviewer cannot see what ships."""

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
    workflow = args[args.index("--workflow") + 1]
    print(json.dumps(state["ci"] if workflow == "ci.yml" else state["staging"]))
elif args[:2] == ["run", "view"]:
    print(state["log"])
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


def release_pr(work: Path, tmp: Path, gh_state: dict) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "V": "1.1.0", "FAKE_GH": json.dumps(gh_state)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "pr"], cwd=work, capture_output=True, text=True, env=env, check=False
    )


READY = {
    "ci": [{"databaseId": 1, "conclusion": "success", "status": "completed"}],
    "staging": [{"databaseId": 2, "conclusion": "success", "status": "completed", "event": "workflow_dispatch"}],
    "log": "stg-deploy: click walk (41 OK, 0 FAIL)",
}
RED_CI = {"databaseId": 1, "conclusion": "failure", "status": "completed"}


@pytest.mark.parametrize(
    ("state", "named"),
    [
        ({**READY, "ci": [RED_CI]}, "ci.yml"),
        ({**READY, "staging": []}, "deploy-staging.yml"),
        ({**READY, "log": "stg-deploy: click walk skipped (SKIP_WALK=1)"}, "click walk"),
        ({**READY, "log": "stg-deploy: click walk (40 OK, 1 FAIL)"}, "1 FAIL"),
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
