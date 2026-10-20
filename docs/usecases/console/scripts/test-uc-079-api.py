"""uc-079 the branch policy agent answers from the manual or says it does not know, api layer:
docs/usecases/console/branch-policy-answers.md. The demo stack (usecase_harness.demo) with the Branch operations
base; after the first answers the fee schedule is replaced by version 2 and synced. Each answer is checked on its
evidence: the citation's document and page, the figures the passage holds, and the version after the re-sync."""

from __future__ import annotations

from usecase_harness import chat, check, demo, finish, seed_demo_knowledge, turn_citations, turn_parts, turn_text

NOT_IN_KB = "That is not in the knowledge base."

with demo() as stack:
    asked = {
        "fee": ("What is the fee for an outgoing wire transfer?", "Fee Schedule", 1),
        "atm": ("What is the daily ATM withdrawal limit?", "Branch Operations Manual", 2),
        "stop": ("How do I place a stop payment on a cheque?", "Branch Operations Manual", 3),
    }
    answers = {}
    for key, (question, title, page) in asked.items():
        _, events = chat(stack.api, "ag_policy", question)
        answers[key] = events
        cited = turn_citations(events)
        check(
            f"the {key} answer cites {title} on page {page}",
            "[1]" in turn_text(events) and bool(cited) and cited[0]["title"] == title and cited[0].get("page") == page,
            {"text": turn_text(events)[:200], "citations": cited},
        )
    fee_v1 = answers["fee"]
    check("the fee answer quotes the schedule's 30.00", "30.00" in turn_text(fee_v1), turn_text(fee_v1))
    limits = [p for p in turn_parts(answers["atm"]) if p["shape"] == "rows"]
    check(
        "the limits draw as a rows part with the manual's four amounts",
        len(limits) == 1 and [r.get("amount") for r in limits[0]["data"]] == ["1,000", "3,000", "3,000", "10,000"],
        limits,
    )

    _, events = chat(stack.api, "ag_policy", "What is the prepayment penalty on a fixed-rate mortgage?")
    check(
        "a question the base does not cover gets the not-in-the-knowledge-base reply and no citation",
        turn_text(events).strip() == NOT_IN_KB and turn_citations(events) == [],
        {"text": turn_text(events), "citations": turn_citations(events)},
    )

    # US5: version 2 replaces the fee schedule under the same name; the next answer cites and quotes it.
    seed_demo_knowledge(stack.kb_url, stack.files_url, fees="v2")
    _, events = chat(stack.api, "ag_policy", "What is the fee for an outgoing wire transfer?")
    before, after = turn_citations(fee_v1), turn_citations(events)
    check(
        "after the re-sync the fee answer quotes 35.00 and cites a newer version of the Fee Schedule",
        "35.00" in turn_text(events)
        and bool(after)
        and after[0]["title"] == "Fee Schedule"
        and bool(before)
        and after[0]["version"] != before[0]["version"],
        {"text": turn_text(events)[:200], "before": before[:1], "after": after[:1]},
    )

finish()
