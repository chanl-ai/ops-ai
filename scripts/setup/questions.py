"""The questions, in order, and the file the passed answers go to. An answers file (`make setup ANSWERS=<file>`)
answers them all with no prompt; its keys are install.sh's (DATABASE, MODEL, MODEL_NAME, MODEL_API_KEY) plus the ones
setup adds, so one file serves both. Without one, each question is asked; piped lines answer them in order."""

from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from setup import database, mirror, model
from setup.report import Result

ROOT = Path(__file__).resolve().parents[2]
SETUP_KEYS = ("RUNS_ON", "DOCKER", "PYPI_MIRROR", "NPM_MIRROR", "IMAGE_REGISTRY", "MODEL_PROVIDER", "KUBE_OVERLAY")
# install.sh's own answers keys (install.sh, the answers file loop); setup reads four of them and passes the rest by.
INSTALL_KEYS = [
    "PUBLIC_URL",
    "PORT",
    "PROJECT",
    "ORG_NAME",
    "ADMIN_EMAIL",
    "ADMIN_NAME",
    "ADMIN_PASSWORD",
    "DATABASE",
    "DB_MODE",
    "MODEL",
    "MODEL_NAME",
    "MODEL_API_KEY",
    "MODEL_INPUT_PRICE",
    "MODEL_OUTPUT_PRICE",
    "MODEL_BUDGET",
    "VERSION",
    "IMAGES",
    "OFFLINE",
]
RUNS_ON = ("laptop", "shared-vm", "devcontainer", "docker", "kubernetes")
SECRET_KEYS = ("MODEL_API_KEY",)


def read_answers(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key not in SETUP_KEYS and key not in INSTALL_KEYS:
            raise SystemExit(f"setup: answers file: unknown key {key}")
        out[key] = value
    return out


def target(runs_on: str) -> Path:
    """Where settings go: a checkout's .env, the devcontainer's .env.local (a shared VM's workspace is one), an
    answers file for ./install.sh, or the Kubernetes overlay's own git-ignored env file. SETUP_FILE overrides it."""
    if os.environ.get("SETUP_FILE"):
        return Path(os.environ["SETUP_FILE"])
    return {
        "laptop": ROOT / ".env",
        "shared-vm": ROOT / ".devcontainer" / ".env.local",
        "devcontainer": ROOT / ".devcontainer" / ".env.local",
        "docker": ROOT / ".env.install",
    }.get(runs_on, ROOT / "deploy" / "k8s" / "overlays" / "example" / "setup.env")


def _minimum(name: str) -> tuple[int, ...]:
    """install.sh's MIN_DOCKER or MIN_COMPOSE, so the two never disagree."""
    found = re.search(rf"^{name}=([\d.]+)", (ROOT / "install.sh").read_text(), re.M)
    return tuple(int(x) for x in (found.group(1) if found else "0").split("."))


def _version(cmd: list[str]) -> tuple[int, ...] | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"(\d+)\.(\d+)", out)
    return (int(found.group(1)), int(found.group(2))) if found else None


def docker(answer: str, needed: bool) -> Result:
    item = "docker"
    if os.environ.get("OPS_INFRA") == "external":
        return Result(
            item, True, "the devcontainer runs the side containers; the workspace needs no Docker", answer=answer
        )
    if answer.strip().lower() in ("no", "n", "false"):
        if needed:
            return Result(item, False, "our database container needs Docker", answer=answer)
        return Result(item, True, "not used here", answer=answer)
    engine = _version(["docker", "version", "--format", "{{.Server.Version}}"])
    compose = _version(["docker", "compose", "version", "--short"])
    need_engine, need_compose = _minimum("MIN_DOCKER"), _minimum("MIN_COMPOSE")
    shown = f"engine {'.'.join(map(str, engine or ()))}, compose {'.'.join(map(str, compose or ()))}"
    if engine is None or compose is None:
        return Result(item, False, "docker or docker compose did not answer (is the engine running?)", answer=answer)
    if engine < need_engine or compose < need_compose:
        want = f"{'.'.join(map(str, need_engine))} and {'.'.join(map(str, need_compose))}"
        return Result(item, False, f"{shown}; needs at least {want}", answer=answer)
    return Result(item, True, shown, answer=answer)


def asker(answers: dict[str, str] | None) -> Callable[[str, str, str], str]:
    def ask(key: str, prompt: str, default: str) -> str:
        if answers is not None:
            return answers.get(key, default)
        if not prompt:  # read from an answers file only
            return default
        shown = f"{prompt} [{default}]: " if default else f"{prompt}: "
        if key in SECRET_KEYS and sys.stdin.isatty():
            value = getpass.getpass(shown)
        else:
            print(shown, end="", flush=True)
            value = sys.stdin.readline().strip()
            print()
        return value or default

    return ask


def run(answers: dict[str, str] | None) -> tuple[str, list[Result]]:
    ask = asker(answers)
    runs_on = ask("RUNS_ON", f"Where does it run ({', '.join(RUNS_ON)})", "laptop")
    if runs_on not in RUNS_ON:
        return runs_on, [Result("runs on", False, f"one of {', '.join(RUNS_ON)}, not {runs_on!r}")]
    db = ask("DATABASE", "Database: 'builtin' for our container, or a PostgreSQL URL", database.CONTAINER)
    results = [docker(ask("DOCKER", "Is Docker here (yes or no)", "yes"), needed=db == database.CONTAINER)]
    results.append(database.check(db))
    results.append(mirror.pypi(ask("PYPI_MIRROR", "PyPI mirror index URL, or none", "none")))
    results.append(mirror.npm(ask("NPM_MIRROR", "npm mirror registry URL, or none", "none")))
    results.append(mirror.registry(ask("IMAGE_REGISTRY", "Container registry prefix, or none", "none")))
    legacy = ask("MODEL", "", "")
    provider = ask(
        "MODEL_PROVIDER", "Model provider (openai, azure-openai, fake)", "fake" if legacy in ("", "test") else "openai"
    )
    base = "" if legacy == "test" else legacy
    if provider == "azure-openai" and not base:
        base = ask("MODEL", "Azure OpenAI base URL (ending in /openai/v1)", "")
    name = ask("MODEL_NAME", "Model id", "") if provider != "fake" else ""
    key = ask("MODEL_API_KEY", "API key", "") if provider != "fake" else ""
    results.append(model.check(provider, base, name, key))
    return runs_on, results


def for_install(results: list[Result]) -> list[Result]:
    """The answers ./install.sh reads, from the settings a checkout would get: the database URL as DATABASE, the
    model as MODEL (its base URL, or `test` for the fake), MODEL_NAME and MODEL_API_KEY, the mirrors by their keys."""
    renames = {"OPS_DATABASE_URL": "DATABASE", "UV_DEFAULT_INDEX": "PYPI_MIRROR", "NPM_CONFIG_REGISTRY": "NPM_MIRROR"}
    renames |= {
        "OPS_BASE_IMAGE_PREFIX": "IMAGE_REGISTRY",
        "OPENAI_API_KEY": "MODEL_API_KEY",
        "DEMO_MODEL": "MODEL_NAME",
    }
    out: list[Result] = []
    for r in results:
        settings = {renames.get(k, k): v for k, v in r.settings.items() if k != "OPENAI_BASE_URL"}
        if r.item == "database" and r.ok and not settings:
            settings = {"DATABASE": "builtin"}
        if r.item == "model" and r.ok:
            fake = settings.get("MODEL_NAME") == "fake"
            settings = (
                {"MODEL": "test"} if fake else {"MODEL": r.settings.get("OPENAI_BASE_URL", model.OPENAI)} | settings
            )
        out.append(Result(r.item, r.ok, r.reason, settings, r.secrets, r.answer))
    return out
