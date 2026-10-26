"""A stand-in core-banking API for walking the bank use case on a dev stack: a real HTTP upstream with an OpenAPI
document the tools service imports, an API key it checks, and writes that change what later reads return.

Run it with `python -m fake_bank` (see __main__.py): https as api.bank.test on this machine's private address, which
is how tools-service's egress rules let it reach anything. The key is FAKE_BANK_KEY (default dev-bank-key)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from pydantic import BaseModel, Field

# Loaded by path as well as as a package (tests/test_fake_bank.py, python -m fake_bank), so the sibling is found by its
# folder rather than by a relative import.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bank_auth import router as auth_router  # pyright: ignore[reportMissingImports, reportUnknownVariableType]

KEY = os.environ.get("FAKE_BANK_KEY", "dev-bank-key")

# The address the OpenAPI document gives, which an import makes the module's endpoint: api.bank.test on a dev stack,
# the stand-in's public https address where it runs as a staging app (deploy/fly/staging/bank.toml).
PUBLIC_URL = os.environ.get("FAKE_BANK_PUBLIC_URL", "https://api.bank.test")
app = FastAPI(title="Harbor & Pine Core Banking", version="1.0.0", servers=[{"url": PUBLIC_URL}])
# The bank's sign-in and the routes protected each way a connection signs in (c-330); kept out of the OpenAPI document.
app.include_router(auth_router)  # pyright: ignore[reportUnknownArgumentType]


# Declared as a security scheme so the OpenAPI document names it, as a real bank's would; the importer turns the
# scheme name into the secret the header reads (bank_api_key -> {{BANK_API_KEY}}).
KEY_HEADER = APIKeyHeader(name="X-Api-Key", scheme_name="bank_api_key", auto_error=False)


def api_key(x_api_key: Annotated[str | None, Security(KEY_HEADER)] = None) -> None:
    if x_api_key != KEY:
        raise HTTPException(401, "missing or wrong X-Api-Key")


# The statements service is an older system that takes its key in the query, as some bank partners still do; the
# importer turns the scheme into a `?api_key={{STATEMENTS_API_KEY}}` reference resolved at call time.
KEY_QUERY = APIKeyQuery(name="api_key", scheme_name="statements_api_key", auto_error=False)


def query_key(api_key: Annotated[str | None, Security(KEY_QUERY)] = None) -> None:
    if api_key != KEY:
        raise HTTPException(401, "missing or wrong api_key")


# An outside system's webhook receiver (the levy demo): it checks a shared secret header, as many webhook senders sign
# their calls, and the importer turns the scheme into {{LEVY_WEBHOOK_SECRET}}, a secret resolved at call time.
WEBHOOK_SECRET = os.environ.get("FAKE_BANK_WEBHOOK_SECRET", "dev-webhook-secret")
WEBHOOK_HEADER = APIKeyHeader(name="X-Webhook-Secret", scheme_name="levy_webhook_secret", auto_error=False)


def webhook_secret(x_webhook_secret: Annotated[str | None, Security(WEBHOOK_HEADER)] = None) -> None:
    if x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(401, "missing or wrong X-Webhook-Secret")


class Customer(BaseModel):
    id: str
    name: str
    email: str
    segment: str
    address: str
    ssnLast4: str  # noqa: N815 - the bank API's field name; only the last four digits are ever served
    accountIds: list[str]  # noqa: N815 - the bank API's field name


class Hold(BaseModel):
    id: str
    amount: float
    reason: str


class Account(BaseModel):
    id: str
    customerId: str  # noqa: N815 - the bank API's field name
    type: str
    currency: str
    balance: float
    status: str
    holds: list[Hold] = Field(default_factory=list[Hold])


class Transaction(BaseModel):
    id: str
    accountId: str  # noqa: N815 - the bank API's field name
    date: date
    description: str
    amount: float


class HoldIn(BaseModel):
    amount: float = Field(gt=0)
    reason: str


class NoteIn(BaseModel):
    text: str = Field(min_length=1)
    author: str = ""


class Note(BaseModel):
    id: str
    customerId: str  # noqa: N815 - the bank API's field name
    text: str
    author: str


class DisputeIn(BaseModel):
    accountId: str  # noqa: N815 - the bank API's field name
    transactionId: str  # noqa: N815 - the bank API's field name
    reason: str


class Dispute(BaseModel):
    id: str
    accountId: str  # noqa: N815 - the bank API's field name
    transactionId: str  # noqa: N815 - the bank API's field name
    reason: str
    status: str


CUSTOMERS = {
    "CUS-1001": Customer(
        id="CUS-1001",
        name="Marcus Bell",
        email="marcus.bell@example.com",
        segment="retail",
        address="12 Harbour Street, Halifax NS B3J 1A1",
        ssnLast4="4471",
        # The card goes last: the levy story holds on the first account listed (levy_case `hold`).
        accountIds=["CHQ-2219", "SAV-4410", "VISA-5521"],
    ),
    "CUS-1002": Customer(
        id="CUS-1002",
        name="Priya Natarajan",
        email="priya.n@example.com",
        segment="small business",
        address="88 Lakeshore Road, Toronto ON M8V 1A5",
        ssnLast4="9032",
        accountIds=["BUS-7781"],
    ),
}
CUSTOMERS["CUS-1003"] = Customer(
    # Same name as a person a levy notice may name, at another address with another SSN: a candidate, never a match.
    id="CUS-1003",
    name="Jordan Whitfield",
    email="j.whitfield@example.com",
    segment="retail",
    address="9 Elm Crescent, Brandon MB R7A 0K2",
    ssnLast4="5555",
    accountIds=["CHQ-1003"],
)
ACCOUNTS = {
    "CHQ-2219": Account(
        id="CHQ-2219", customerId="CUS-1001", type="chequing", currency="CAD", balance=2140.55, status="open"
    ),
    "SAV-4410": Account(
        id="SAV-4410", customerId="CUS-1001", type="savings", currency="CAD", balance=18250.00, status="open"
    ),
    # A credit card's balance is what the cardholder owes, so nothing on it can be held.
    "VISA-5521": Account(
        id="VISA-5521", customerId="CUS-1001", type="credit card", currency="CAD", balance=-1612.40, status="open"
    ),
    "CHQ-1003": Account(
        id="CHQ-1003", customerId="CUS-1003", type="chequing", currency="CAD", balance=640.10, status="open"
    ),
    "BUS-7781": Account(
        id="BUS-7781", customerId="CUS-1002", type="business chequing", currency="CAD", balance=48210.90, status="open"
    ),
}
TRANSACTIONS = [
    Transaction(
        id="TXN-9001", accountId="CHQ-2219", date=date(2026, 10, 9), description="Payroll deposit", amount=2850.00
    ),
    Transaction(id="TXN-9002", accountId="CHQ-2219", date=date(2026, 10, 10), description="Grocer 418", amount=-86.12),
    Transaction(
        id="TXN-9003",
        accountId="CHQ-2219",
        date=date(2026, 10, 11),
        description="ONLINE ELECTRONICS INTL",
        amount=-1299.99,
    ),
    Transaction(
        id="TXN-9004", accountId="CHQ-2219", date=date(2026, 10, 12), description="Transit pass", amount=-156.00
    ),
    Transaction(
        id="TXN-9101", accountId="BUS-7781", date=date(2026, 10, 12), description="Supplier payment", amount=-4200.00
    ),
    # The charges scripts/demo/team.json's dispute runs and chats name, so an agent asked about one finds it.
    Transaction(
        id="TXN-9201", accountId="VISA-5521", date=date(2026, 10, 16), description="COASTAL AIR", amount=-1240.00
    ),
    Transaction(
        id="TXN-9202",
        accountId="CHQ-1003",
        date=date(2026, 10, 11),
        description="NORTHLINE ELECTRONICS",
        amount=-482.10,
    ),
    Transaction(
        id="TXN-9203", accountId="BUS-7781", date=date(2026, 9, 3), description="LAKESHORE STREAMING", amount=-64.99
    ),
    Transaction(
        id="TXN-9204", accountId="BUS-7781", date=date(2026, 10, 3), description="LAKESHORE STREAMING", amount=-64.99
    ),
]
DISPUTES: dict[str, Dispute] = {}
NOTES: dict[str, list[Note]] = {}


@app.get(
    "/customers",
    operation_id="search_customers",
    summary="Find customers by name, email, address or the last four digits of their SSN",
    dependencies=[Depends(api_key)],
)
def search_customers(query: Annotated[str, Query()]) -> list[Customer]:
    """Name and email match as a case-insensitive substring of at least two characters; an address needs six, so a
    street number alone finds nobody; an SSN fragment matches only as the whole last four. The query is stripped
    before any length check, so blanks find nobody."""
    q = query.strip().lower()
    if len(q) < 2:
        return []
    return [
        c
        for c in CUSTOMERS.values()
        if q in c.name.lower() or q in c.email.lower() or (len(q) >= 6 and q in c.address.lower()) or q == c.ssnLast4
    ]


@app.post(
    "/customers/{customer_id}/notes",
    operation_id="add_customer_note",
    summary="Write a note on a customer's record",
    status_code=201,
    dependencies=[Depends(api_key)],
)
def add_customer_note(customer_id: str, body: NoteIn) -> Note:
    if customer_id not in CUSTOMERS:
        raise HTTPException(404, "no such customer")
    note = Note(id=f"NOTE-{uuid.uuid4().hex[:6]}", customerId=customer_id, text=body.text, author=body.author)
    NOTES.setdefault(customer_id, []).append(note)
    return note


@app.get(
    "/customers/{customer_id}/notes",
    operation_id="list_customer_notes",
    summary="Notes on a customer's record",
    dependencies=[Depends(api_key)],
)
def list_customer_notes(customer_id: str) -> list[Note]:
    if customer_id not in CUSTOMERS:
        raise HTTPException(404, "no such customer")
    return NOTES.get(customer_id, [])


# `x-ops-shape` on a success response tells the tools service's importer how a result draws in chat (record, rows).
RECORD: dict[int | str, dict[str, Any]] = {200: {"description": "One record", "x-ops-shape": "record"}}
ROWS: dict[int | str, dict[str, Any]] = {200: {"description": "Rows", "x-ops-shape": "rows"}}


# A model given only a name otherwise invents an id and calls this again and again (customer_summary, 2026-10-18).
GET_CUSTOMER = "One customer and their account ids, by the customer's CUS- id; find the id with search_customers first"
CUSTOMER_ID = "The customer's id, such as CUS-1002, as search_customers returns it; never a name"


@app.get(
    "/customers/{customer_id}",
    operation_id="get_customer",
    summary=GET_CUSTOMER,
    dependencies=[Depends(api_key)],
    responses=RECORD,
)
def get_customer(customer_id: Annotated[str, PathParam(description=CUSTOMER_ID)]) -> Customer:
    if customer_id not in CUSTOMERS:
        raise HTTPException(404, "no such customer")
    return CUSTOMERS[customer_id]


@app.get(
    "/customers/{customer_id}/accounts",
    operation_id="list_accounts",
    summary="A customer's accounts with balances, statuses and holds",
    dependencies=[Depends(api_key)],
    responses=ROWS,
)
def list_accounts(customer_id: str) -> list[Account]:
    if customer_id not in CUSTOMERS:
        raise HTTPException(404, "no such customer")
    return [ACCOUNTS[a] for a in CUSTOMERS[customer_id].accountIds if a in ACCOUNTS]


@app.get(
    "/accounts/{account_id}",
    operation_id="get_account",
    summary="Balance, status and holds of one account",
    dependencies=[Depends(api_key)],
)
def get_account(account_id: str) -> Account:
    if account_id not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    return ACCOUNTS[account_id]


class LevyRules(BaseModel):
    protectedBalance: float  # noqa: N815 - the bank API's field name
    currency: str
    exemptAccountTypes: list[str]  # noqa: N815


@app.get("/levy-rules", operation_id="get_levy_rules", summary="The exempt-funds rules a levy hold follows")
def get_levy_rules(rules_key: Annotated[str | None, Query(alias="rulesKey")] = None) -> LevyRules:
    """The levy handbook's exempt funds: the first 2,500.00 CAD of a personal chequing or savings account. The key is
    an ordinary query parameter, not a security scheme, so an import makes it an input that a code tool fills with a
    secret handle (c-531), and the value never reaches the function."""
    if rules_key != KEY:
        raise HTTPException(401, "missing or wrong rulesKey")
    return LevyRules(protectedBalance=2500.0, currency="CAD", exemptAccountTypes=["chequing", "savings"])


@app.get(
    "/accounts/{account_id}/statement",
    operation_id="get_statement",
    summary="The latest monthly statement of an account",
    dependencies=[Depends(query_key)],
)
def get_statement(account_id: str, request: Request) -> dict[str, Any]:
    if account_id not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    account = ACCOUNTS[account_id]
    lines = [t for t in TRANSACTIONS if t.accountId == account_id]
    # Repeats the URL it was called on, key and all, as a careless legacy API does; the gateway must scrub it.
    return {"accountId": account_id, "period": "2026-09", "closingBalance": account.balance, "lines": len(lines),
            "requestedUrl": str(request.url)}  # fmt: skip


@app.get(
    "/accounts/{account_id}/transactions",
    operation_id="list_transactions",
    summary="Recent transactions on an account",
    dependencies=[Depends(api_key)],
    responses=ROWS,
)
def list_transactions(account_id: str, limit: int = 10) -> list[Transaction]:
    if account_id not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    return [t for t in TRANSACTIONS if t.accountId == account_id][-limit:]


@app.post(
    "/accounts/{account_id}/holds",
    operation_id="place_hold",
    summary="Place a hold on funds in an account",
    status_code=201,
    dependencies=[Depends(api_key)],
)
def place_hold(account_id: str, body: HoldIn) -> Hold:
    if account_id not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    account = ACCOUNTS[account_id]
    available = account.balance - sum(h.amount for h in account.holds)
    if body.amount > available:
        raise HTTPException(422, f"hold of {body.amount:.2f} exceeds the available balance of {available:.2f}")
    hold = Hold(id=f"HLD-{uuid.uuid4().hex[:6]}", amount=body.amount, reason=body.reason)
    ACCOUNTS[account_id].holds.append(hold)
    return hold


@app.post(
    "/disputes",
    operation_id="open_dispute",
    summary="Open a dispute on a card or account transaction",
    status_code=201,
    dependencies=[Depends(api_key)],
)
def open_dispute(body: DisputeIn) -> Dispute:
    if not any(t.id == body.transactionId and t.accountId == body.accountId for t in TRANSACTIONS):
        raise HTTPException(404, "no such transaction on that account")
    d = Dispute(
        id=f"DSP-{uuid.uuid4().hex[:6]}",
        accountId=body.accountId,
        transactionId=body.transactionId,
        reason=body.reason,
        status="open",
    )
    DISPUTES[d.id] = d
    return d


@app.get(
    "/disputes/{dispute_id}",
    operation_id="get_dispute",
    summary="One dispute and its status",
    dependencies=[Depends(api_key)],
)
def get_dispute(dispute_id: str) -> Dispute:
    if dispute_id not in DISPUTES:
        raise HTTPException(404, "no such dispute")
    return DISPUTES[dispute_id]


class WebhookIn(BaseModel):
    event: str = Field(description="What happened, e.g. levy.processed")
    payload: dict[str, Any] = Field(description="The data sent, such as the fields read from a levy notice")


class WebhookReceipt(BaseModel):
    id: str
    received: bool = True


# Every call received, newest last, kept in memory for the inbox page (the stand-in has no database).
WEBHOOKS: list[dict[str, Any]] = []
# Headers shown on the page; the secret header is shown as present, never its value.
SHOWN_HEADERS = ("content-type", "user-agent", "idempotency-key", "x-request-id")


@app.post(
    "/webhooks/{hook}",
    operation_id="notify_webhook",
    summary="Send a JSON payload to an outside system's webhook",
    status_code=202,
    dependencies=[Depends(webhook_secret)],
)
def notify_webhook(hook: str, body: WebhookIn, request: Request) -> WebhookReceipt:
    receipt_id = f"WHK-{uuid.uuid4().hex[:8]}"
    receipt: dict[str, Any] = {
        "id": receipt_id,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "hook": hook,
        "headers": {k: v for k, v in request.headers.items() if k.lower() in SHOWN_HEADERS}
        | {"x-webhook-secret": "(present)"},
        "event": body.event,
        "payload": body.payload,
    }
    WEBHOOKS.append(receipt)
    return WebhookReceipt(id=receipt_id)


@app.get("/webhooks.json", include_in_schema=False)
def webhook_log() -> list[dict[str, Any]]:
    """Every call received, newest first: what the inbox page shows."""
    return list(reversed(WEBHOOKS))


@app.get("/webhooks", include_in_schema=False, response_class=HTMLResponse)
def webhook_inbox() -> str:
    """The receiver's inbox: each call with its time, headers and JSON, newest first, refreshed every few seconds."""
    rows = "".join(
        f"<article><header><strong>{escape(w['event'])}</strong> to <code>/webhooks/{escape(w['hook'])}</code>"
        f" <time>{escape(w['at'])}</time> <span>{escape(w['id'])}</span></header>"
        f"<pre class=h>{escape(json.dumps(w['headers'], indent=2))}</pre>"
        f"<pre>{escape(json.dumps(w['payload'], indent=2))}</pre></article>"
        for w in reversed(WEBHOOKS)
    )
    empty = "<p>Nothing received yet. Calls to <code>notify_webhook</code> appear here.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5"><title>Webhook inbox</title><style>
body{{font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:960px;padding:16px;color:#111;background:#fff}}
h1{{font-size:20px}} article{{border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0}}
header{{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}} time,span{{color:#666;font-size:12px}}
pre{{background:#f6f6f6;border-radius:6px;padding:8px;overflow-x:auto;white-space:pre-wrap;word-break:break-word}}
pre.h{{color:#555;font-size:12px}}
@media (prefers-color-scheme: dark){{body{{color:#eee;background:#111}} article{{border-color:#333}}
pre{{background:#1b1b1b}}}}
</style></head><body><h1>Webhook inbox</h1><p>{len(WEBHOOKS)} received by the outside system stand-in.</p>
{rows or empty}</body></html>"""
