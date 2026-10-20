"""`uv run --project .. python -m fake_openai <dir>` from services/models-service/scripts: the fake on 127.0.0.1.

The port is FAKE_OPENAI_PORT, else `port` in <dir>/script.json, else 8746. It prints the setting models-service seeds
its openai-local connection from."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

from .app import create_app, load_script

DEFAULT_PORT = 8746


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".run/fake-openai").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    script = load_script(folder)
    port = int(os.environ.get("FAKE_OPENAI_PORT") or script.port or DEFAULT_PORT)
    print(f"OPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:{port}/v1", flush=True)
    # FAKE_OPENAI_HOST=0.0.0.0 when it runs in its own container (deploy/compose/try.yaml); `*` is every address, as
    # OPS_BIND_HOST takes it (deploy/fly/staging).
    host = os.environ.get("FAKE_OPENAI_HOST") or "127.0.0.1"
    host = "" if host == "*" else host
    uvicorn.run(create_app(script), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
