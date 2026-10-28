"""One WASM runtime for the suite: compiling the module is the slow part, and every run gets its own store anyway."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ops_runner.fetch import compiled_dir, wasm_path
from ops_runner.fetch import main as fetch
from ops_runner.wasm import WasmPython
from ops_service_kit.settings import Settings


@pytest.fixture(scope="session")
def runtime() -> Iterator[WasmPython]:
    settings = Settings()
    path = wasm_path(settings)
    if not path.is_file():
        # The build is gitignored: a fresh checkout (QA's included) fetches it once, checked by its SHA-256.
        fetch()
    rt = WasmPython(path, sha256=settings.runner_wasm_sha256, compiled_dir=compiled_dir(settings))
    yield rt
    rt.close()
