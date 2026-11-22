"""scripts/test_db.py's template, by failure mode: a changed migration keeps the old template, so tests run on a
schema the code no longer builds; a change in a chain the service does not use rebuilds its template for nothing; a
service with its own chain (kb, files, documents) gets a template without it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_db


def tree(root: Path) -> None:
    for d in (*test_db.CHAINS, "services/kb-service"):
        (root / d / "migrations/versions").mkdir(parents=True)
        (root / d / "migrations/versions/0001_x.py").write_text("revision = '0001_x'\n")
        (root / d / "alembic.ini").write_text("[alembic]\n")
    for c in test_db.SHARED_CODE:
        (root / c).mkdir(parents=True)
        (root / c / "m.py").write_text("x = 1\n")


def test_template_follows_the_chains_a_service_uses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree(tmp_path)
    monkeypatch.setattr(test_db, "ROOT", tmp_path)
    base = test_db.chains_for(None)
    kb = test_db.chains_for("kb-service")
    assert kb == (*base, "services/kb-service") and test_db.chains_for("ops_store") == base
    before = test_db.template_name(base), test_db.template_name(kb)
    assert before[0].startswith("ops_tpl_base_") and before[1].startswith("ops_tpl_kb_")

    # A change in kb's own chain rebuilds kb's template and leaves the base one alone.
    (tmp_path / "services/kb-service/migrations/versions/0002_y.py").write_text("revision = '0002_y'\n")
    assert test_db.template_name(kb) != before[1] and test_db.template_name(base) == before[0]

    # A change in a base chain rebuilds both.
    (tmp_path / "services/agents-service/migrations/versions/0001_x.py").write_text("revision = '0001_z'\n")
    assert test_db.template_name(base) != before[0] and test_db.template_name(kb) != before[1]
