"""The fake bank's levy operations (c-057 T003), on its app in process: a person found by address or last-four SSN,
an SSN fragment that is not the whole last four finding nobody, a note landing on the customer, and a hold over the
available balance refused with 422."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1] / "scripts" / "fake_bank" / "app.py"
KEY = {"X-Api-Key": "dev-bank-key"}


def fake_bank() -> ModuleType:
    """The fake's module, loaded fresh from the scripts folder so each test starts with the seeded state."""
    spec = importlib.util.spec_from_file_location("fake_bank_app", APP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def client() -> TestClient:
    return TestClient(fake_bank().app)


def test_customers_are_found_by_name_address_or_the_whole_last_four() -> None:
    bank = client()
    by = {
        "bell": ["CUS-1001"],
        "lakeshore": ["CUS-1002"],
        "4471": ["CUS-1001"],
        "9032": ["CUS-1002"],
        "44": [],  # an SSN fragment is matched whole or not at all
        "whitfield": ["CUS-1003"],
        "5555": ["CUS-1003"],
        "   ": [],  # stripped before the length check
        " 12 ": [],  # a street number is not an address match
        "harbour street": ["CUS-1001"],
    }
    for query, expected in by.items():
        r = bank.get("/customers", params={"query": query}, headers=KEY)
        assert r.status_code == 200, r.text
        assert [c["id"] for c in r.json()] == expected, query
    assert bank.get("/customers", params={"query": "bell"}).status_code == 401


def test_a_note_is_written_on_the_customer_and_read_back() -> None:
    bank = client()
    r = bank.post("/customers/CUS-1002/notes", json={"text": "Levy notice: no hold", "author": "m.okafor"}, headers=KEY)
    assert r.status_code == 201, r.text
    note = r.json()
    assert (note["customerId"], note["text"]) == ("CUS-1002", "Levy notice: no hold")
    assert [n["id"] for n in bank.get("/customers/CUS-1002/notes", headers=KEY).json()] == [note["id"]]
    assert bank.post("/customers/CUS-9999/notes", json={"text": "x"}, headers=KEY).status_code == 404


def test_a_hold_over_the_available_balance_is_refused() -> None:
    bank = client()
    ok = bank.post("/accounts/CHQ-2219/holds", json={"amount": 2000, "reason": "levy"}, headers=KEY)
    assert ok.status_code == 201, ok.text
    # 2140.55 on the account, 2000 held: 150 more exceeds what is available.
    over = bank.post("/accounts/CHQ-2219/holds", json={"amount": 150, "reason": "levy"}, headers=KEY)
    assert over.status_code == 422 and "available balance" in over.json()["detail"]
    assert len(bank.get("/accounts/CHQ-2219", headers=KEY).json()["holds"]) == 1


def test_the_document_names_the_levy_operations() -> None:
    ops = {o["operationId"] for p in client().get("/openapi.json").json()["paths"].values() for o in p.values()}
    assert {"search_customers", "add_customer_note", "place_hold"} <= ops


def test_the_document_declares_the_shapes_chat_draws() -> None:
    paths = client().get("/openapi.json").json()["paths"]
    shapes = {
        o["operationId"]: next(r for code, r in o["responses"].items() if code.startswith("2")).get("x-ops-shape")
        for p in paths.values()
        for o in p.values()
    }
    assert shapes["get_customer"] == "record" and shapes["list_accounts"] == "rows"
    assert shapes["list_transactions"] == "rows" and shapes["place_hold"] is None


def test_a_customers_accounts_list_as_rows() -> None:
    bank = client()
    rows = bank.get("/customers/CUS-1001/accounts", headers=KEY).json()
    assert [(r["id"], r["balance"]) for r in rows] == [("CHQ-2219", 2140.55), ("SAV-4410", 18250.0)]
    assert bank.get("/customers/CUS-9999/accounts", headers=KEY).status_code == 404


def test_the_statement_takes_its_key_in_the_query_and_repeats_its_url() -> None:
    bank = client()
    assert bank.get("/accounts/CHQ-2219/statement").status_code == 401
    assert bank.get("/accounts/CHQ-2219/statement", headers=KEY).status_code == 401, "the header key is not this one"
    got = bank.get("/accounts/CHQ-2219/statement", params={"api_key": "dev-bank-key"}).json()
    assert got["period"] == "2026-09" and "api_key=dev-bank-key" in got["requestedUrl"]
