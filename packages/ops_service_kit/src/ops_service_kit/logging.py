"""Logger factory; packages log through this so context fields are bound in one place (spec 17 rule 6)."""

from __future__ import annotations

import logging as _logging
import sys
from typing import Any


class BoundLogger:
    def __init__(self, name: str, context: dict[str, Any] | None = None) -> None:
        self._log = _logging.getLogger(name)
        self._context = context or {}

    def bind(self, **fields: Any) -> BoundLogger:
        return BoundLogger(self._log.name, {**self._context, **fields})

    def _fmt(self, event: str, fields: dict[str, Any]) -> str:
        merged = {**self._context, **fields}
        return event + "".join(f" {k}={v}" for k, v in merged.items())

    def debug(self, event: str, **fields: Any) -> None:
        self._log.debug(self._fmt(event, fields))

    def info(self, event: str, **fields: Any) -> None:
        self._log.info(self._fmt(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._log.warning(self._fmt(event, fields))

    def exception(self, event: str, **fields: Any) -> None:
        self._log.exception(self._fmt(event, fields))


def get_logger(name: str) -> BoundLogger:
    return BoundLogger(name)


def quiet_request_logs() -> None:
    """httpx and httpcore log every request's full URL at INFO, and a URL can carry a resolved secret (a query-string
    API key, c-070), so their request lines stay out of the logs; warnings and errors still show."""
    for name in ("httpx", "httpcore"):
        _logging.getLogger(name).setLevel(_logging.WARNING)


def configure_logging() -> None:
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    quiet_request_logs()


def request_logger() -> _logging.Logger:
    """The `ops.request` logger (c-560): its own handler printing the bare message, and no propagation, so each line is
    exactly one JSON object whatever format the service's root logger prints."""
    logger = _logging.getLogger("ops.request")
    if not logger.handlers:
        handler = _logging.StreamHandler(sys.stderr)
        handler.setFormatter(_logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(_logging.INFO)
        logger.propagate = False
    return logger
