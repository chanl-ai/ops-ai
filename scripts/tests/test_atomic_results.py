"""ci_usecases.py `run --out`: a reader of the results file never sees it empty or half written."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_usecases


def test_a_reader_never_sees_a_partial_results_file(tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    out.write_text(json.dumps({"results": []}))
    stop = threading.Event()
    errors: list[str] = []

    def read() -> None:
        while not stop.is_set():
            try:
                json.loads(out.read_text())
            except json.JSONDecodeError as e:
                errors.append(str(e))

    reader = threading.Thread(target=read)
    reader.start()
    try:
        done: list[dict[str, Any]] = []
        for i in range(200):
            done.append({"id": f"uc-{i}", "code": 0, "seconds": 0, "log": "x" * 2000})
            ci_usecases.write_results(str(out), done)
    finally:
        stop.set()
        reader.join()
    assert errors == []
    assert len(json.loads(out.read_text())["results"]) == 200
    assert [p.name for p in tmp_path.iterdir()] == ["r.json"]
