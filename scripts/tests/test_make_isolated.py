"""`make ... ISOLATED=1` acts only on the isolated stack, by failure mode: a run started inside
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
    # Without pytest's marker, so the shared-root rule is what refuses, not the rule for tests.
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE", "PYTEST_CURRENT_TEST"))}

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


def stack_values(tmp_path: Path, *args: str, env: dict[str, str]) -> dict[str, str]:
    """Every OPS_*_PORT and the models addresses as the root Makefile sets them for `args`."""
    show = tmp_path / "show.mk"
    show.write_text(
        "show:\n\t@$(foreach v,$(sort $(filter OPS_%_PORT OPS_MODELS_URL OPS_MODELS_FAKE_OPENAI_URL,$(.VARIABLES))),"
        'echo "$(v)=$($(v))";)\n'
    )
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE"))}
    out = subprocess.run(
        ["make", "-s", "--no-print-directory", "-f", "Makefile", "-f", str(show), "show", *args],
        cwd=ROOT,
        env={**clean, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in out.stdout.splitlines())


def test_the_isolated_stack_shares_no_port_with_the_shared_one(tmp_path: Path) -> None:
    shared, isolated = stack_values(tmp_path, env={}), stack_values(tmp_path, "ISOLATED=1", env={})
    ports = {n: p for n, p in shared.items() if n.endswith("_PORT") and n != "OPS_GATEWAY_PORT"}
    clash = {n: p for n, p in isolated.items() if n in ports and p in ports.values()}
    assert not clash, clash


def test_the_isolated_stack_reaches_its_own_models_service_whatever_the_copied_env_names(tmp_path: Path) -> None:
    shared = {"OPS_MODELS_URL": "http://127.0.0.1:8730", "OPS_MODELS_FAKE_OPENAI_URL": "http://127.0.0.1:8746/v1"}
    values = stack_values(tmp_path, "ISOLATED=1", env=shared)
    assert values["OPS_MODELS_URL"] == f"http://127.0.0.1:{values['OPS_MODELS_PORT']}" != shared["OPS_MODELS_URL"]
    assert values["OPS_MODELS_FAKE_OPENAI_URL"] == f"http://127.0.0.1:{values['OPS_FAKE_OPENAI_PORT']}/v1"


def test_a_test_cannot_stop_or_migrate_the_shared_stack() -> None:
    for goal in ("db-down", "down", "migrate", "reset-db"):
        out = dry_run(goal, "CONFIRM=yes", env={"PYTEST_CURRENT_TEST": "probe"})
        assert out.returncode != 0 and "refused" in out.stderr, (goal, out.stdout + out.stderr)
        assert "compose" not in out.stdout, (goal, out.stdout)
