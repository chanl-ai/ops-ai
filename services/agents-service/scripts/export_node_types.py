"""Writes the engine's node types, as `GET /v1/workflows/node-types` returns them without the per-team `unavailable`,
to apps/console/src/components/workflows/layout/node-types.json. The console's layout tests and the seed bake script
(c-486) read ports from it without a running stack; tests/engine/test_node_types_export.py fails when it is stale.

    uv run python scripts/export_node_types.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ops_engine import default_registry

TARGET = Path(__file__).resolve().parents[3] / "apps/console/src/components/workflows/layout/node-types.json"


def exported() -> str:
    types: list[dict[str, Any]] = [t.view() for t in default_registry().all()]
    return json.dumps(types, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    TARGET.write_text(exported())
    print(f"wrote {TARGET}")
