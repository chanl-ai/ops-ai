"""Seeds the demo's document types in documents-service (c-236, c-256): levy_notice version 1, the fields a levy
notice is read with, and the two levy fixtures as its samples with the values they should read; and
restraining_notice version 1 (c-248), with the synthetic restraining notices' text PDFs as its samples
(tests/fixtures/restraining/expected.json). Re-runnable: a type that exists is left as it is.

    uv run python scripts/seed_document_types.py --platform http://127.0.0.1:8710
    uv run python scripts/seed_document_types.py --documents http://127.0.0.1:8797 --files http://127.0.0.1:8796 --dev

The samples' bytes go to files-service first, as the console uploads them; the type and its samples go to
documents-service.

The seeded levy workflows name levy_notice v1 (services/agents-service/seed/engine_workflows.json)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "agents-service" / "tests" / "fixtures" / "mailbox"
RESTRAINING = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "restraining"
TAX_LEVIES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tax_levy"
INVOICES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "invoice"
STATEMENTS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "bank_statement"
BUILDER = "j.richardson@harborpine.example"
TEAM = "team_ops"

# Active ISO 4217 codes: a currency is read only when the notice prints one of these, never guessed from a place.
_CODES = (
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF "
    "CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG "
    "HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA "
    "MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD "
    "RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX "
    "USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL "
)
CURRENCIES = _CODES.split()

LEVY_NOTICE: dict[str, Any] = {
    "id": "levy_notice",
    "name": "Levy notice",
    "description": "A court's notice of garnishment naming judgment debtors and the amount to hold for each.",
    "many": True,
    "note": "The six fields both levy workflows read, and the currency when the notice prints one.",
    "fields": [
        {"key": "name", "label": "Name", "type": "text", "required": True},
        {"key": "address", "label": "Address", "type": "text"},
        {
            "key": "ssn_last4",
            "label": "SSN last four",
            "type": "text",
            "description": "The four digits after the masked part",
        },
        {"key": "amount", "label": "Amount", "type": "money", "required": True},
        {
            "key": "currency",
            "label": "Currency",
            "type": "enum",
            "options": CURRENCIES,
            "description": "The ISO 4217 code printed with the amount; empty when the notice prints none",
        },
        {"key": "court", "label": "Court", "type": "text"},
        {"key": "case_no", "label": "Case number", "type": "text", "required": True},
    ],
}

SAMPLES: dict[str, list[dict[str, Any]]] = {
    "levy_notice.pdf": [
        {"name": "Marcus Bell", "ssn_last4": "4471", "amount": "3,250.00", "case_no": "NS-2026-GN-01187"},
        {"name": "Priya Natarajan", "ssn_last4": "9032", "amount": "12,400.00", "case_no": "ON-2026-GN-04421"},
        {"name": "Jordan Whitfield", "ssn_last4": "1180", "amount": "890.50", "case_no": "MB-2026-GN-00318"},
    ],
    "levy_notice_smudged.pdf": [
        {"name": "Ana Example", "ssn_last4": "1234", "amount": "100.00", "case_no": "NS-2026-GN-09999"},
    ],
}


def _text(
    key: str, label: str, description: str | None = None, *, required: bool = False, **rules: Any
) -> dict[str, Any]:
    field: dict[str, Any] = {"key": key, "label": label, "type": "text"}
    if description:
        field["description"] = description
    if required:
        field["required"] = True
    return field | rules


# Phrases a notice prints where it gives no value; read as one, the field is emptied and marked (c-247).
NOT_GIVEN = ["Not supplied on this form", "Not supplied", "Not provided", "N/A", "Unknown"]


# Each description carries the field's provenance rule: where on the notice the value comes from, and what it must
# never be taken from. The samples prove each rule on the notice built to break it (expected.json's `edge`).
RESTRAINING_NOTICE: dict[str, Any] = {
    "id": "restraining_notice",
    "name": "Restraining notice",
    "description": "A restraining notice, levy, warrant or writ served on the bank about one judgment debtor.",
    "many": False,
    "note": "Fields and provenance rules from the synthetic restraining notices (c-248).",
    "fields": [
        _text(
            "notice_kind",
            "Kind of notice",
            "The document's title on one line, such as Restraining notice or Tax warrant, without the court or agency",
        ),
        _text(
            "case_no",
            "Case number",
            "The case reference or index number printed at the top: the number only, without its label such as Index "
            "No. or Case reference",
            required=True,
            clean=["stripLabel"],
        ),
        _text("court", "Court", "The court in the caption; empty for an agency's levy"),
        _text("issuing_agency", "Issuing agency", "The agency issuing a levy or warrant; empty for a court notice"),
        _text(
            "creditor",
            "Judgment creditor",
            "The plaintiff or judgment creditor: the name only, without a party role or trailing punctuation; empty "
            "when none is named",
            clean=["trimPunctuation"],
        ),
        _text(
            "debtor_name",
            "Debtor",
            "The defendant, judgment debtor or taxpayer, never a claimant; the name only, without a party role such as "
            "Plaintiff or Defendant or trailing punctuation",
            required=True,
            clean=["trimPunctuation"],
        ),
        _text(
            "debtor_address",
            "Debtor address",
            "The debtor's own address only, never the sender's, agency's, attorney's or recipient bank's; empty when "
            "the notice says it is not supplied",
            emptyWhen=NOT_GIVEN,
        ),
        _text(
            "ssn_full",
            "SSN",
            "The full SSN tied to this debtor, from any page; never fill masked digits; keep an invalid-looking "
            "number as printed",
            pattern=r"\d{3}-\d{2}-\d{4}",
        ),
        _text(
            "ssn_last4",
            "SSN last four",
            "The last four digits of the debtor's SSN only, such as 4321, never the masked part",
            clean=["lastFour"],
        ),
        _text("ein", "Federal EIN", "A business debtor's federal employer identification number"),
        _text("state_tax_id", "State tax ID", "A business debtor's state tax identifier"),
        _text(
            "attorney_name",
            "Attorney",
            "Counsel from the attorney signature block only, never the letterhead or the sender",
            clean=["trimPunctuation"],
        ),
        _text("attorney_firm", "Attorney firm", "The firm after the attorney's name in the signature block"),
        _text("attorney_address", "Attorney address", "The address in the attorney signature block"),
        _text(
            "garnishee",
            "Garnishee",
            "The bank the notice is addressed to: the institution's name only, without TO or its address",
        ),
        _text("garnishee_address", "Garnishee address", "The recipient bank's address"),
        {"key": "amount", "label": "Amount due", "type": "money"},
        {"key": "date_served", "label": "Date served", "type": "date"},
        {"key": "response_deadline", "label": "Respond by", "type": "date"},
    ],
}


# A state or federal tax levy served on the bank (c-270): the levy demo's second kind beside the restraining notice.
TAX_LEVY: dict[str, Any] = {
    "id": "tax_levy",
    "name": "Tax levy",
    "description": "A state or federal tax authority's levy or warrant served on the bank for a taxpayer's unpaid tax.",
    "many": False,
    "note": "Fields from the synthetic tax levies (c-270).",
    "fields": [
        _text(
            "notice_kind",
            "Kind of notice",
            "The document's title on one line, such as Notice of levy, without the State or Federal after a dash",
        ),
        _text(
            "case_no",
            "Levy number",
            "The levy, warrant or case number printed at the top: the number only, without its label such as Case "
            "reference",
            required=True,
            clean=["stripLabel"],
        ),
        _text("authority", "Authority", "The tax authority issuing the levy, never the bank", required=True),
        _text(
            "taxpayer_name",
            "Taxpayer",
            "The taxpayer whose funds are levied, person or business, the name only",
            required=True,
            clean=["trimPunctuation"],
        ),
        _text(
            "taxpayer_address",
            "Taxpayer address",
            "The taxpayer's own address only, never the authority's or the bank's",
            emptyWhen=NOT_GIVEN,
        ),
        _text(
            "taxpayer_id_last4",
            "SSN last four",
            "The last four digits of a person's SSN only, such as 3301, never the masked part",
            clean=["lastFour"],
        ),
        _text(
            "taxpayer_ein",
            "EIN",
            "A business taxpayer's employer identification number, printed as two digits, a hyphen and seven digits",
            pattern=r"\d{2}-\d{7}",
        ),
        _text("tax_type", "Tax type", "The kind of tax, such as income, sales and use, employment or withholding"),
        _text("tax_period", "Tax period", "The period or periods the tax is for, as printed"),
        {"key": "amount_due", "label": "Amount due", "type": "money", "required": True},
        {"key": "levy_date", "label": "Levy date", "type": "date"},
        {
            "key": "response_deadline",
            "label": "Respond by",
            "type": "date",
            "description": "The date the bank must answer by",
        },
        _text(
            "release_conditions",
            "Release conditions",
            "When the levy is released, as the notice states it, on one line, without a label such as Release:",
            clean=["stripLabel"],
        ),
        _text(
            "garnishee",
            "Garnishee",
            "The bank the levy is addressed to: the institution's name only, without TO or its address",
        ),
    ],
}


# Two kinds that are not levies (c-255), so classify, templates and boxes are proven on more than one kind of document.
SUPPLIER_INVOICE: dict[str, Any] = {
    "id": "supplier_invoice",
    "name": "Supplier invoice",
    "description": "A vendor's invoice to the bank for goods or services, with its number, dates and total due.",
    "many": False,
    "note": "Fields from the synthetic supplier invoices (c-255).",
    # An invoice is due after it is issued (c-296).
    "checks": [{"id": "due_after_issue", "kind": "before", "earlier": "invoice_date", "later": "due_date"}],
    "fields": [
        _text(
            "invoice_no",
            "Invoice number",
            "The invoice's number as printed, without its label",
            required=True,
            clean=["stripLabel"],
            keyField=True,
        ),
        _text(
            "vendor",
            "Vendor",
            "The company that issued the invoice, the name only",
            required=True,
            clean=["trimPunctuation"],
        ),
        _text("bill_to", "Bill to", "Who the invoice is billed to, the name only", clean=["trimPunctuation"]),
        {
            "key": "invoice_date",
            "label": "Invoice date",
            "type": "date",
            "description": "The date the invoice was issued",
        },
        {"key": "due_date", "label": "Due date", "type": "date", "description": "The date payment is due"},
        {"key": "tax", "label": "Tax", "type": "money", "description": "The tax amount, not the total"},
        {
            "key": "total",
            "label": "Total due",
            "type": "money",
            "required": True,
            "keyField": True,
            "description": "The total amount due, including tax",
        },
    ],
}

BANK_STATEMENT: dict[str, Any] = {
    "id": "bank_statement",
    "name": "Bank statement",
    "description": "A bank or credit union's account statement for one account holder over one period, with balances.",
    "many": False,
    "note": "Fields from the synthetic bank statements (c-255).",
    "fields": [
        _text(
            "account_holder",
            "Account holder",
            "The person or company the account belongs to, the name only",
            required=True,
            clean=["trimPunctuation"],
        ),
        _text(
            "account_last4",
            "Account last four",
            "The last four digits of the account number only, never the masked part",
            clean=["lastFour"],
            pattern=r"\d{4}",
        ),
        {
            "key": "period_start",
            "label": "Period start",
            "type": "date",
            "description": "The first day the statement covers",
        },
        {
            "key": "period_end",
            "label": "Period end",
            "type": "date",
            "description": "The last day the statement covers",
        },
        {
            "key": "opening_balance",
            "label": "Opening balance",
            "type": "money",
            "description": "The balance at the start of the period",
        },
        {
            "key": "closing_balance",
            "label": "Closing balance",
            "type": "money",
            "required": True,
            "description": "The balance at the end of the period",
        },
    ],
}


def samples_in(folder: Path) -> dict[str, dict[str, Any]]:
    """A fixture folder's text PDFs and what each should read; scans need OCR, which a test run does not turn on."""
    entries: dict[str, dict[str, Any]] = json.loads((folder / "expected.json").read_text())
    return {name: e["expected"] for name, e in sorted(entries.items()) if not e.get("imageOnly")}


# The fixture-backed types: each definition, its samples and the folder their files are in.
SEEDED: dict[str, tuple[dict[str, Any], Callable[[], dict[str, dict[str, Any]]], Path]] = {
    "RESTRAINING_NOTICE": (RESTRAINING_NOTICE, lambda: samples_in(RESTRAINING), RESTRAINING),
    "TAX_LEVY": (TAX_LEVY, lambda: samples_in(TAX_LEVIES), TAX_LEVIES),
    "SUPPLIER_INVOICE": (SUPPLIER_INVOICE, lambda: samples_in(INVOICES), INVOICES),
    "BANK_STATEMENT": (BANK_STATEMENT, lambda: samples_in(STATEMENTS), STATEMENTS),
}


def data(r: httpx.Response) -> Any:
    if r.status_code >= 300:
        sys.exit(f"{r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}")
    return r.json()["data"]


def put(files: httpx.Client, name: str, body: bytes) -> str:
    """The console's upload: a ticket, the bytes, complete."""
    ticket = data(
        files.post(
            "/v1/files/uploads",
            json={"name": name, "size": len(body), "mime": "application/pdf", "purpose": "document_type_sample"},
        )
    )
    files.put(ticket["uploadUrl"], content=body, headers=ticket["headers"]).raise_for_status()
    return str(data(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def seed_type(
    documents: httpx.Client, files: httpx.Client, kind: dict[str, Any], samples: dict[str, Any], folder: Path
) -> str:
    made = documents.post("/v1/document-types", json=kind)
    if made.status_code == 409:
        # Create-only: an existing type is left as people left it. A new version made here on every start would drop
        # the templates and fields a person saved; a change to a seeded type is a version made through the API.
        return f"{kind['id']}: already there"
    data(made)
    for pdf, expected in samples.items():
        file_id = put(files, pdf, (folder / pdf).read_bytes())
        body = {"fileId": file_id, "expected": expected}
        data(documents.post(f"/v1/document-types/{kind['id']}/samples", json=body))
    return f"{kind['id']}: v1 with {len(samples)} samples"


def seed(documents: httpx.Client, files: httpx.Client) -> str:
    levy = seed_type(documents, files, LEVY_NOTICE, SAMPLES, FIXTURES)
    done = [seed_type(documents, files, kind, samples(), folder) for kind, samples, folder in SEEDED.values()]
    return "; ".join([levy, *done])


def sign_in(platform: str, email: str, password: str) -> dict[str, str]:
    r = httpx.post(f"{platform}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"sign-in as {email} failed: {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--documents", default=f"http://127.0.0.1:{os.environ.get('OPS_DOCUMENTS_PORT', '8760')}")
    ap.add_argument("--files", default=f"http://127.0.0.1:{os.environ.get('OPS_FILES_PORT', '8750')}")
    ap.add_argument("--platform", default=f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}")
    ap.add_argument("--password", default=os.environ.get("OPS_PLATFORM_DEMO_PASSWORD", "northfield-demo"))
    ap.add_argument("--dev", action="store_true", help="dev auth (a stack not signed in through platform-service)")
    args = ap.parse_args()
    who = {"X-Dev-User": BUILDER} if args.dev else sign_in(args.platform, BUILDER, args.password)
    headers = {**who, "X-Team-Id": TEAM}
    with (
        httpx.Client(base_url=args.documents, headers=headers, timeout=60) as documents,
        httpx.Client(base_url=args.files, headers=headers, timeout=60) as files,
    ):
        print(seed(documents, files))


if __name__ == "__main__":
    main()
