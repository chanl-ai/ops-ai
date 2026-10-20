"""The checkpointer's asyncpg pool reads the same DSN the services give SQLAlchemy, TLS setting included."""

from __future__ import annotations

from ops_checkpointer.saver import asyncpg_dsn


def test_a_tls_dsn_reaches_asyncpg_as_sslmode() -> None:
    # SQLAlchemy's asyncpg dialect takes `ssl=require`; asyncpg's own DSN parser sends `ssl` to the server as a setting,
    # which refuses it (CantChangeRuntimeParamError), so a TLS install's agents-service failed at start.
    url = "postgresql+asyncpg://ops_agents_runtime:pw@db.example.com:5432/ops?ssl=require"
    assert asyncpg_dsn(url) == "postgresql://ops_agents_runtime:pw@db.example.com:5432/ops?sslmode=require"


def test_a_dsn_without_tls_is_unchanged_apart_from_the_scheme() -> None:
    url = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"
    assert asyncpg_dsn(url) == "postgresql://ops:ops@localhost:5477/ops_runtime"
