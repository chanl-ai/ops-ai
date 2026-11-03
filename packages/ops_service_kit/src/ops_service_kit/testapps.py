"""Frees the app a test built: FastAPI's module-level caches hold every endpoint closure it saw, and with it the app."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.dependencies import models as _models

__all__ = ["release_app_caches", "released_apps"]

_CACHES = ("_is_gen_callable_cached", "_is_async_gen_callable_cached", "_is_coroutine_callable_cached")


def release_app_caches() -> int:
    """Clears FastAPI's per-callable caches and returns how many it found (0 when a FastAPI release renamed them)."""
    found = 0
    for name in _CACHES:
        cache = getattr(_models, name, None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()
            found += 1
    return found


def released_apps() -> Iterator[None]:
    """Body of an autouse fixture: the test runs, then the caches let go of its app."""
    yield
    release_app_caches()
