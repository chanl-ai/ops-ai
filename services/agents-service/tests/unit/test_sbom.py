"""The SBOM's copyleft check must catch licences written the way PyPI classifiers write them."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


def copyleft() -> re.Pattern[str]:
    spec = importlib.util.spec_from_file_location("sbom", Path(__file__).resolve().parents[2] / "scripts" / "sbom.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sbom"] = module  # its dataclasses resolve their module by name
    spec.loader.exec_module(module)
    pattern: re.Pattern[str] = module.COPYLEFT
    return pattern


def test_copyleft_matches_classifier_spellings() -> None:
    pattern = copyleft()
    for licence in ("GNU Affero General Public License v3", "GNU Lesser General Public License v2 (LGPLv2)", "GPLv3"):
        assert pattern.search(licence), licence
    assert not pattern.search("MIT License")
