"""The console's JSON baselines (apps/console/scripts/*-baseline.json) may only fall, like the .txt ones.

`--commits` reads their history through scripts/baseline_history.py: a raised count, an added path or a new file is a
rise that needs a maintainer's approving review on the pull request. `--self-test` plants a rise in a scratch
repository and sees it refused.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

ROOT = Path(__file__).resolve().parents[1]
BASELINES_BEGAN = "f2f7893e913d7d10257cf517d3273bc4696e6b18"
PATHSPEC = "apps/console/scripts/*-baseline.json"


def commit_problems(root: Path = ROOT, began: str = BASELINES_BEGAN) -> list[str]:
    return baseline_history.problems(root, began, [PATHSPEC], baseline_history.json_rows)


def self_test() -> int:
    # The pre-commit hook runs this with GIT_DIR (and possibly GIT_INDEX_FILE, GIT_WORK_TREE) pointing at the real
    # repository; inherited, they send the scratch repository's `git add` and commit into the real index. Every git
    # call here and in baseline_history inherits os.environ, so they are removed for the self-test and put back after.
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("GIT_")}
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True, env=env
        ).stdout.strip()

    old = os.environ.get(baseline_history.REVIEW_ENV)
    os.environ[baseline_history.REVIEW_ENV] = "required"
    failures: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "apps/console/scripts").mkdir(parents=True)
            f = root / "apps/console/scripts/data-baseline.json"
            f.write_text('{"pageSize": {"a.tsx": 2}, "rawTable": ["b.tsx"]}\n')
            git(root, "init", "-q")
            git(root, "add", ".")
            git(root, "commit", "-qm", "begin")
            began = git(root, "rev-parse", "HEAD")
            for label, body, rises in (
                ("a lowered count", '{"pageSize": {"a.tsx": 1}, "rawTable": ["b.tsx"]}\n', False),
                ("a raised count", '{"pageSize": {"a.tsx": 3}, "rawTable": ["b.tsx"]}\n', True),
                ("a new path in a list", '{"pageSize": {"a.tsx": 3}, "rawTable": ["b.tsx", "c.tsx"]}\n', True),
            ):
                f.write_text(body)
                git(root, "commit", "-qam", label)
                red = bool(commit_problems(root, began))
                if red != rises or (label == "a lowered count" and red):
                    failures.append(f"{label}: expected {'refused' if rises else 'accepted'}")
                # the next case builds on a fresh base so only its own change is judged
                began = git(root, "rev-parse", "HEAD")
            f.write_text("{ not json")
            git(root, "commit", "-qam", "broken")
            if not commit_problems(root, began):
                failures.append("a file that stops parsing was accepted")
    finally:
        os.environ.update(saved)
        if old is None:
            os.environ.pop(baseline_history.REVIEW_ENV, None)
        else:
            os.environ[baseline_history.REVIEW_ENV] = old
    print("self-test: FAILED " + "; ".join(failures) if failures else "self-test: console baseline rises are refused")
    return 1 if failures else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--commits" in sys.argv:
        missing = commit_problems()
        sys.stdout.write(
            "\n".join(missing) + "\n" if missing else baseline_history.outcome("check_console_baselines") + "\n"
        )
        return 1 if missing else 0
    sys.stderr.write("usage: check_console_baselines.py --commits | --self-test\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
