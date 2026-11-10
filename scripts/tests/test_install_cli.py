"""scripts/ops_cli.sh and scripts/install_cli.sh, by failure mode: a CLI target that syncs the developer workspace or
runs with no `ops` and says nothing useful, an installer that ignores the mirror the machine is set up for, and an
offline install that still reaches for an index."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
BASE_PATH = "/usr/bin:/bin"


def executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def checkout(tmp_path: Path) -> Path:
    """A copy of the scripts in a folder of their own, so a .venv beside them is the test's to choose."""
    scripts = tmp_path / "repo" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("ops_cli.sh", "install_cli.sh"):
        shutil.copy(SCRIPTS / name, scripts / name)
    (tmp_path / "repo" / "sdk" / "python").mkdir(parents=True)
    return scripts


def run(script: Path, *args: str, path: str = BASE_PATH, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {"PATH": path, "HOME": str(script.parent)} | env
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=clean, check=False)


def test_no_ops_installed_prints_one_line_naming_install_cli_and_fails(tmp_path: Path) -> None:
    result = run(checkout(tmp_path) / "ops_cli.sh", "chat")
    assert result.returncode == 127
    assert result.stdout == "" and len(result.stderr.strip().splitlines()) == 1
    assert "make install-cli" in result.stderr


def test_opsai_on_path_wins_over_ops_and_the_workspace(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir = tmp_path / "bin"
    executable(bin_dir / "opsai", 'echo "opsai $@"\n')
    executable(bin_dir / "ops", '[ "$1" = --version ] && echo "ops-ai 0.1.0" && exit 0\necho "ops $@"\n')
    executable(tmp_path / "repo" / ".venv" / "bin" / "opsai", 'echo "venv-opsai $@"\n')
    result = run(scripts / "ops_cli.sh", "chat", path=f"{bin_dir}:{BASE_PATH}")
    assert (result.returncode, result.stdout.strip()) == (0, "opsai chat"), result.stderr


def test_older_ops_on_path_that_is_ours_still_runs(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir = tmp_path / "bin"
    executable(bin_dir / "ops", '[ "$1" = --version ] && echo "ops-ai 0.1.0" && exit 0\necho "path-ops $@"\n')
    result = run(scripts / "ops_cli.sh", "chat", "agents", path=f"{bin_dir}:{BASE_PATH}")
    assert (result.returncode, result.stdout.strip()) == (0, "path-ops chat agents"), result.stderr


def test_a_command_from_path_never_calls_uv(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir = tmp_path / "bin"
    executable(bin_dir / "ops", '[ "$1" = --version ] && echo "ops-ai 0.1.0" && exit 0\necho "path-ops $@"\n')
    executable(bin_dir / "uv", "echo uv-was-called >&2; exit 9\n")
    executable(tmp_path / "repo" / ".venv" / "bin" / "ops", 'echo "venv-ops $@"\n')
    result = run(scripts / "ops_cli.sh", "chat", "agents", path=f"{bin_dir}:{BASE_PATH}")
    assert (result.returncode, result.stdout.strip()) == (0, "path-ops chat agents"), result.stderr
    assert "uv-was-called" not in result.stderr


def test_an_ops_from_another_tool_is_not_run(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir = tmp_path / "bin"
    executable(bin_dir / "ops", 'echo "other tool $@"\n')
    executable(tmp_path / "repo" / ".venv" / "bin" / "ops", 'echo "venv-ops $@"\n')
    result = run(scripts / "ops_cli.sh", "chat", path=f"{bin_dir}:{BASE_PATH}")
    assert (result.returncode, result.stdout.strip()) == (0, "venv-ops chat"), result.stderr
    (tmp_path / "repo" / ".venv" / "bin" / "ops").unlink()
    again = run(scripts / "ops_cli.sh", "chat", path=f"{bin_dir}:{BASE_PATH}")
    assert again.returncode == 127 and "make install-cli" in again.stderr and "other tool" not in again.stdout


def test_workspace_venv_is_the_fallback_without_syncing(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    executable(tmp_path / "repo" / ".venv" / "bin" / "opsai", 'echo "venv-opsai $@"\n')
    executable(tmp_path / "bin" / "uv", "echo uv-was-called >&2; exit 9\n")
    result = run(scripts / "ops_cli.sh", "kb", path=f"{tmp_path / 'bin'}:{BASE_PATH}")
    assert (result.returncode, result.stdout.strip()) == (0, "venv-opsai kb"), result.stderr


def test_make_cli_targets_go_through_the_wrapper_not_a_workspace_run() -> None:
    result = subprocess.run(
        ["make", "-n", "-s", "chat", "AS=james", "SAY=hello"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "scripts/ops_cli.sh" in result.stdout and "uv run" not in result.stdout


def fake_uv(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "uv.log"
    uv = executable(
        tmp_path / "bin" / "uv",
        f'echo "$@" >> {log}\nenv | grep -E "^(UV_|SSL_CERT_FILE)" | sort >> {log}\n',
    )
    return uv.parent, log


def test_pip_mirror_settings_reach_uv_and_the_workspace_is_never_synced(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir, log = fake_uv(tmp_path)
    result = run(
        scripts / "install_cli.sh",
        path=f"{bin_dir}:{BASE_PATH}",
        PIP_INDEX_URL="https://nexus.example.com/repository/pypi-group/simple/",
        PIP_EXTRA_INDEX_URL="https://extra.example.com/simple/",
        PIP_TRUSTED_HOST="nexus.example.com",
        PIP_CERT="/etc/ssl/company-ca.pem",
    )
    assert result.returncode == 0, result.stderr
    text = log.read_text()
    install = next(line for line in text.splitlines() if line.startswith("tool install"))
    assert install.startswith("tool install --force") and "sync" not in install
    assert "UV_DEFAULT_INDEX=https://nexus.example.com/repository/pypi-group/simple/" in text
    assert "UV_INDEX=https://extra.example.com/simple/" in text
    assert "UV_INSECURE_HOST=nexus.example.com" in text
    assert "SSL_CERT_FILE=/etc/ssl/company-ca.pem" in text
    assert "UV_NO_CONFIG" not in text, "the person's own uv.toml must stay in force"


def test_uv_settings_already_set_are_not_overridden_by_pip_names(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir, log = fake_uv(tmp_path)
    run(
        scripts / "install_cli.sh",
        path=f"{bin_dir}:{BASE_PATH}",
        UV_DEFAULT_INDEX="https://uv.example.com/simple/",
        PIP_INDEX_URL="https://pip.example.com/simple/",
    )
    text = log.read_text()
    assert "UV_DEFAULT_INDEX=https://uv.example.com/simple/" in text and "pip.example.com" not in text


def test_wheels_install_is_offline_and_installs_by_name_not_from_the_checkout(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir, log = fake_uv(tmp_path)
    wheels = tmp_path / "wheelhouse"
    wheels.mkdir()
    result = run(scripts / "install_cli.sh", path=f"{bin_dir}:{BASE_PATH}", WHEELS=str(wheels))
    assert result.returncode == 0, result.stderr
    first = next(line for line in log.read_text().splitlines() if line.startswith("tool install"))
    assert f"--no-index --find-links {wheels.resolve()} ops-ai" in first
    assert "sdk/python" not in first


def test_missing_wheelhouse_folder_is_refused_before_anything_installs(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir, log = fake_uv(tmp_path)
    result = run(scripts / "install_cli.sh", path=f"{bin_dir}:{BASE_PATH}", WHEELS=str(tmp_path / "nope"))
    assert result.returncode == 2 and "make wheelhouse" in result.stderr
    assert not log.exists()


def test_without_uv_pip_installs_for_the_user_and_offline_when_given_wheels(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    log = tmp_path / "py.log"
    python = executable(tmp_path / "bin" / "fakepython", f'echo "$@" >> {log}\n')
    wheels = tmp_path / "wheelhouse"
    wheels.mkdir()
    assert run(scripts / "install_cli.sh", PYTHON=str(python)).returncode == 0
    assert run(scripts / "install_cli.sh", PYTHON=str(python), WHEELS=str(wheels)).returncode == 0
    online, offline = [line for line in log.read_text().splitlines() if "pip install" in line]
    assert online.startswith("-m pip install --user") and "--no-index" not in online and "sdk/python" in online
    assert "--no-index" in offline and f"--find-links {wheels.resolve()}" in offline and offline.endswith("ops-ai")


def test_the_persons_own_uv_toml_is_honoured(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        return
    scripts = checkout(tmp_path)
    (tmp_path / "repo" / "sdk" / "python" / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    config = tmp_path / "xdg" / "uv"
    config.mkdir(parents=True)
    (config / "uv.toml").write_text('index-url = "http://127.0.0.1:9/company/simple"\n')
    result = run(
        scripts / "install_cli.sh",
        path=f"{Path(uv).parent}:{BASE_PATH}",
        XDG_CONFIG_HOME=str(tmp_path / "xdg"),
        UV_CACHE_DIR=str(tmp_path / "cache"),
    )
    assert result.returncode != 0 and "127.0.0.1:9/company/simple" in result.stderr, result.stderr


def fake_uv_with_shims(tmp_path: Path) -> Path:
    """A uv whose `tool install` writes the two shims the real package ships, into the tool folder it reports."""
    tool_bin = tmp_path / "toolbin"
    executable(
        tmp_path / "bin" / "uv",
        f'if [ "$1 $2 $3" = "tool dir --bin" ]; then echo {tool_bin}; exit 0; fi\n'
        f"mkdir -p {tool_bin}; : > {tool_bin}/opsai; : > {tool_bin}/ops\n",
    )
    return tool_bin


def test_the_ops_alias_is_dropped_when_another_tool_owns_the_name(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    tool_bin = fake_uv_with_shims(tmp_path)
    other = tmp_path / "other"
    executable(other / "ops", 'echo "some other ops"\n')
    result = run(scripts / "install_cli.sh", path=f"{tmp_path / 'bin'}:{other}:{BASE_PATH}")
    assert result.returncode == 0, result.stderr
    assert (tool_bin / "opsai").exists() and not (tool_bin / "ops").exists()
    assert "another tool already owns the name ops" in result.stdout


def test_the_ops_alias_is_kept_and_announced_when_the_name_is_free(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    tool_bin = fake_uv_with_shims(tmp_path)
    result = run(scripts / "install_cli.sh", path=f"{tmp_path / 'bin'}:{BASE_PATH}")
    assert result.returncode == 0, result.stderr
    assert (tool_bin / "opsai").exists() and (tool_bin / "ops").exists()
    assert "alias for opsai" in result.stdout


def test_from_index_installs_the_package_by_name_without_building_the_checkout(tmp_path: Path) -> None:
    scripts = checkout(tmp_path)
    bin_dir, log = fake_uv(tmp_path)
    result = run(scripts / "install_cli.sh", path=f"{bin_dir}:{BASE_PATH}", FROM_INDEX="1")
    assert result.returncode == 0, result.stderr
    install = next(line for line in log.read_text().splitlines() if line.startswith("tool install"))
    assert install.endswith("ops-ai") and "--no-index" not in install and "sdk/python" not in install
