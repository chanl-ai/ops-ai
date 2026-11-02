"""A run is given a saved tool, not a snippet written in the test: a file on disk, or one function's source."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any

from ops_runner.domain import Limits
from ops_runner.wasm import WasmPython

ROOT = Path(__file__).resolve().parents[3]
LEVY = ROOT / "scripts" / "sample-team" / "code" / "compute_levy_hold.py"
SETTLE = Path(__file__).resolve().parent / "fixtures" / "notice_hold.py"

RULES = {"protectedBalance": 2000, "currency": "CAD", "exemptAccountTypes": ["chequing"]}


def definition(path: Path, name: str) -> str:
    """The function as text, annotations postponed so the guest does not need the typing names."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return "from __future__ import annotations\n" + inspect.getsource(getattr(module, name))


def test_the_levy_file_holds_what_the_rules_leave_available(runtime: WasmPython) -> None:
    """scripts/sample-team/code/compute_levy_hold.py, the tool a builder saved, run as that file."""
    calls: list[dict[str, Any]] = []

    def rules(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append({"tool": tool, "args": args})
        if tool != "get_levy_rules":
            return {"ok": False, "error": {"code": "binding_forbidden", "message": tool}}
        return {"ok": True, "output": RULES}

    notice = {
        "document": {"name": "A. Cole", "amount": 3000, "case_no": "L-19"},
        "accounts": [
            {"id": "sav", "type": "savings", "balance": 500, "status": "open"},
            {"id": "chq", "type": "chequing", "balance": 8000, "status": "open"},
            {"id": "old", "type": "chequing", "balance": 9000, "status": "closed"},
        ],
    }
    r = runtime.run(LEVY.read_text(), "main", notice, Limits(time_s=5), rules)
    assert r.ok and r.output == {
        "holdAmount": 3000.0,
        "accountId": "chq",
        "reason": "Chequing account chq keeps its first 2,000.00 CAD exempt; holds 3,000.00.",
    }
    assert calls == [{"tool": "get_levy_rules", "args": {"rulesKey": {"$secret": "BANK_API_KEY"}}}]

    nowhere = {
        "document": {"amount": 500},
        "accounts": [{"id": "old", "type": "savings", "status": "closed", "balance": 50}],
    }
    empty = runtime.run(LEVY.read_text(), "main", nowhere, Limits(time_s=5), rules)
    assert empty.ok and empty.output == {
        "holdAmount": 0,
        "accountId": None,
        "reason": "The customer has no open account to hold funds in.",
    }

    short = {
        "document": {"amount": 250},
        "accounts": [{"id": "sav", "type": "savings", "balance": 100, "status": "open"}],
    }
    partial = runtime.run(LEVY.read_text(), "main", short, Limits(time_s=5), rules)
    assert partial.ok and partial.output == {
        "holdAmount": 100.0,
        "accountId": "sav",
        "reason": "Savings account sav is not exempt; holds all 100.00 available.",
    }


def test_a_function_definition_settles_each_payment_on_its_own(runtime: WasmPython) -> None:
    """settle from tests/fixtures/notice_hold.py, sent as that function's source, entry name and all."""
    source = definition(SETTLE, "settle")
    assert source.lstrip().startswith("from __future__ import annotations")
    assert "def settle(" in source and "def main(" not in source
    accounts = {
        "a-open": {"balance": 40, "status": "open"},
        "a-closed": {"balance": 100, "status": "closed"},
    }
    seen: list[dict[str, Any]] = []

    def bank(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        seen.append({"tool": tool, "args": args})
        account_id = str(args.get("accountId"))
        if account_id not in accounts:
            return {"ok": False, "error": {"code": "not_found", "message": f"No account {account_id}."}}
        return {"ok": True, "output": accounts[account_id]}

    payments = [
        {"id": "p1", "accountId": "a-open", "amount": 25},
        {"id": "p2", "accountId": "a-closed", "amount": 10},
        {"id": "p3", "accountId": "a-missing", "amount": 5},
        {"id": "p4", "accountId": "a-open", "amount": 30},
    ]
    r = runtime.run(source, "settle", {"payments": payments}, Limits(time_s=5), bank)
    assert r.ok, r.error
    assert r.output == {
        "taken": 55.0,
        "lines": [
            {"id": "p1", "taken": 25.0, "short": 0.0},
            {"id": "p2", "taken": 0.0, "short": 10.0},
            {"id": "p4", "taken": 30.0, "short": 0.0},
        ],
        "refused": [{"id": "p3", "code": "not_found"}],
    }
    assert "settled 3 refused 1" in r.log
    assert [call["args"]["key"] for call in seen] == [{"$secret": "BANK_API_KEY"}] * 4
    assert [call["tool"] for call in seen] == ["get_account"] * 4
