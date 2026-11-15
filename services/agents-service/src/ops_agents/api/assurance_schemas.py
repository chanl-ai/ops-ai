"""The Evals page's answers: suites, runs and publish checks, each with the page's stats and tab counts."""

from __future__ import annotations

from typing import Literal

from ops_service_kit.http import ListResult, Out


class AssetRef(Out):
    kind: Literal["agent", "skill", "workflow"]
    id: str
    name: str
    href: str


class SuiteCaseResult(Out):
    case_id: str
    name: str
    candidate: Literal["pass", "fail"]
    live: Literal["pass", "fail"] | None
    regression: bool
    human_verdict: Literal["pass", "fail"] | None = None


class SuiteDraftCase(Out):
    id: str
    name: str
    input: str
    source: Literal["review"]
    status: Literal["draft"]
    review_id: str
    reason: str
    created_by: str
    created_at: str


class AssuranceSuite(Out):
    id: str
    asset: AssetRef
    owner: str
    tier: str
    cases: int
    draft_cases: int
    pass_rate: float | None
    live_pass_rate: float | None
    regressions: int | None
    candidate_version: int | None
    live_version: int | None
    last_run_at: str | None
    failing: bool
    results: list[SuiteCaseResult]
    drafts: list[SuiteDraftCase]


class AssuranceRun(Out):
    id: str
    asset: AssetRef
    version: int
    trigger: str
    passed: int
    total: int
    pass_rate: float
    regressions: int
    duration_ms: int
    cost_usd: float
    ran_at: str
    review_id: str | None = None


class GateStep(Out):
    step: Literal["structural", "pass_rate", "regressions"]
    label: str
    mode: Literal["blocking", "advisory"]
    result: Literal["pass", "fail", "pending"]
    detail: str


class AssuranceGate(Out):
    review_id: str
    asset: AssetRef
    from_version: int | None
    to_version: int
    tier: str
    requested_by: str
    requested_at: str
    review_status: Literal["pending", "approved", "rejected", "returned"]
    steps: list[GateStep]
    blocked: bool


class AssuranceStats(Out):
    failing_suites: int
    gates_blocked: int
    live_untested: int
    not_run: int


class TabCounts(Out):
    suites: int
    runs: int
    gates: int


class SuiteList(ListResult[AssuranceSuite]):
    stats: AssuranceStats
    tab_counts: TabCounts


class RunList(ListResult[AssuranceRun]):
    stats: AssuranceStats
    tab_counts: TabCounts


class GateList(ListResult[AssuranceGate]):
    stats: AssuranceStats
    tab_counts: TabCounts
