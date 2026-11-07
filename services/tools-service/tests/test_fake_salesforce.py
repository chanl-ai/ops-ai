"""The fake Salesforce's advisor org, on its app in process: the OAuth server's token check is replaced by a signer
named in each request's headers, so the routes, the SOQL evaluator and the writes run as they do behind a real
sign-in. One test per way the fake could mislead a use case: a query answering the wrong records, a write recorded
under the wrong person or not refused, a composite half applied, and the existing case paths no longer answering as
the Salesforce plugin's use cases expect."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

LIB = Path(__file__).resolve().parents[3] / "docs" / "usecases" / "lib"
DANA = {"x-subject": "dana.whitfield", "x-scopes": "openid api refresh_token"}


def fake_salesforce() -> ModuleType:
    """The fake's module, loaded fresh so each test starts on the seeded org; it imports its siblings in the folder."""
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location("fake_salesforce_under_test", LIB / "fake_salesforce.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Rig:
    sf: Any  # the module, for its ids and constants
    fake: Any
    client: TestClient

    def query(self, q: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        r = self.client.get(f"{self.sf.API}/query", params={"q": q}, headers=headers or DANA)
        assert r.status_code == 200, r.text
        return r.json()

    def ids(self, q: str, headers: dict[str, str] | None = None) -> list[str]:
        return [row["Id"] for row in self.query(q, headers)["records"]]


@pytest.fixture
def rig() -> Iterator[Rig]:
    sf = fake_salesforce()
    # Nothing listens here; the token check that would fetch its keys is replaced below.
    fake = sf.Salesforce("http://127.0.0.1:9")

    def signer(request: Any, host: str) -> tuple[str, set[str]]:
        return str(request.headers.get("x-subject", "")), set(str(request.headers.get("x-scopes", "")).split())

    fake._signer = signer
    with TestClient(fake.app(), base_url=f"https://{sf.API_HOST}") as client:
        yield Rig(sf, fake, client)


def test_using_scope_mine_hides_another_advisors_event(rig: Rig) -> None:
    sf = rig.sf
    everyone = rig.ids("SELECT Id FROM Event WHERE StartDateTime = TODAY")
    mine = rig.ids("SELECT Id, Subject FROM Event USING SCOPE mine WHERE StartDateTime = TODAY ORDER BY StartDateTime")
    assert sf.PRIYA_EVENT_ID in everyone
    assert mine == [sf.REVIEW_EVENT_ID, sf.CHECKIN_EVENT_ID]


def test_today_and_last_n_days_compare_by_local_day(rig: Rig) -> None:
    sf = rig.sf
    # The review is a datetime at 14:00 local; TODAY is the whole local day, and YESTERDAY holds none of it.
    assert sf.REVIEW_EVENT_ID in rig.ids("SELECT Id FROM Event WHERE StartDateTime = TODAY")
    assert rig.ids("SELECT Id FROM Event WHERE StartDateTime = YESTERDAY") == []
    # The call was 17 days ago: inside the last 20 days, outside the last 10.
    assert sf.CALL_TASK_ID in rig.ids("SELECT Id FROM Task WHERE ActivityDate = LAST_N_DAYS:20")
    assert sf.CALL_TASK_ID not in rig.ids("SELECT Id FROM Task WHERE ActivityDate = LAST_N_DAYS:10")
    # The education opportunity last changed 21 days ago.
    assert rig.ids("SELECT Id FROM Opportunity WHERE LastModifiedDate < LAST_N_DAYS:14 AND IsClosed = false") == [
        sf.EDUCATION_ID
    ]


def test_relationship_fields_come_back_nested(rig: Rig) -> None:
    sf = rig.sf
    q = "SELECT Subject, Owner.Name, Who.Name, What.Name FROM Event WHERE Id IN ('{}', '{}') ORDER BY StartDateTime"
    rows = rig.query(q.format(sf.REVIEW_EVENT_ID, sf.PRIYA_EVENT_ID))["records"]
    priya, review = rows
    assert review["Owner"] == {
        "attributes": {"type": "User", "url": f"{sf.API}/sobjects/User/{sf.DANA_ID}"},
        "Name": "Dana Whitfield",
    }
    assert (review["Who"]["attributes"]["type"], review["Who"]["Name"]) == ("Contact", "Grace Okafor")
    assert (review["What"]["attributes"]["type"], review["What"]["Name"]) == ("Account", "Okafor Family Trust")
    assert "Owner.Name" not in review
    assert (priya["Owner"]["Name"], priya["Who"], priya["What"]) == ("Priya Raman", None, None)


def test_like_matches_whatever_the_case(rig: Rig) -> None:
    assert rig.ids("SELECT Id FROM Account WHERE Name LIKE '%okafor%'") == [rig.sf.OKAFOR_ID]
    assert rig.ids("SELECT Id FROM Contact WHERE Email LIKE 'GRACE%'") == [rig.sf.GRACE_ID]


def test_an_unparsed_condition_is_noted_and_does_not_refuse_the_query(rig: Rig) -> None:
    q = "SELECT Id FROM Account WHERE Type = 'Household' AND Industry INCLUDES ('Wealth')"
    assert rig.ids(q) == [rig.sf.OKAFOR_ID]
    assert rig.fake.unparsed == ["Industry INCLUDES ( 'Wealth' )"]
    assert q in rig.fake.queries


def test_a_create_and_an_update_are_recorded_with_the_signer(rig: Rig) -> None:
    sf, client = rig.sf, rig.client
    task = {"Subject": "Annual review notes", "Status": "Completed", "WhatId": sf.OKAFOR_ID, "WhoId": sf.GRACE_ID}
    made = client.post(f"{sf.API}/sobjects/Task", json=task, headers=DANA)
    assert made.status_code == 201, made.text
    tid = made.json()["id"]
    changed = client.patch(
        f"{sf.API}/sobjects/Opportunity/{sf.EDUCATION_ID}", json={"StageName": "Proposal"}, headers=DANA
    )
    assert changed.status_code == 204, changed.text
    assert [(e["by"], e["object"], e["op"], e["id"]) for e in rig.fake.edits] == [
        ("dana.whitfield", "Task", "create", tid),
        ("dana.whitfield", "Opportunity", "update", sf.EDUCATION_ID),
    ]
    stored = client.get(f"{sf.API}/sobjects/Task/{tid}", headers=DANA).json()
    assert (stored["OwnerId"], stored["CreatedById"], stored["IsClosed"]) == (sf.DANA_ID, sf.DANA_ID, True)
    opportunity = rig.fake.records["Opportunity"][sf.EDUCATION_ID]
    assert (opportunity["StageName"], opportunity["LastModifiedById"]) == ("Proposal", sf.DANA_ID)


def test_a_write_without_the_api_scope_is_refused(rig: Rig) -> None:
    # The plugin signs in with openid, api and refresh_token; a token holding only openid reads who signed in.
    sf = rig.sf
    reader = {"x-subject": "dana.whitfield", "x-scopes": "openid"}
    r = rig.client.post(f"{sf.API}/sobjects/Task", json={"Subject": "Call back"}, headers=reader)
    assert r.status_code == 403
    assert rig.fake.edits == []
    assert rig.fake.refused == ["insufficient_scope:dana.whitfield"]


def test_a_value_outside_a_restricted_picklist_is_refused(rig: Rig) -> None:
    sf = rig.sf
    url = f"{sf.API}/sobjects/Opportunity/{sf.EDUCATION_ID}"
    r = rig.client.patch(url, json={"StageName": "Won"}, headers=DANA)
    assert r.status_code == 400
    assert [(e["errorCode"], e["fields"]) for e in r.json()] == [
        ("INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST", ["StageName"])
    ]
    assert rig.fake.records["Opportunity"][sf.EDUCATION_ID]["StageName"] == "Needs Analysis"
    assert rig.fake.edits == []


def test_a_create_missing_a_required_field_is_refused(rig: Rig) -> None:
    sf = rig.sf
    r = rig.client.post(f"{sf.API}/sobjects/Opportunity", json={"Name": "Trust review fee"}, headers=DANA)
    assert r.status_code == 400
    assert [(e["errorCode"], e["fields"]) for e in r.json()] == [("REQUIRED_FIELD_MISSING", ["StageName", "CloseDate"])]
    assert rig.fake.edits == []


def composite(rig: Rig, *subrequests: dict[str, Any]) -> list[dict[str, Any]]:
    body = {"allOrNone": True, "compositeRequest": list(subrequests)}
    r = rig.client.post(f"{rig.sf.API}/composite", json=body, headers=DANA)
    assert r.status_code == 200, r.text
    return r.json()["compositeResponse"]


def test_composite_applies_in_order_and_resolves_references(rig: Rig) -> None:
    sf = rig.sf
    opportunity = {"Name": "Two education plans", "AccountId": sf.OKAFOR_ID, "StageName": "Proposal",
                   "CloseDate": "2027-01-15"}  # fmt: skip
    answers = composite(
        rig,
        {"method": "POST", "url": "/services/data/v61.0/sobjects/Opportunity", "referenceId": "plan",
         "body": opportunity},
        {"method": "POST", "url": "/services/data/v61.0/sobjects/Task", "referenceId": "next",
         "body": {"Subject": "Send the plan to Grace", "WhatId": "@{plan.id}", "WhoId": sf.GRACE_ID}},
    )  # fmt: skip
    assert [a["httpStatusCode"] for a in answers] == [201, 201]
    plan, task = answers[0]["body"]["id"], answers[1]["body"]["id"]
    assert rig.fake.records["Task"][task]["WhatId"] == plan
    assert [(e["object"], e["id"]) for e in rig.fake.edits] == [("Opportunity", plan), ("Task", task)]


def test_composite_applies_nothing_when_one_subrequest_fails(rig: Rig) -> None:
    sf = rig.sf
    tasks = len(rig.fake.records["Task"])
    answers = composite(
        rig,
        {"method": "POST", "url": "/services/data/v61.0/sobjects/Task", "referenceId": "note",
         "body": {"Subject": "Review held", "WhatId": sf.OKAFOR_ID}},
        {"method": "PATCH", "url": f"/services/data/v61.0/sobjects/Opportunity/{sf.EDUCATION_ID}",
         "referenceId": "stage", "body": {"StageName": "Won"}},
    )  # fmt: skip
    assert [(a["referenceId"], a["httpStatusCode"], a["body"][0]["errorCode"]) for a in answers] == [
        ("note", 400, "PROCESSING_HALTED"),
        ("stage", 400, "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST"),
    ]
    assert len(rig.fake.records["Task"]) == tasks
    assert rig.fake.edits == []


def test_search_finds_the_new_clients_by_name(rig: Rig) -> None:
    sf = rig.sf
    q = "FIND {okafor} IN NAME FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email)"
    r = rig.client.get(f"{sf.API}/search", params={"q": q}, headers=DANA)
    found = {(row["attributes"]["type"], row["Id"]) for row in r.json()["searchRecords"]}
    assert {("Account", sf.OKAFOR_ID), ("Contact", sf.GRACE_ID)} <= found
    assert ("Account", sf.LINDQVIST_ID) not in found


def test_a_case_query_on_a_new_account_reaches_the_org(rig: Rig) -> None:
    sf = rig.sf
    q = f"SELECT Id, Subject FROM Case WHERE AccountId = '{sf.OKAFOR_ID}' AND IsClosed = false"
    assert rig.ids(q) == [sf.BENEFICIARY_CASE_ID]


def test_the_existing_case_paths_answer_as_before(rig: Rig) -> None:
    sf, client = rig.sf, rig.client
    by_number = rig.query("SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'")["records"]
    assert [c["Id"] for c in by_number] == [sf.PLUGIN_CASE_ID]
    assert rig.ids("SELECT Id, CaseNumber FROM Case WHERE CaseNumber = '00044817'") == [sf.CASE_ID]
    escalated = rig.query(
        "SELECT Id, CaseNumber, Subject, Status, AccountId, LastModifiedDate FROM Case "
        "WHERE Status = 'Escalated' AND LastModifiedDate > 1970-01-01T00:00:00Z ORDER BY LastModifiedDate, Id"
    )
    assert (escalated["totalSize"], len(escalated["records"]), "nextRecordsUrl" in escalated) == (3, 2, True)
    described = client.get(f"{sf.API}/sobjects/Case/describe", headers=DANA).json()
    assert described == {"name": "Case", "fields": [{"name": f} for f in ("Id", "CaseNumber", "Status", "Subject")]}
    sosl = (
        "FIND {Acme} IN ALL FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email), Case(Id, CaseNumber, Subject)"
    )
    found = client.get(f"{sf.API}/search", params={"q": sosl}, headers=DANA).json()["searchRecords"]
    assert sorted({r["attributes"]["type"] for r in found}) == ["Account", "Case", "Contact"]
    assert {r["Id"] for r in found if r["attributes"]["type"] != "Case"} == {sf.ACCOUNT_ID, sf.CONTACT["Id"]}
    refused = client.patch(
        f"{sf.API}/sobjects/Case/{sf.CASE_ID}", json={"Status": "Closed"}, headers={"x-subject": "a"}
    )
    assert refused.status_code == 403
    edited = client.patch(f"{sf.API}/sobjects/Case/{sf.PLUGIN_CASE_ID}", json={"Status": "Working"}, headers=DANA)
    assert edited.status_code == 204
    assert rig.fake.edits == [{"by": "dana.whitfield", "change": {"Status": "Working"}, "id": sf.PLUGIN_CASE_ID}]
