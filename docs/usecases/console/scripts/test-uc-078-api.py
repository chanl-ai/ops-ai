"""uc-078 the advisor's helper answers about a customer and compares products, api layer:
docs/usecases/console/advisor-helper-answers.md. The demo stack (usecase_harness.demo): turns run through
models-service on the fake OpenAI with the committed demo rules, the customer reads reach the core bank through
tools-service, and the comparison answers from the Retail products base. Each check reads its evidence from the
stream: a part's data from the bank, a figure the text quotes from a tool result, a citation's page."""

from __future__ import annotations

from usecase_harness import chat, check, demo, finish, turn_citations, turn_parts, turn_text

with demo() as stack:
    # US1: her record and her accounts, both from the bank.
    tid, events = chat(stack.api, "ag_advisor", "What does Priya Natarajan have with us?")
    parts = turn_parts(events)
    records = [p for p in parts if p["shape"] == "record"]
    rows = [p for p in parts if p["shape"] == "rows"]
    check(
        "her customer record draws as a record part with the bank's id and her account",
        len(records) == 1 and records[0]["data"].get("id") == "CUS-1002" and "BUS-7781" in str(records[0]["data"]),
        records,
    )
    check(
        "her accounts draw as a rows part with the bank's balance",
        len(rows) == 1 and [(r.get("id"), r.get("balance")) for r in rows[0]["data"]] == [("BUS-7781", 48210.9)],
        rows,
    )
    text = turn_text(events)
    check("the reply quotes the balance the bank returned", "48210.9" in text and "BUS-7781" in text, text)

    # US2: the comparison is a table from the product sheet's passage, and the answer cites it by page.
    _, events = chat(stack.api, "ag_advisor", "Compare Savings Plus and Money Market for her", thread=tid)
    tables = [p for p in turn_parts(events) if p["shape"] == "rows"]
    check(
        "the comparison draws as a rows part with each product's minimum balance from the passage",
        len(tables) == 1
        and [(r.get("product"), r.get("minimum balance")) for r in tables[0]["data"]]
        == [("Savings Plus", "5,000"), ("Money Market", "25,000")],
        tables,
    )
    cited = turn_citations(events)
    check(
        "the comparison cites the Retail Product Sheet on page 4",
        "[1]" in turn_text(events)
        and bool(cited)
        and cited[0]["title"] == "Retail Product Sheet"
        and cited[0].get("page") == 4,
        {"text": turn_text(events)[:200], "citations": cited},
    )

finish()
