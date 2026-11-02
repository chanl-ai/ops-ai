"""Workflow authoring and runs over the generated agents operations. `ops.raw.agents.workflows_*` stays available."""

from __future__ import annotations

import csv
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

from ._io import (
    Definition,
    as_folder,
    definition_body,
    definition_in,
    dump_definition,
    load_data,
    load_definition,
)
from ._transport import page_items
from .errors import NotFound

PLANNED = "This command is planned; the public API for it is not shipped."


class WorkflowCheck(dict[str, Any]):
    """The validate response, with `raise_for_errors` so a script stops on the first failing check."""

    @property
    def ok(self) -> bool:
        return bool(self.get("ok"))

    @property
    def checks(self) -> list[dict[str, Any]]:
        return list(self.get("checks") or [])

    @property
    def errors(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if c.get("level") != "warning"]

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return [c for c in self.get("checks") or [] if c.get("level") == "warning"]

    def raise_for_errors(self) -> None:
        if self.ok:
            return
        first = self.errors[0] if self.errors else {"code": "invalid", "message": "the definition failed checks"}
        where = first.get("path") or first.get("node") or first.get("code")
        raise ValueError(f"{where}: {first.get('message')}")


def _diff(next_def: dict[str, Any], current: dict[str, Any] | None) -> list[str]:
    if current is None:
        return [f"create {next_def.get('id')}"]
    held = current.get("definition") or {}
    changes: list[str] = []
    if held.get("digest") and next_def.get("id") == held.get("id") and current.get("digest"):
        pass
    next_nodes = {n.get("id"): n for n in next_def.get("nodes") or []}
    held_nodes = {n.get("id"): n for n in held.get("nodes") or []}
    for nid, node in next_nodes.items():
        if nid not in held_nodes:
            changes.append(f"add node {nid}")
        elif node != held_nodes[nid]:
            changes.append(f"change node {nid}")
    for nid in held_nodes:
        if nid not in next_nodes:
            changes.append(f"remove node {nid}")
    if next_def.get("connections") != held.get("connections"):
        changes.append("change connections")
    if next_def.get("name") != held.get("name"):
        changes.append("rename")
    return changes or ["no changes"]


class Workflows:
    def __init__(self, raw: Any, runs: Any) -> None:
        self._raw = raw
        self._runs = runs

    def list(self, **query: Any) -> Iterator[Any]:
        nxt: dict[str, Any] = {}
        while True:
            items, nxt_more = page_items(self._raw.agents.workflows_list_definitions(**{**query, **nxt}))
            yield from items
            if nxt_more is None:
                return
            nxt = nxt_more

    def get(self, id: str, version: int | None = None) -> Any:
        return self.get_definition(id, version=version)

    def types(self, group: str | None = None) -> list[dict[str, Any]]:
        found = list(self._raw.agents.workflows_node_types())
        return [t for t in found if group is None or t.get("group") == group]

    def type(self, id: str) -> dict[str, Any]:
        for item in self.types():
            if item.get("id") == id:
                return item
        raise NotFound(404, "not_found", f"node type {id}")

    def validate(self, definition: Definition) -> WorkflowCheck:
        return WorkflowCheck(self._raw.agents.workflows_validate_definition(definition_body(definition)))

    def plan(self, definition: Definition) -> dict[str, Any]:
        """Validate and show node changes against the stored draft or live version. Writes nothing."""
        parsed = load_definition(definition)
        check = self.validate(definition)
        current = None
        with suppress(NotFound):
            current = self.get_definition(str(parsed["id"]))
        return {"check": check, "current": current, "changes": _diff(parsed, current)}

    def apply(self, definition: Definition) -> Any:
        """Stores the next draft, or returns the existing digest when the definition is unchanged."""
        return self._raw.agents.workflows_create_definition(definition_body(definition))

    def get_definition(self, id: str, version: int | None = None) -> Any:
        return self._raw.agents.workflows_get_definition(id, version=version)

    def export(self, id: str, *, format: str = "json", version: int | None = None) -> str:
        view = self.get_definition(id, version=version)
        return dump_definition(view["definition"], format)

    def publish(self, id: str, *, note: str = "") -> Any:
        return self._raw.agents.workflows_request_definition_publish(id, {"note": note})

    def pause(self, id: str) -> Any:
        return self._raw.agents.workflows_pause_definition(id)

    def resume(self, id: str) -> Any:
        return self._raw.agents.workflows_resume_definition(id)

    def archive(self, id: str) -> Any:
        return self._raw.agents.workflows_archive_definition(id)

    def run(
        self,
        id: str,
        *,
        input: Any = None,
        mode: str = "test",
        wait: bool = False,
        **fields: Any,
    ) -> Any:
        started = self._runs.start(id, input=load_data(input) or {}, mode=mode, **fields)
        return self._runs.wait(started["runId"]) if wait else started

    def schedule(self, id: str, *, input: Any = None, due_at: str | None = None, key: str | None = None) -> Any:
        """Start on the existing work-queue clock. A repeated key is one run."""
        delay = 0.0
        if due_at:
            from datetime import UTC, datetime  # noqa: PLC0415

            due = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            delay = max(0.0, (due - datetime.now(UTC)).total_seconds())
        fields: dict[str, Any] = {"mode": "live", "afterSeconds": delay}
        if key:
            fields["runKey"] = key
        return self._runs.start(id, input=load_data(input) or {}, **fields)

    def send_test_email(self, id: str, event: Any, *, mode: str = "test") -> Any:
        return self._raw.agents.workflows_start_by_hand(
            {"workflowId": id, "mode": mode, "values": load_data(event) or {}}
        )

    def batch(self, id: str, rows: Any, *, mode: str = "test", dry_run: bool = False) -> list[Any]:
        records = _rows(rows)
        if dry_run:
            return records
        return [self.run(id, input=row, mode=mode) for row in records]

    def test(self, source: str | Path, *, case: str | None = None) -> list[dict[str, Any]]:
        """Runs the folder's fixture cases against the definition's id in test mode."""
        folder = as_folder(source) or Path(source).parent
        definition = load_definition(definition_in(folder if as_folder(source) else source))
        workflow_id = str(definition["id"])
        cases = _cases(folder, case)
        results: list[dict[str, Any]] = []
        for item in cases:
            run = self.run(workflow_id, input=item.get("input") or {}, mode="test", wait=True)
            expected = item.get("expected") or {}
            results.append(
                {
                    "name": item["name"],
                    "ok": _outcome_matches(run, expected),
                    "run": run,
                    "expected": expected,
                }
            )
        return results

    def trace(self, run_id: str) -> dict[str, Any]:
        run = self._raw.agents.workflows_get_engine_run(run_id)
        return {
            "run": run,
            "steps": run.get("steps") or [],
            "failure": run.get("failure"),
            "story": run.get("story"),
        }

    def replay(self, run_id: str) -> Any:
        raise NotImplementedError(PLANNED)

    def fork(self, run_id: str, *, from_node: str) -> Any:
        raise NotImplementedError(PLANNED)


class AsyncWorkflows:
    def __init__(self, raw: Any, runs: Any) -> None:
        self._raw = raw
        self._runs = runs

    async def list(self, **query: Any) -> AsyncIterator[Any]:
        nxt: dict[str, Any] = {}
        while True:
            items, nxt_more = page_items(await self._raw.agents.workflows_list_definitions(**{**query, **nxt}))
            for item in items:
                yield item
            if nxt_more is None:
                return
            nxt = nxt_more

    async def get(self, id: str, version: int | None = None) -> Any:
        return await self.get_definition(id, version=version)

    async def types(self, group: str | None = None) -> list[dict[str, Any]]:
        found = list(await self._raw.agents.workflows_node_types())
        return [t for t in found if group is None or t.get("group") == group]

    async def type(self, id: str) -> dict[str, Any]:
        for item in await self.types():
            if item.get("id") == id:
                return item
        raise NotFound(404, "not_found", f"node type {id}")

    async def validate(self, definition: Definition) -> WorkflowCheck:
        return WorkflowCheck(await self._raw.agents.workflows_validate_definition(definition_body(definition)))

    async def plan(self, definition: Definition) -> dict[str, Any]:
        parsed = load_definition(definition)
        check = await self.validate(definition)
        current = None
        with suppress(NotFound):
            current = await self.get_definition(str(parsed["id"]))
        return {"check": check, "current": current, "changes": _diff(parsed, current)}

    async def apply(self, definition: Definition) -> Any:
        return await self._raw.agents.workflows_create_definition(definition_body(definition))

    async def get_definition(self, id: str, version: int | None = None) -> Any:
        return await self._raw.agents.workflows_get_definition(id, version=version)

    async def export(self, id: str, *, format: str = "json", version: int | None = None) -> str:
        view = await self.get_definition(id, version=version)
        return dump_definition(view["definition"], format)

    async def publish(self, id: str, *, note: str = "") -> Any:
        return await self._raw.agents.workflows_request_definition_publish(id, {"note": note})

    async def pause(self, id: str) -> Any:
        return await self._raw.agents.workflows_pause_definition(id)

    async def resume(self, id: str) -> Any:
        return await self._raw.agents.workflows_resume_definition(id)

    async def archive(self, id: str) -> Any:
        return await self._raw.agents.workflows_archive_definition(id)

    async def run(self, id: str, *, input: Any = None, mode: str = "test", wait: bool = False, **fields: Any) -> Any:
        started = await self._runs.start(id, input=load_data(input) or {}, mode=mode, **fields)
        return await self._runs.wait(started["runId"]) if wait else started

    async def send_test_email(self, id: str, event: Any, *, mode: str = "test") -> Any:
        return await self._raw.agents.workflows_start_by_hand(
            {"workflowId": id, "mode": mode, "values": load_data(event) or {}}
        )

    async def batch(self, id: str, rows: Any, *, mode: str = "test", dry_run: bool = False) -> list[Any]:
        records = _rows(rows)
        if dry_run:
            return records
        out: list[Any] = []
        for row in records:
            out.append(await self.run(id, input=row, mode=mode))
        return out

    async def test(self, source: str | Path, *, case: str | None = None) -> list[dict[str, Any]]:
        folder = as_folder(source) or Path(source).parent
        definition = load_definition(definition_in(folder if as_folder(source) else source))
        workflow_id = str(definition["id"])
        results: list[dict[str, Any]] = []
        for item in _cases(folder, case):
            run = await self.run(workflow_id, input=item.get("input") or {}, mode="test", wait=True)
            expected = item.get("expected") or {}
            results.append(
                {"name": item["name"], "ok": _outcome_matches(run, expected), "run": run, "expected": expected}
            )
        return results

    async def trace(self, run_id: str) -> dict[str, Any]:
        run = await self._raw.agents.workflows_get_engine_run(run_id)
        return {"run": run, "steps": run.get("steps") or [], "failure": run.get("failure"), "story": run.get("story")}

    async def replay(self, run_id: str) -> Any:
        raise NotImplementedError(PLANNED)

    async def fork(self, run_id: str, *, from_node: str) -> Any:
        raise NotImplementedError(PLANNED)


def _rows(rows: Any) -> list[dict[str, Any]]:
    data = load_data(rows) if not (isinstance(rows, str) and str(rows).endswith(".csv")) else None
    if isinstance(data, list):
        return [row if isinstance(row, dict) else {"value": row} for row in data]
    path = Path(rows)
    if path.suffix.lower() == ".csv":
        with path.open(newline="") as fh:
            return list(csv.DictReader(fh))
    loaded = load_data(rows)
    if isinstance(loaded, list):
        return [row if isinstance(row, dict) else {"value": row} for row in loaded]
    raise ValueError("batch rows are a CSV or a JSON/YAML list of objects")


def _cases(folder: Path, name: str | None) -> list[dict[str, Any]]:
    evaluation = folder / "evaluation.yaml"
    fixtures = folder / "fixtures"
    cases: list[dict[str, Any]] = []
    if evaluation.is_file():
        data = load_data(evaluation) or {}
        for item in data.get("cases") or []:
            cases.append(item)
    elif fixtures.is_dir():
        for path in sorted(fixtures.glob("*.json")):
            payload = load_data(path)
            expected_path = folder / "expected" / path.name
            cases.append(
                {
                    "name": path.stem,
                    "input": payload,
                    "expected": load_data(expected_path) if expected_path.is_file() else {},
                }
            )
    if name:
        cases = [c for c in cases if c.get("name") == name]
        if not cases:
            raise ValueError(f"no case named {name}")
    return cases


def _outcome_matches(run: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not expected:
        return run.get("status") in {"succeeded", "waiting"}
    return all(run.get(key) == expected[key] for key in ("status", "outcome") if key in expected)


def iter_json(items: Iterator[Any]) -> list[Any]:
    return list(items)
