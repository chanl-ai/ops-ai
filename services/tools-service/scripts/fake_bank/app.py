"""A stand-in core-banking API for walking the bank use case on a dev stack: a real HTTP upstream with an OpenAPI
document the tools service imports, an API key it checks, and writes that change what later reads return.

Run it with `python -m fake_bank` (see __main__.py): https as api.bank.test on this machine's private address, which
is how tools-service's egress rules let it reach anything. The key is FAKE_BANK_KEY (default dev-bank-key)."""

from __future__ import annotations

import os
import uuid
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

KEY = os.environ.get("FAKE_BANK_KEY", "dev-bank-key")

app = FastAPI(title="Northfield Core Banking", version="1.0.0", servers=[{"url": "https://api.bank.test"}])


# Declared as a security scheme so the OpenAPI document names it, as a real bank's would; the importer turns the
# scheme name into the secret the header reads (bank_api_key -> {{BANK_API_KEY}}).
KEY_HEADER = APIKeyHeader(name="X-Api-Key", scheme_name="bank_api_key", auto_error=False)


def api_key(x_api_key: Annotated[str | None, Security(KEY_HEADER)] = None) -> None:
    if x_api_key != KEY:
        raise HTTPException(401, "missing or wrong X-Api-Key")


class Customer(BaseModel):
    id: str
    name: str
    email: str
    segment: str
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
        accountIds=["CHQ-2219", "SAV-4410"],
    ),
    "CUS-1002": Customer(
        id="CUS-1002",
        name="Priya Natarajan",
        email="priya.n@example.com",
        segment="small business",
        accountIds=["BUS-7781"],
    ),
}
ACCOUNTS = {
    "CHQ-2219": Account(
        id="CHQ-2219", customerId="CUS-1001", type="chequing", currency="CAD", balance=2140.55, status="open"
    ),
    "SAV-4410": Account(
        id="SAV-4410", customerId="CUS-1001", type="savings", currency="CAD", balance=18250.00, status="open"
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
]
DISPUTES: dict[str, Dispute] = {}


@app.get(
    "/customers",
    operation_id="search_customers",
    summary="Find customers by name or email",
    dependencies=[Depends(api_key)],
)
def search_customers(query: Annotated[str, Query(min_length=2)]) -> list[Customer]:
    q = query.lower()
    return [c for c in CUSTOMERS.values() if q in c.name.lower() or q in c.email.lower()]


@app.get(
    "/customers/{customer_id}",
    operation_id="get_customer",
    summary="One customer and their account ids",
    dependencies=[Depends(api_key)],
)
def get_customer(customer_id: str) -> Customer:
    if customer_id not in CUSTOMERS:
        raise HTTPException(404, "no such customer")
    return CUSTOMERS[customer_id]


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


@app.get(
    "/accounts/{account_id}/transactions",
    operation_id="list_transactions",
    summary="Recent transactions on an account",
    dependencies=[Depends(api_key)],
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
