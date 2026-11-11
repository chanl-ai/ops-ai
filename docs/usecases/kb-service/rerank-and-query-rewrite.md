# A knowledge owner turns on rerank and query rewrite

Status: passing. Id: `uc-677`. Service: `kb-service`. Layers: api, sdk, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Both steps are off by default and a search names neither | api | 1 | 1 |
| S2 | With rerank on, the agents' search follows a chat model's 0 to 10 scores and says it reranked | api | 2 | 2 |
| S3 | With rewrite on, the question is rewritten with the base's instruction and both forms are shown | api | 3 | 3 |
| S4 | A rewrite mode that is not built is refused | api | 4 | 4 |
| S5 | A developer turns rerank on and reads the reranked search through both SDKs | sdk | 5, 6 | 6 |
| S6 | On the Retrieval tab the owner turns rerank on, and the Playground shows the Reranked column | ui | 7, 8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL with pgvector | `make db-up` on the pgvector image, or `OPS_PG_PORT=<port>` naming another pgvector server |
| Models | models-service on its scripted aliases and the fake OpenAI answering the rewrite and rerank prompts from `services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai/script.json`; the base names alias `default`, which the fake serves. No provider is called |

Run: `make usecase-test UC=uc-677 LAYER=api` (or `sdk`, `ui`).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Two typed pages (wire cutoff, wire fees); search "domestic wire" | Passages; no `rerank` and no `rewrite` in the answer |
| 2 | Turn rerank on (`queryModel` default) and search again on `POST /v1/knowledge-bases/search` | `rerank.ran`; Wire fees first, scored 9; the other scored 0 |
| 3 | Turn rerank off and rewrite on with an instruction; ask the query route "how late can money leave" | `rewrite.asked` and `rewrite.rewritten` ("domestic wire cutoff"); Wire cutoff first |
| 4 | Save rewrite `expand` | 400 `invalid_retrieval` |
| 5 | Python SDK: save rerank on, then query | `rerank.ran`; the first passage reranked 9 |
| 6 | TypeScript SDK: the same search | The same order and scores |
| 7 | Console Retrieval tab: turn Rerank on, name alias `default`, save | One PATCH with `rerank: true` |
| 8 | Playground: ask "domestic wire" | The trace says Reranked 2 on default and shows a Reranked column with 9 of 10 first |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-677-api.py` | passing |
| sdk | `kb-service/scripts/test-uc-677-sdk.py` | passing |
| ui | `kb-service/scripts/test-uc-677-ui.mjs` | passing |

## Non-vacuous check

`test_rerank_scores_decide_the_order_and_the_limit_on_the_agents_route` failed (`assert [2, 9] == [9, 2]`) with the
reranked sort replaced by the fused order, then passed with it restored.
