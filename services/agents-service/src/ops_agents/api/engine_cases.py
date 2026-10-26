"""The engine's CasePort (c-219): Open case and Add to case steps write the run's team's cases. A case opens in the
run's team with the run as its first entry; a run joins only a case of its own team. A test run's case says so in
its subject, so trying a workflow never reads as a customer's issue. Runs in the worker's pass, under the run's
tenant."""

from __future__ import annotations

from typing import Any, cast

from ops_engine.ports import CaseNotFoundError, CaseTypeNotFoundError, OpenedCase
from ops_engine.store import RunStore

from ..store.case_types import CaseTypeNotFound
from ..store.cases import CaseNotFound, CaseStore, Priority
from .case_type_seeds import seeded_case_types

TEST_PREFIX = "[Test] "


class RunCases:
    def __init__(self, runs: RunStore, cases: CaseStore) -> None:
        self.runs, self.cases = runs, cases

    async def _team_of(self, run_id: str) -> tuple[str, dict[str, Any]]:
        run = await self.runs.get(run_id)
        team = str((run or {}).get("team_id") or "")
        if run is None or not team:
            # No team would reach every team's cases; the step fails rather than guess one.
            raise RuntimeError(f"run {run_id} has no team, so it opens and joins no cases")
        return team, run

    async def open(self, run_id: str, fields: dict[str, Any], key: str) -> OpenedCase:
        team, run = await self._team_of(run_id)
        subject = str(fields["subject"])
        if run.get("mode") == "test" and not subject.startswith(TEST_PREFIX):
            subject = TEST_PREFIX + subject
        type_id = str(fields.get("caseType") or "") or None
        type_version: int | None = None
        if type_id:
            try:
                type_version, _ = await (await seeded_case_types(self.cases.engine, team)).published(type_id)
            except CaseTypeNotFound as e:
                raise CaseTypeNotFoundError(type_id) from e
        opened = await self.cases.open(
            team_id=team,
            subject=subject[:300],
            priority=cast(Priority, fields.get("priority") or "normal"),
            by=f"run:{run_id}",
            producer_key=key,
            customer_id=fields.get("customerId"),
            customer_name=fields.get("customerName"),
            assignee=fields.get("assignee"),
            fields=cast(dict[str, Any] | None, fields.get("fields")),
            type_id=type_id,
            type_version=type_version,
        )
        case_id = str(opened.case["id"])
        if opened.created:
            await self.cases.add_event(case_id, "run", ref=run_id, detail={}, by=f"run:{run_id}")
        return OpenedCase(case_id, opened.created)

    async def add(
        self,
        run_id: str,
        case_id: str,
        note: str | None,
        fields: dict[str, Any] | None = None,
        *,
        status: str | None = None,
        key: str | None = None,
    ) -> None:
        team, _ = await self._team_of(run_id)
        try:
            await self.cases.get(case_id, [team])
        except CaseNotFound as e:
            raise CaseNotFoundError(case_id) from e
        if fields:
            # A retried step sets the same values again, which changes nothing.
            await self.cases.merge_fields(case_id, fields)
        if status:
            if status == "closed":
                raise ValueError("a run does not close a case; closing is a person's")
            # The same status again changes nothing, so a retried step records no second move.
            await self.cases.change(case_id, {"status": status}, by=f"run:{run_id}")
        events = await self.cases.events(case_id)
        by = f"run:{run_id}"
        # A retried step finds its entry on the timeline already and adds nothing: the run's own entry the first time
        # it joins, a note of a later step of the same run by that step's key.
        if not any(e["kind"] == "run" and e["ref"] == run_id for e in events):
            await self.cases.add_event(case_id, "run", ref=run_id, detail={"text": note} if note else {}, by=by)
        elif note and key and not any(e["kind"] == "note" and e["ref"] == key for e in events):
            await self.cases.add_event(case_id, "note", ref=key, detail={"text": note}, by=by)
