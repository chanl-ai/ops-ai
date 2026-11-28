# Sample project base: 40 documents, 40 questions, today's score

Status: current, 2026-11-27. Scripts: `services/kb-service/experiments/sample_base/make_base.py` (the documents),
`questions.json` (the fixed questions), `score.py` (the score). Run with `make kb-sample-score` on a running stack.

**The score below was taken on the scripted model** (`DEMO_MODEL=fake`): the scripted embeddings and no picture
reading, since the scripted model answers no page picture. It measures reading and keyword search on these files, not
a real model's meaning search or descriptions. A run on a real model needs the owner's approval for its spend.

## What it is

Four made-up projects in four industries (claims intake in insurance, a meter data platform in utilities, a small
business lending portal in banking, a clinic scheduling service in healthcare), ten documents each, written from one
table of facts per project so every question has one known answer. Each project has the three shapes the design
started from: a Word decision note written with bold lines instead of heading styles, an architecture review PDF whose
second page is a diagram with no text layer, and a change log. The rest are a team roster, runbook and onboarding PDF,
meeting notes and a risk register (with a table) in Word, release notes and a glossary in Markdown.

Forty questions, ten of each kind: who works on what, how the system fits together, why a choice was made, and what
changed. A question is answered when one of the first three citations is a document it expects, at the page it names
when it names one (the "how" questions about the diagram expect the review at page 2).

## Today's score

`make kb-sample-score OPS_PORT_OFFSET=35000`, base `kb_565052f55c3b`, 40 of 40 documents indexed:

| Kind | Answered |
|---|---|
| Who works on what | 9 of 10 |
| How the system fits together | 6 of 10 |
| Why a choice was made | 10 of 10 |
| What changed | 10 of 10 |
| All | 35 of 40 |

| Miss | Why |
|---|---|
| Four "how does work get from A to C" questions | The answer is the diagram on page 2 of each review. OCR read it as the three box labels only, and the scripted model describes no picture, so the glossary (which names the parts) ranks first |
| "Who is on call for the Credit decision engine?" | The roster says it in words the question does not use ("owns ... and is on call for it"); the runbook ranks first |

The four diagram misses are the ones picture reading exists for: on a real model the diagram's description says how
the parts connect. documents-service now sends a page OCR read as under 30 words to the model too
(`test_a_diagram_whose_labels_ocr_reads_is_still_described`), since a labelled diagram is read as its labels.

## Gotchas

| Trigger | What to do |
|---|---|
| The base's name already exists (409) | The name carries the time to the second; two runs in one second collide |
