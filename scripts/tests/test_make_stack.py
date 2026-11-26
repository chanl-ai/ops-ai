"""One stack per machine (make/env.mk, make/git.mk, scripts/stack.sh), by failure mode: a worktree that keeps its own
pids and state starts a second stack beside the first; an offset stack that shares a port, the compose project or the
state folder with the default one acts on it; a service left running code from another checkout or another commit
serves the wrong branch; a review that checks out over uncommitted work loses it; a test that stops or migrates the
stack breaks it for everyone. `make -n` prints what would run without running it."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Without pytest's marker where a case needs the stack rules themselves, not the rule for tests.
CLEAN = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE", "PYTEST_CURRENT_TEST", "STACK_"))}


def git(where: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, check=True).stdout


def make(where: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", *args],
        cwd=where,
        env={**CLEAN, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def checkout(dest: Path) -> Path:
    """A git repository holding this one's Makefile and make/, which is all `make ports` and `make review` read."""
    (dest / "make").mkdir(parents=True)
    shutil.copy(ROOT / "Makefile", dest / "Makefile")
    for mk in (ROOT / "make").glob("*.mk"):
        shutil.copy(mk, dest / "make" / mk.name)
    git(dest.parent, "init", "-q", "-b", "main", str(dest))
    git(dest, "add", "-A")
    git(dest, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "make")
    return dest


def ports_line(where: Path, **env: str) -> str:
    return make(where, "-s", "ports", env=env).stdout.splitlines()[0]


def test_a_worktree_keeps_its_stack_state_in_the_main_checkout(tmp_path: Path) -> None:
    main = checkout(tmp_path / "repo")
    git(main, "worktree", "add", "-q", "--detach", str(tmp_path / "repo-review"))
    assert f"state in {main.resolve()}/.run" in ports_line(tmp_path / "repo-review")
    assert f"state in {main.resolve()}/.run" in ports_line(main)


def stack_values(*args: str, env: dict[str, str]) -> dict[str, str]:
    """Every OPS_*_PORT and the models addresses as the root Makefile sets them for `args`."""
    show = "show:\n\t@$(foreach v,$(sort $(filter OPS_%_PORT OPS_MODELS_URL OPS_MODELS_FAKE_OPENAI_URL,$(.VARIABLES))),"
    show += 'echo "$(v)=$($(v))";)\n'
    out = subprocess.run(
        ["make", "-s", "--no-print-directory", "-f", "Makefile", "-f", "/dev/stdin", "show", *args],
        cwd=ROOT,
        input=show,
        env={**CLEAN, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in out.stdout.splitlines())


def test_an_offset_stack_shares_no_port_compose_project_or_state_with_the_default_one() -> None:
    default, offset = stack_values(env={}), stack_values("OPS_PORT_OFFSET=30000", env={})
    ports = {n: p for n, p in default.items() if n.endswith("_PORT") and n != "OPS_GATEWAY_PORT"}
    clash = {n: p for n, p in offset.items() if n in ports and p in ports.values()}
    assert not clash, clash
    plain, shifted = ports_line(ROOT), ports_line(ROOT, OPS_PORT_OFFSET="30000")
    assert "compose project ops-runtime," in plain and "compose project ops-runtime-30000," in shifted, shifted
    assert shifted.endswith("/.run/offset-30000"), shifted


def test_an_offset_stack_reaches_its_own_models_service_whatever_the_env_names() -> None:
    named = {"OPS_MODELS_URL": "http://127.0.0.1:8730", "OPS_MODELS_FAKE_OPENAI_URL": "http://127.0.0.1:8746/v1"}
    values = stack_values("OPS_PORT_OFFSET=30000", env=named)
    assert values["OPS_MODELS_URL"] == f"http://127.0.0.1:{values['OPS_MODELS_PORT']}" != named["OPS_MODELS_URL"]
    assert values["OPS_MODELS_FAKE_OPENAI_URL"] == f"http://127.0.0.1:{values['OPS_FAKE_OPENAI_PORT']}/v1"


def test_a_test_cannot_stop_migrate_or_move_the_stack() -> None:
    for goal in ("db-down", "down", "migrate", "reset-db", "review"):
        out = subprocess.run(
            ["make", "-n", goal, "CONFIRM=yes", "BRANCH=main"],
            cwd=ROOT,
            env={**CLEAN, "PYTEST_CURRENT_TEST": "probe"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert out.returncode != 0 and "refused" in out.stderr, (goal, out.stdout + out.stderr)
        assert "compose" not in out.stdout and "worktree" not in out.stdout, (goal, out.stdout)


def test_review_never_checks_out_over_uncommitted_work_in_the_review_worktree(tmp_path: Path) -> None:
    origin = checkout(tmp_path / "origin")
    git(origin, "switch", "-q", "-c", "feat/x")
    (origin / "notes.txt").write_text("branch\n")
    git(origin, "add", "-A")
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    main = tmp_path / "repo"
    git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(main))
    review = tmp_path / "repo-review"
    git(main, "worktree", "add", "-q", "--detach", str(review), "origin/main")
    (review / "Makefile").write_text((review / "Makefile").read_text() + "# a reviewer's edit\n")
    out = make(main, "review", "BRANCH=feat/x")
    assert out.returncode != 0 and "uncommitted changes" in out.stdout + out.stderr, out.stdout + out.stderr
    assert "a reviewer's edit" in (review / "Makefile").read_text()
    assert not (review / "notes.txt").exists() and git(main, "branch", "--show-current").strip() == "main"


@pytest.fixture
def stack_repo(tmp_path: Path):
    """A repository with scripts/stack.sh and an agents-service folder changed by its second commit, and a process
    recorded as the running agents-service the way `start` records one."""
    repo = tmp_path / "stack"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/stack.sh", repo / "scripts/stack.sh")
    (repo / "services/agents-service").mkdir(parents=True)
    (repo / "services/agents-service/app.py").write_text("one\n")
    git(tmp_path, "init", "-q", str(repo))
    for text in ("one\n", "two\n"):
        (repo / "services/agents-service/app.py").write_text(text)
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", text.strip())
    process = subprocess.Popen(["sleep", "60"])
    (repo / ".run").mkdir()
    (repo / ".run/agents.pid").write_text(f"{process.pid}\n")
    yield repo
    process.kill()
    process.wait()


def fresh(repo: Path, root: Path | str, rev: str) -> subprocess.CompletedProcess[str]:
    (repo / ".run/agents.rev").write_text(f"{root} {rev}\n")
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
    return subprocess.run(
        ["bash", "scripts/stack.sh", "check-fresh"], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


def test_a_service_still_running_another_commits_code_is_stale(stack_repo: Path) -> None:
    older, head = git(stack_repo, "rev-parse", "HEAD~1").strip(), git(stack_repo, "rev-parse", "HEAD").strip()
    assert fresh(stack_repo, stack_repo, head).returncode == 0
    out = fresh(stack_repo, stack_repo, older)
    assert out.returncode == 1 and "its code differs" in out.stderr, out.stderr


def test_a_service_started_from_another_checkout_is_stale(stack_repo: Path) -> None:
    head = git(stack_repo, "rev-parse", "HEAD").strip()
    out = fresh(stack_repo, "/elsewhere/ops-ai", head)
    assert out.returncode == 1 and "runs from /elsewhere/ops-ai" in out.stderr, out.stderr


def test_health_warns_for_a_service_whose_recorded_commit_is_not_head(stack_repo: Path) -> None:
    older, head = git(stack_repo, "rev-parse", "HEAD~1").strip(), git(stack_repo, "rev-parse", "HEAD").strip()
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}

    def health() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/stack.sh", "health", "agents"],
            cwd=stack_repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    (stack_repo / ".run/agents.rev").write_text(f"{stack_repo} {head}\n")
    assert "WARNING" not in health().stdout
    (stack_repo / ".run/agents.rev").write_text(f"{stack_repo} {older}\n")
    out = health()
    assert (
        f"WARNING: agents runs {older[:8]}, tree is at {head[:8]}; restart with make restart SVC=agents" in out.stdout
    )


def fake_secrets(tmp_path: Path, *, fail: bool = False) -> dict[str, str]:
    """OPS_SECRETS_CMD naming a fake export on PATH: dotenv lines, or a failure."""
    tool = tmp_path / "fake-export"
    tool.write_text("#!/bin/sh\n" + ("exit 1\n" if fail else "echo SEC_KEY=v1\necho 'SEC_TWO=\"v2\"'\n"))
    tool.chmod(0o755)
    return {"PATH": f"{tmp_path}:{os.environ['PATH']}", "OPS_SECRETS_CMD": "fake-export --format dotenv"}


def env_check(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return make(ROOT, "-s", "print-env-check", "KEYS=SEC_KEY SEC_TWO", env=env)


def test_secrets_command_keys_load_below_the_callers_environment(tmp_path: Path) -> None:
    out = env_check({**fake_secrets(tmp_path), "SEC_TWO": ""})
    assert (out.stdout, out.stderr) == ("SEC_KEY: set\nSEC_TWO: not set\n", ""), "the caller's value (even empty) wins"
    assert not (ROOT / ".run" / "secrets.mk").exists(), "the secrets file does not outlive the make run"


def test_secrets_command_is_skipped_when_unset_or_off_without_a_word(tmp_path: Path) -> None:
    on = fake_secrets(tmp_path)
    nothing = ("SEC_KEY: not set\nSEC_TWO: not set\n", "")
    for env in ({**on, "OPS_NO_SECRETS_CMD": "1"}, {**on, "OPS_SECRETS_CMD": ""}, {"PATH": on["PATH"]}):
        out = env_check(env)
        assert (out.stdout, out.stderr) == nothing, env


def test_a_failing_secrets_command_warns_once_and_make_goes_on(tmp_path: Path) -> None:
    out = env_check(fake_secrets(tmp_path, fail=True))
    assert out.returncode == 0 and out.stdout == "SEC_KEY: not set\nSEC_TWO: not set\n"
    assert out.stderr == "OPS_SECRETS_CMD failed; using .env and the environment\n"


def dry(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """`make -n` from the real root: what would run, nothing run."""
    return make(ROOT, "-n", *args, env=env)


def test_a_shared_stack_resets_only_its_own_database_whatever_the_env_names() -> None:
    env = {"OPS_DATABASE_URL": "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"}
    out = dry("reset-db", "CONFIRM=yes", "OPS_INFRA=shared", "OPS_PORT_OFFSET=36000", env=env)
    assert out.returncode == 0, out.stderr
    assert '5477/ops_runtime_36000" --reset --confirmed-by-reset-db' in out.stdout, out.stdout
    assert '/ops_runtime" ' not in out.stdout, out.stdout


def test_a_shared_stack_keeps_the_infra_ports_and_moves_the_rest() -> None:
    plain, shared = stack_values(env={}), stack_values("OPS_INFRA=shared", "OPS_PORT_OFFSET=400", env={})
    infra = ("OPS_PG_PORT", "OPS_OPA_PORT", "OPS_GREENMAIL_SMTP_PORT", "OPS_GREENMAIL_IMAP_PORT")
    infra += ("OPS_MAILPIT_SMTP_PORT", "OPS_MAILPIT_HTTP_PORT")
    assert all(shared[n] == plain[n] for n in infra), {n: shared[n] for n in infra}
    assert shared["OPS_AGENTS_PORT"] != plain["OPS_AGENTS_PORT"]


def test_a_shared_stack_starts_and_stops_no_container_and_a_dry_run_writes_no_marker(tmp_path: Path) -> None:
    for goal in ("up", "down"):
        # make -n still runs a line that holds $(MAKE); the sample-install lines must not write their markers then.
        out = dry(goal, "OPS_INFRA=shared", "OPS_PORT_OFFSET=400", f"OPS_RUN_DIR={tmp_path}")
        assert out.returncode == 0, out.stderr
        assert "docker compose" not in out.stdout, (goal, out.stdout)
    assert not list(tmp_path.iterdir()), list(tmp_path.iterdir())


def test_a_real_sample_install_writes_its_markers_whatever_the_command_line_holds(tmp_path: Path) -> None:
    # MAKE=true stands in for the two sample installs; a spaced value with an n must not read as make -n.
    out = make(ROOT, "sample-install", "MAKE=true", f"OPS_RUN_DIR={tmp_path}", "NAME=sample team now")
    assert out.returncode == 0, out.stdout + out.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample-library.installed", "sample-team.installed"]


def test_a_shared_stacks_service_makefiles_start_and_stop_no_container() -> None:
    shared = ("OPS_INFRA=shared", "OPS_PORT_OFFSET=400")
    runs = [("services/agents-service", "db-up"), ("services/agents-service", "db-down")]
    runs += [("services/tools-service", "test"), ("services/tools-service", "test-gateway")]
    for folder, goal in runs:
        out = make(ROOT / folder, "-n", goal, "T=tests/none.py", *shared)
        assert out.returncode == 0, (folder, goal, out.stderr)
        assert "docker compose" not in out.stdout and "OPS_INFRA=shared" in out.stdout, (folder, goal, out.stdout)


def test_shared_needs_a_plain_numeric_offset_except_for_the_preview_targets() -> None:
    for offset in ("0", "00", "04", "4/5", "4?x", "4 5"):
        out = dry("up", "OPS_INFRA=shared", f"OPS_PORT_OFFSET={offset}")
        assert out.returncode != 0 and "OPS_INFRA=shared" in out.stderr, (offset, out.stderr)
    assert dry("wt", "BRANCH=x", "OPS_INFRA=shared").returncode == 0
    assert dry("wt-stop", "BRANCH=x", "OPS_INFRA=shared").returncode == 0
    mixed = dry("wt-list", "reset-db", "CONFIRM=yes", "OPS_INFRA=shared")
    assert "schema_sync" not in mixed.stdout and "OPS_INFRA=shared" in mixed.stderr, mixed.stdout


def test_a_shared_stacks_shell_and_use_case_reset_reach_the_default_containers() -> None:
    for goal in ("db-shell", "usecase-reset"):
        out = dry(goal, "OPS_INFRA=shared", "OPS_PORT_OFFSET=400")
        assert "-p ops-runtime " in out.stdout and "ops-runtime-400" not in out.stdout, (goal, out.stdout)
    assert "-d ops_runtime_400" in dry("db-shell", "OPS_INFRA=shared", "OPS_PORT_OFFSET=400").stdout


def test_db_move_image_is_refused_on_a_shared_stack() -> None:
    # Run for real: the guard is the recipe's first command, so nothing after it executes.
    out = make(ROOT, "db-move-image", "OPS_INFRA=shared", "OPS_PORT_OFFSET=400")
    assert out.returncode != 0 and "default stack owns the postgres container" in out.stdout, out.stdout + out.stderr
