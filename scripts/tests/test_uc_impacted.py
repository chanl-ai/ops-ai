"""The UI use case selector (scripts/uc_impacted.py), by failure mode: a changed page runs none of the use cases that
open it, or a path the map does not name passes silently instead of being printed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("uc_impacted", ROOT / "scripts" / "uc_impacted.py")
assert _spec is not None and _spec.loader is not None
uc_impacted = importlib.util.module_from_spec(_spec)
sys.modules["uc_impacted"] = uc_impacted
_spec.loader.exec_module(uc_impacted)

MAP = """
no-ui | docs/**, **/tests/** | -
chat | apps/console/src/components/chat/**, packages/ops_agent_kernel/** | uc-087 uc-074
files | apps/console/src/app/files/** | uc-112
"""


def test_a_changed_page_picks_its_use_cases_beside_core_and_an_unmapped_path_is_printed() -> None:
    changed = [
        "apps/console/src/components/chat/message-view.tsx",
        "packages/ops_agent_kernel/src/ops_agent_kernel/kernel.py",
        "services/agents-service/tests/unit/test_kernel.py",
        "docs/usecases/README.md",
        "apps/console/src/lib/format.ts",
    ]
    sel = uc_impacted.select(changed, ["uc-021", "uc-074"], uc_impacted.read_map(MAP))
    assert list(sel.reasons) == ["uc-021", "uc-074", "uc-087"], sel.reasons
    assert sel.reasons["uc-074"] == "core"
    assert sel.reasons["uc-087"].startswith("changed apps/console/src/components/chat/message-view.tsx and 1 more")
    assert sel.unmapped == ["apps/console/src/lib/format.ts"], sel.unmapped
