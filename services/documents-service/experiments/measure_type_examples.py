"""Field accuracy of restraining notices read before and after corrections teach their type, on the shared stack with
the real extract alias (c-297).

    uv run python experiments/measure_type_examples.py

Two teacher notices and two measured notices are read with no examples. Every wrong field on the teachers is corrected
to its expected value, which keeps an example each; the measured notices are never corrected, so what they gain on
their second read comes from the teachers' corrections only. The measured notices are then read again. The examples
the run taught are removed at the end, so the type reads as it did before. A guard stops before any read that could take
the run past 10 provider calls. Prints one JSON object per read and a summary; the 2026-10-19 run's output is
measure_type_examples_results.jsonl."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from measure_page_images import DOCS, FILES, person, scored, seeded, sent, upload  # noqa: E402

CAP = 10
PER_READ = 2
TYPE = "restraining_notice"
TEACHERS = ["TEST001_scan.pdf", "VAR01.pdf"]
MEASURED = ["TEST003_scan.pdf", "VAR02.pdf"]


def main() -> None:
    _, folder = seeded()[TYPE]
    expected_of = {name: row["expected"] for name, row in json.loads((folder / "expected.json").read_text()).items()}
    builder, files = person("j.richardson@harborpine.example", DOCS), person("j.richardson@harborpine.example", FILES)
    found = builder.get(f"/v1/document-types/{TYPE}").json()["data"]
    version = next(v for v in found["versions"] if v["version"] == found["latestVersion"])
    before_ids = {e["id"] for e in builder.get(f"/v1/document-types/{TYPE}/examples").json()["data"]}
    runs: list[str] = []
    rows: list[dict[str, Any]] = []

    def read(name: str, phase: str) -> dict[str, Any] | None:
        used = asyncio.run(sent(runs))[0] if runs else 0
        if used + PER_READ > CAP:
            print(json.dumps({"stopped": f"{name} {phase}: {used} calls used, a read may take {PER_READ}"}))
            return None
        body = {"fileId": upload(files, folder / name), "documentTypeId": TYPE, "ocr": True}
        started = time.monotonic()
        got = builder.post("/v1/documents/extractions", json=body).json()["data"]
        seconds = round(time.monotonic() - started, 2)
        runs.append(got["id"])
        calls, cost, _ = asyncio.run(sent([got["id"]]))
        expected = expected_of[name]
        wrong = scored(version["fields"], version.get("dateOrder"), expected, got)
        row = {
            "file": name, "phase": phase, "path": got.get("path"), "right": len(expected) - len(wrong),
            "total": len(expected), "wrong": wrong, "calls": calls, "cost": round(cost, 6), "seconds": seconds,
            "extraction": got["id"],
        }  # fmt: skip
        rows.append(row)
        print(json.dumps(row), flush=True)
        return row

    taught: list[str] = []
    try:
        for name in TEACHERS:
            row = read(name, "teacher")
            if row is None:
                continue
            for key in cast(list[str], row["wrong"]):
                r = builder.patch(
                    f"/v1/documents/extractions/{row['extraction']}/fields/{key}",
                    json={"value": expected_of[name][key]},
                )
                print(json.dumps({"corrected": f"{name} {key}", "status": r.status_code}), flush=True)
        for name in MEASURED:
            read(name, "before")
        now = builder.get(f"/v1/document-types/{TYPE}/examples").json()["data"]
        taught = [e["id"] for e in now if e["id"] not in before_ids]
        print(json.dumps({"examples": len(taught), "fields": sorted({e["field"] for e in now})}), flush=True)
        for name in MEASURED:
            read(name, "after")
    finally:
        for example in taught:
            builder.delete(f"/v1/document-types/{TYPE}/examples/{example}").raise_for_status()
    calls, cost, _ = asyncio.run(sent(runs))
    summary: dict[str, Any] = {"calls": calls, "cost": round(cost, 6), "examples": len(taught), "removed": len(taught)}
    for phase in ("before", "after"):
        of = [r for r in rows if r["phase"] == phase]
        summary[phase] = f"{sum(r['right'] for r in of)}/{sum(r['total'] for r in of)}"
    print(json.dumps({"summary": summary}))


if __name__ == "__main__":
    main()
