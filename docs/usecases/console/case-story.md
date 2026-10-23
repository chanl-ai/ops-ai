# A case shows the whole story of its matter and what is left

Status: current. Id: `uc-500`. Service: `console` on agents-service. Layers: ui. Card: c-500.

A case owner opens a case and learns from its top whether the matter is handled: what is left, on whom and by when,
how the case's work began, one timer, and one feed of everything that happened in plain sentences. The feed is the run
story's lines (`run_story.lines`, the run page's "What happened") for every run linked to the case plus the case's own
events, so the run page and the case page say a step the same way. The use case runs three kinds of case on the demo
stack with a worker: a card dispute James starts from its form (copy of `scripts/demo/workflows/card_dispute_intake.json`,
Marcus Bell's Coastal Air fare, which the fake model assesses as due a credit and the bank's core matches), a tax levy
that arrives by test email (copies of the seeded `levy_mail`, `levy_read_one` and `levy_case`, reading
`TAXLEVY01.pdf`, a `tax_levy` case whose type names `respondBy` as its deadline and whose read gives it, written
"October 27, 2026"), and a case James opens by hand.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts the dispute copy from Start run → its form, test run | The run starts |
| 2 | He opens the case the run opened | What's left names who it waits on, no Resolve; "James Richardson started Card dispute intake (uc-500) from its form"; the feed has "Opened a case: Card dispute: Coastal Air, …", an "Asked …" line and the start line, and no tool names |
| 3 | He chooses People | Only lines a person did |
| 4 | Maya rejects the credit; the run ends; James reloads and presses Resolve | "Nothing is left", Resolve shown, the feed has "Maya Okafor rejected: …"; the case reads Resolved |
| 5 | James sends the levy mail copy a test email with `TAXLEVY01.pdf` and opens the tax levy case | "From an email from registry@court.example: Notice of levy SYN-TL-2026-0101"; the timer reads "Respond by"; the feed has "Email from registry@court.example: Notice of levy SYN-TL-2026-0101", "Read TAXLEVY01.pdf: …" and "Opened a case: Tax levy: Riley Fixture (SYN-TL-2026-0101)" |
| 6 | James opens a case by hand | "Opened by James Richardson", the feed's "James Richardson opened this case", the Resolution timer, Resolve offered |
| 7 | He opens the dispute run's page | "What happened" starts with the same start line and has "Maya Okafor rejected: …" |
| 8 | Every page at 1280 and 400 px | No page errors and no sideways scroll |

Screenshots are saved under `evidenceDir('500', 'uc')` (the use-case runner's harness). Set `OPS_USECASE_DB` to a fresh
name when the shared `ops_usecase` database holds rows an older checkout wrote.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-500-ui.mjs` | passing |

## Non-vacuous check

Run before the case page changed (after T006), the case page steps failed: no What's left line, no origin, no feed
drawn through StoryFeed (`uc-red.txt` under `evidenceDir('500')`). After it, all eight pass (`uc-green.txt`
there).
