"""`uv run python -m ops_runner.fetch`: puts the pinned CPython WASI build in runner_cache_dir, checked by SHA-256.

The file is 26 MB, so it is fetched at install rather than kept in git; a file already there is checked, not fetched."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings

from .wasm import sha256_of

WASM_FILE = "python-3.12.0.wasm"
log = get_logger("ops_runner.fetch")


def wasm_path(settings: Settings) -> Path:
    return settings.runner_cache_dir / WASM_FILE


def main() -> None:
    configure_logging()
    settings = Settings()
    path = wasm_path(settings)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        with httpx.stream("GET", settings.runner_wasm_url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with part.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        part.rename(path)
    found = sha256_of(path)
    if found != settings.runner_wasm_sha256:
        path.unlink()
        sys.exit(f"{path} had SHA-256 {found}, not the pinned {settings.runner_wasm_sha256}; removed it.")
    log.info("runner_wasm_ready", path=str(path))


if __name__ == "__main__":
    main()
