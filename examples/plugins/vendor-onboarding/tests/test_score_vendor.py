"""Unit tests for contributions/functions/score_vendor.py, run with plain pytest and no stack.

The function file is loaded by path, as the runner loads it: it is not a package, and in the sandbox `ops` is a global
the runner puts in scope. Here a small fake stands in for `ops`, so `main` is tested without tools-service.

One test per way the scoring can be wrong in production:
1. a sanctions hit must block the vendor, however good the rest looks;
2. a company the registry lists as anything but active must block the vendor;
3. a company the registry does not know must not pass as low risk;
4. a clean, established vendor must land in the low band with no reasons;
5. each deduction must be named in the reasons, so the reviewer sees why the score fell;
6. a policy given by the workflow must override the function's defaults;
7. `main` must screen the vendor through the bound tool with its own name and country.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

FUNCTION = Path(__file__).resolve().parents[1] / "contributions" / "functions" / "score_vendor.py"

CLEAN_VENDOR = {
    "legalName": "Brightwater Logistics Ltd",
    "country": "CA",
    "registrationNumber": "RC-1048213",
    "annualSpend": 120000,
}
ACTIVE_COMPANY = {
    "registrationNumber": "RC-1048213",
    "legalName": "Brightwater Logistics Ltd.",
    "country": "CA",
    "status": "active",
    "yearsTrading": 10,
}
NO_HITS: dict[str, Any] = {"hits": []}


@pytest.fixture
def fn() -> ModuleType:
    spec = importlib.util.spec_from_file_location("score_vendor", FUNCTION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeOps:
    """What the runner gives the function as `ops`: records each call and answers from `answers`."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        self.calls.append((tool, args or {}))
        return self.answers[tool]


def test_a_sanctions_hit_blocks_the_vendor(fn: ModuleType) -> None:
    hit = {"hits": [{"list": "Consolidated sanctions list", "name": "Brightwater Logistics Ltd", "score": 0.97}]}
    out = fn.score(CLEAN_VENDOR, ACTIVE_COMPANY, hit)
    assert out["band"] == "blocked"
    assert any("sanctions" in r for r in out["reasons"])


def test_a_company_that_is_not_active_blocks_the_vendor(fn: ModuleType) -> None:
    out = fn.score(CLEAN_VENDOR, {**ACTIVE_COMPANY, "status": "dissolved"}, NO_HITS)
    assert out["band"] == "blocked"
    assert any("dissolved" in r for r in out["reasons"])


def test_a_company_the_registry_does_not_know_is_not_low_risk(fn: ModuleType) -> None:
    out = fn.score(CLEAN_VENDOR, None, NO_HITS)
    assert out["band"] in {"high", "blocked"}
    assert any("RC-1048213" in r for r in out["reasons"])


def test_a_clean_established_vendor_is_low_risk(fn: ModuleType) -> None:
    out = fn.score(CLEAN_VENDOR, ACTIVE_COMPANY, NO_HITS)
    assert out == {"score": 100, "band": "low", "reasons": [], "screeningHits": 0}


def test_each_deduction_is_named(fn: ModuleType) -> None:
    vendor = {**CLEAN_VENDOR, "legalName": "Brightwater Freight Inc", "annualSpend": 900000}
    young = {**ACTIVE_COMPANY, "yearsTrading": 1}
    out = fn.score(vendor, young, NO_HITS)
    # 100 - 30 (under 2 years) - 20 (name differs) - 15 (spend over the review line) = 35
    assert out["score"] == 35
    assert out["band"] == "high"
    assert len(out["reasons"]) == 3


def test_the_workflow_policy_overrides_the_defaults(fn: ModuleType) -> None:
    policy = {"highRiskCountries": ["CA"], "spendReviewAbove": 50000}
    out = fn.score(CLEAN_VENDOR, ACTIVE_COMPANY, NO_HITS, policy)
    # 100 - 25 (country on the policy's list) - 15 (spend over the policy's line) = 60
    assert out["score"] == 60
    assert out["band"] == "medium"


def test_main_screens_the_vendor_through_the_bound_tool(fn: ModuleType) -> None:
    ops = FakeOps({"screen_vendor": NO_HITS})
    fn.ops = ops  # in the sandbox the runner puts `ops` in the function's globals
    out = fn.main({"vendor": CLEAN_VENDOR, "company": ACTIVE_COMPANY})
    assert ops.calls == [("screen_vendor", {"legal_name": "Brightwater Logistics Ltd", "country": "CA"})]
    assert out["band"] == "low"
