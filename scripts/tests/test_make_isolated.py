"""`make ... ISOLATED=1` acts only on the isolated stack (c-099, tick 14), by failure mode: a run started inside
another make inherits the shared stack's exported addresses and `?=` keeps them, so an isolated reset or migrate
would drop or change the shared database. `make -n` prints what would run without running it."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"
# What a make run on the shared stack exports to everything it starts.
SHARED_ENV = {
    "OPS_DATABASE_URL": SHARED,
    "OPS_TEST_DATABASE_URL": "postgresql+asyncpg://ops:ops@localhost:5477/ops_test",
    "OPS_PG_PORT": "5477",
    "OPS_AGENTS_PORT": "8700",
    "OPS_PLATFORM_PORT": "8710",
    "OPS_PLATFORM_URL": "http://127.0.0.1:8710",
    "OPS_STACK": "shared",
}


def dry_run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE"))}
    return subprocess.run(
        ["make", "-n", *args], cwd=ROOT, env={**clean, **env}, capture_output=True, text=True, check=False
    )


def test_an_isolated_reset_inside_a_shared_make_never_names_the_shared_database() -> None:
    out = dry_run("reset-db", "ISOLATED=1", "CONFIRM=yes", env=SHARED_ENV)
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert "localhost:5477/" not in text and "localhost:6477/ops_runtime" in text, text


def test_an_isolated_make_up_inside_a_shared_make_never_names_the_shared_database() -> None:
    out = dry_run("up", "ISOLATED=1", env=SHARED_ENV)
    text = out.stdout + out.stderr
    assert "localhost:5477/" not in text and "localhost:6477/ops_runtime" in text, text


def test_an_isolated_reset_of_the_shared_database_is_refused_before_anything_runs() -> None:
    out = dry_run("reset-db", "ISOLATED=1", "CONFIRM=yes", f"OPS_DATABASE_URL={SHARED}", env={})
    assert out.returncode != 0 and "reset-db refused" in out.stderr, out.stdout + out.stderr
    assert "stop-for-reset" not in out.stdout, out.stdout


def project(root: Path) -> str:
    """The compose project `make ports ISOLATED=1` names when run from `root`."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE"))}
    out = subprocess.run(
        ["make", "-s", "-f", str(root / "make/env.mk"), "-f", str(root / "make/dev.mk"), "ports", "ISOLATED=1"],
        cwd=root,
        env=clean,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.split("compose project ", 1)[1].split()[0]


def test_two_checkouts_never_share_one_isolated_compose_project(tmp_path: Path) -> None:
    # One shared name let `make db-down ISOLATED=1` in one checkout remove the stack a run in another was using.
    other = tmp_path / "ops-ai-other"
    (other / "make").mkdir(parents=True)
    for name in ("make/env.mk", "make/dev.mk"):
        (other / name).write_text((ROOT / name).read_text())
    ours, theirs = project(ROOT), project(other)
    assert ours.startswith("ops-runtime-isolated-") and theirs.startswith("ops-runtime-isolated-"), (ours, theirs)
    assert ours != theirs and project(ROOT) == ours, (ours, theirs)


def copy_checkout(dest: Path) -> Path:
    """Another checkout of this repository: the Makefile and make/ are all `make -n` reads."""
    (dest / "make").mkdir(parents=True)
    (dest / "Makefile").write_text((ROOT / "Makefile").read_text())
    for mk in (ROOT / "make").glob("*.mk"):
        (dest / "make" / mk.name).write_text(mk.read_text())
    return dest


def test_a_second_checkout_cannot_act_on_the_shared_stack(tmp_path: Path) -> None:
    # A worktree's `make up` whose ISOLATED=1 was lost (a zsh word list that did not split) migrated the shared
    # database to the worktree's branch and stopped the shared tools-service.
    record = tmp_path / "shared-root"
    record.write_text(f"{ROOT}\n")
    other = copy_checkout(tmp_path / "ops-ai-worktree")
    env = {"OPS_SHARED_ROOT_FILE": str(record)}
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE"))}

    def run(where: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "-n", *args], cwd=where, env={**clean, **env}, capture_output=True, text=True, check=False
        )

    # Starting the shared Postgres and OPA is safe from anywhere (a fixed compose project, --no-recreate, nothing
    # migrated): a test target from an export runs it first.
    assert "the shared stack runs from" not in run(other, "db-up").stderr
    assert "the shared stack runs from" in run(other, "migrate").stderr
    refused = run(other, "up")
    assert refused.returncode != 0 and "the shared stack runs from" in refused.stderr, refused.stderr
    assert "docker compose" not in refused.stdout and "migrate" not in refused.stdout, refused.stdout
    assert "the shared stack runs from" not in run(other, "up", "ISOLATED=1").stderr
    assert "the shared stack runs from" not in run(ROOT, "ports").stderr
