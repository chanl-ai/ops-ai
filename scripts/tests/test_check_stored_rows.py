"""The database URL check_stored_rows opens, by failure mode: the plain URL staging stores is refused, an
already-normalised URL is altered, and an unreadable URL's error quotes the password."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_stored_rows as c  # pyright: ignore[reportMissingImports]


def opened(monkeypatch: pytest.MonkeyPatch, url: str) -> tuple[str, dict[str, Any]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(c, "load", lambda _path: lambda target, **options: calls.append((target, options)))
    c.open_engine(url)
    return calls[0]


def test_plain_url_reaches_the_engine_with_asyncpg_and_its_ssl_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    assert opened(monkeypatch, "postgres://u:pw@db.test/ops?sslmode=disable") == (
        "postgresql+asyncpg://u:pw@db.test/ops",
        {"connect_args": {"ssl": "disable"}},
    )


def test_sqlalchemy_url_is_opened_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql+asyncpg://u:pw@db.test/ops"
    assert opened(monkeypatch, url) == (url, {})


def test_unreadable_url_error_holds_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as stopped:
        opened(monkeypatch, "postgres://u:hunter2@db.test:port/ops")
    assert "hunter2" not in str(stopped.value)
