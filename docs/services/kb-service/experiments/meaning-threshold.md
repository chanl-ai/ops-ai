# Meaning threshold: where the meaning lane's floor sits

Status: done, 2026-11-09. Script: `services/kb-service/experiments/meaning_threshold.py` on the labelled set
`experiments/meaning_threshold_set.json`. Four real OpenAI embedding calls (two per model), none through the stack.

## Verdict

The meaning lane's default floor moves from 0.30 to 0.38. At 0.30 half of the questions nothing answers still reached
a piece through the meaning lane; at 0.38 one in twelve did, and the answering piece of 23 of 24 answerable questions
still passed. Presets: balanced 0.38, precise 0.45, raw 0.30.

## Facts

24 pieces across banking, insurance, telecom, utilities and retail, each embedded as kb-service embeds a unit (heading,
blank line, text). 24 answerable questions, each worded without the piece's own terms, and 12 that nothing answers (6
near the domain, 6 unrelated). Cosine similarity at 1,536 dimensions.

| | text-embedding-3-small | text-embedding-3-large |
|---|---|---|
| Answering piece ranked first | 23 of 24 | 24 of 24 |
| Answering piece, min / median / max | 0.282 / 0.566 / 0.647 | 0.417 / 0.567 / 0.711 |
| Best other piece, median / max | 0.367 / 0.481 | 0.346 / 0.513 |
| Unanswerable, best piece median / max | 0.301 / 0.497 | 0.297 / 0.488 |
| At 0.30: answerable kept, unanswerable withheld | 96%, 50% | 100%, 58% |
| At 0.38 | 96%, 92% | 100%, 92% |
| At 0.45 | 92%, 92% | 96%, 92% |
| At 0.50 | 79%, 100% | 71%, 100% |
| Best balanced threshold | 0.38 | 0.39 |

## Gotchas

| Gotcha | Detail |
|---|---|
| Near-domain questions are not separable by the floor | "Does my home policy cover flooding" scored 0.49 against the claims-notice piece: above any floor that keeps answers. Grounding (an answer needs a cited passage) and rerank catch these, not the threshold |
| Wrong pieces score close to right ones | The best other piece reached 0.48 to 0.51, so a floor only decides whether anything returns; order comes from fusion and rerank |
| A small set | 36 questions on one set; the numbers say where the floor belongs, not its third decimal. Rerun the script with a team's own questions before tuning a production base |
| Bases made before | A base keeps the `meaningThreshold` it was saved with (0.30 for release 1 bases); only new bases and presets take 0.38 |

## What it feeds

`DEFAULT_RETRIEVAL` and `PRESETS` in `services/kb-service/src/ops_kb/service.py`, and the `Search` default in
`retrieval.py`.
