"""How a model adapter reports a call's usage to the metering wrapper around it (`metering.py`), without the two
importing each other. The report travels in a context variable, so concurrent fan-out calls each reach their own
wrapper."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from ops_metering import Usage

_reports: ContextVar[list[Usage] | None] = ContextVar("ops_usage_reports", default=None)


def report_usage(usage: Usage) -> None:
    """Called by a model adapter after each call; outside a metered call it does nothing."""
    sink = _reports.get()
    if sink is not None:
        sink.append(usage)


@contextmanager
def collecting() -> Generator[list[Usage]]:
    sink: list[Usage] = []
    token = _reports.set(sink)
    try:
        yield sink
    finally:
        _reports.reset(token)
