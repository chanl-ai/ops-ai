"""A PostgreSQL URL as `fly postgres attach` prints it (`postgres://user:pass@host/db?sslmode=disable`) in the form
the services open (SQLAlchemy asyncpg). Standard library only, so deploy scripts and scripts/ import the one copy."""

from __future__ import annotations

from urllib.parse import parse_qs

PLAIN = ("postgres", "postgresql")


def is_plain(url: str) -> bool:
    """A PostgreSQL URL with no SQLAlchemy driver named."""
    return url.partition("://")[0] in PLAIN


def asyncpg_url(url: str) -> str:
    """`postgresql+asyncpg://` with the query string dropped: asyncpg takes no `sslmode` keyword and the cluster is
    reached over Fly's private network. A URL that already names a driver (or another database) is returned as is."""
    if not is_plain(url):
        return url
    return "postgresql+asyncpg://" + url.split("://", 1)[1].split("?", maxsplit=1)[0]


def ssl_mode(url: str) -> str | None:
    """The URL's `sslmode`, which asyncpg takes as `ssl=<mode>` (same names), or None when the URL sets none."""
    if not is_plain(url):
        return None
    found = parse_qs(url.partition("?")[2]).get("sslmode")
    return found[0] if found else None
