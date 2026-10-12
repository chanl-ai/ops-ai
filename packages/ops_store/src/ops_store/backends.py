"""The backends the conformance suites run on. PostgreSQL provides every guarantee; it is the only backend today."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from .guarantees import Backend, Guarantee

CONFORMANCE_DATABASE = "ops_store_conformance"


def backends(database_url: str) -> tuple[Backend, ...]:
    """Every registered backend, each on its own conformance database on `database_url`'s server, named after that
    URL's database (`<db>_conformance`), so a suite never writes into a service's database and two sessions with
    different test databases never migrate each other's conformance database. `conformance.engine_for` creates it."""
    parsed = make_url(database_url)
    name = f"{parsed.database}_conformance" if parsed.database else CONFORMANCE_DATABASE
    url = parsed.set(database=name)
    return (Backend("postgres", url.render_as_string(hide_password=False), frozenset(Guarantee)),)
