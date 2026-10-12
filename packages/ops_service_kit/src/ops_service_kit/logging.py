"""Logger factory; packages log through this so context fields are bound in one place (spec 17 rule 6)."""

from __future__ import annotations

import logging as _logging
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

    def info(self, event: str, **fields: Any) -> None:
        self._log.info(self._fmt(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._log.warning(self._fmt(event, fields))

    def exception(self, event: str, **fields: Any) -> None:
        self._log.exception(self._fmt(event, fields))


def get_logger(name: str) -> BoundLogger:
    return BoundLogger(name)


def configure_logging() -> None:
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
