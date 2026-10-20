"""Every revision after the eight named in schema.ONLINE_ONLY renders as offline SQL, so an upgrade bundle can be
generated for a DBA. A revision that reads rows or inspects tables (op.get_bind(), sa.inspect) fails here: write it
with Alembic operations and plain SQL instead. The eight named still fail, so the list cannot go stale unseen."""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import OFFLINE_URL, ONLINE_ONLY, ROOT, chains


def _renders(chain: str, prev: str | None, rev: str) -> bool:
    service = ROOT / "services" / f"{chain}-service"
    cfg = Config(str(service / "alembic.ini"))
    cfg.set_main_option("script_location", str(service / "migrations"))
    cfg.stdout = io.StringIO()
    cwd = os.getcwd()
    os.chdir(service)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            command.upgrade(cfg, f"{prev or 'base'}:{rev}", sql=True)
        return True
    except Exception:  # any failure to render is the finding
        return False
    finally:
        os.chdir(cwd)


@pytest.fixture(autouse=True)
def _offline_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DATABASE_URL", OFFLINE_URL)


@pytest.mark.parametrize("chain", chains())
def test_every_revision_but_the_named_ones_renders_offline(chain: str) -> None:
    script = ScriptDirectory(str(ROOT / "services" / f"{chain}-service" / "migrations"))
    revisions = list(reversed(list(script.walk_revisions())))
    failing = {
        r.revision
        for r in revisions
        if not _renders(chain, r.down_revision if isinstance(r.down_revision, str) else None, r.revision)
    }
    assert failing == ONLINE_ONLY.get(chain, set())
