"""Builds runner-service's app so scripts/check_typed_boundaries.py can walk its routes. The service has no committed
OpenAPI document yet, so this script holds only `document()`; the gate on a document is `ops_service_kit.openapi`.

uv run python scripts/check_openapi.py   # prints the operations the app serves
"""

from __future__ import annotations

from typing import Any, cast

from ops_runner.app import create_runner_app
from ops_runner.wasm import WasmPython
from ops_service_kit.settings import Settings, isolate_from_stack

# The app is built to read its routes: the fixed dev user, and none of a running stack's addresses.
isolate_from_stack()


def document() -> dict[str, Any]:
    """The app's document; building it starts no guest, so the runtime is not needed."""
    runtime = cast(WasmPython, None)
    return create_runner_app(runtime, settings=Settings(), tools=None).openapi()


def main() -> int:
    for path, ops in document()["paths"].items():
        print(path, ", ".join(sorted(ops)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
