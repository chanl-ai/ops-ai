# A team runs its agents on its own Azure OpenAI resource, set on Settings or at install, and calls stay in its region

Status: passing. Id: `uc-605`. Service: `models-service`. Layers: api, cli, ui. Card: an earlier change.

An Azure OpenAI connection names the resource's endpoint, an api-version (`v1`, or a dated version from 2024-10-21 on),
optionally the region it runs in, and the name of a saved provider key. models-service sends the key in the `api-key` header to
`{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=…`, or to `{endpoint}/openai/v1/chat/completions`
with the deployment as `model` for `v1`; an alias's model id is the deployment. An answer from another region than the
connection names goes through and is flagged on the connection and in the call log (2026-10-31: warn only).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An agent's alias on an Azure deployment answers, streamed and not, with its tool calls and its usage totals, on both Azure paths | api | 1-4 | 2 |
| S2 | An account admin connects Azure OpenAI on Model providers: the form asks endpoint, API version, region and key, refuses a version too old to stream usage, the list shows the region Azure answered from or a mismatch, and a builder sees none of it | ui | 9-14 | 10 |
| S3 | An install sets OPENAI_API_TYPE=azure with its endpoint, version and region, and the stack's default model is that resource; a missing api-version stops models-service naming it | cli | 7-8 | 8 |
| S4 | A resource answering from another region than the connection names still answers, flagged on the connection and in the call log | api | 5 | 5 |
| S5 | No answer, list, call log or refusal shows the key, and a connection with a missing or old api-version is refused | api | 6 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| The fake Azure | `services/models-service/scripts/fake_openai` serves Azure's two paths: 401 to a bearer token or a wrong key on the deployment path, 404 without an api-version, and `x-ms-region` from FAKE_AZURE_REGION (default `Sweden Central`) |
| The run's stack | api and cli start their own models-service and fake; ui uses the runner's demo stack with platform sign-in (`packages/usecase-runner/src/harness.ts`) |

No real Azure resource is called: none is available to this repository, so a real call is still owed (see below).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Connect `claims-azure` (api-version 2024-10-21, region swedencentral, key `AZURE_UC605`) and alias `uc605-claims` on deployment `claims-gpt4o`; call it | 200 with the fake's text; the fake saw the `api-key` header on `/openai/deployments/claims-gpt4o/chat/completions?api-version=2024-10-21` (it refuses anything else) |
| 2 | Call it streamed, and with a tool offered, streamed and not | The stream ends with the usage chunk and the call log's tokens equal it; no Azure filter annotation reaches the caller; the tool call comes back whole and as a delta |
| 3 | Connect `claims-azure-v1` (api-version v1) and call an alias on it | 200 through `/openai/v1/chat/completions` |
| 4 | Rebind `claims-azure` naming only its base URL and key | api-version and region are kept; the next call still answers 200 |
| 5 | Connect `claims-wrong-region` (region eastus) and call an alias on it | 200; the list shows `observedRegion` Sweden Central; the call log row is `ok` with reason `answered from Sweden Central, expected eastus` |
| 6 | Read the list, the call log and every refusal | No part of the key appears; a connection missing its api-version, or with 2024-02-01, is refused 400 naming the field |
| 7 | Start models-service with OPENAI_API_TYPE=azure, OPENAI_API_BASE (the fake), OPENAI_API_VERSION=2024-10-21, OPENAI_API_REGION=swedencentral and the dev key `openai` | `openai-local` is the Azure connection and alias `default` answers through it |
| 8 | Start it again with OPENAI_API_VERSION unset | It exits non-zero, and its output names OPENAI_API_VERSION |
| 9 | Sam, an account admin, saves key `AZURE_UC605` on Model providers and opens Connect a provider | Azure OpenAI is picked and the form shows Endpoint, API version, Region and Key |
| 10 | Sam enters API version 2024-06-01 and connects | Refused under API version, naming 2024-10-21 |
| 11 | Sam enters 2024-10-21 and connects | The list shows `uc605-ui` as Azure OpenAI, its endpoint, swedencentral, Not called yet, and `AZURE_UC605` |
| 12 | An alias on it is called, and Sam reloads | 200; the region reads Answered from Sweden Central |
| 13 | A connection in westeurope is called, and Sam reloads | 200; its row reads Answered from Sweden Central, expected westeurope |
| 14 | James, a builder of Operations, opens the page and tries the API | The page says only an account admin sees it; list and create answer 403 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `models-service/scripts/test-uc-605-api.py` | passing, `make usecase-test UC=uc-605 LAYER=api` (2026-10-31) |
| cli | `models-service/scripts/test-uc-605-cli.py` | passing, `make usecase-test UC=uc-605 LAYER=cli` (2026-10-31) |
| ui | `models-service/scripts/test-uc-605-ui.mjs` | passing, `make usecase-test UC=uc-605 LAYER=ui` (2026-10-31) |

## Non-vacuous check

Step 1, `the key reaches Azure in its api-key header on the deployment path`: the fake refuses a bearer token there, so
an adapter that sent OpenAI's header would answer 502. With `AzureOpenAIProvider` sending `Authorization: Bearer`, the
models-service tests for the header, the URL, tool calls and region failed (`services/models-service/tests/
test_azure_provider.py`, seen 2026-10-31).

## Owed

One call against a real Azure OpenAI resource in a named region, to confirm the `x-ms-region` header's spelling and the
stream's frame order against the fake's: owed with the first customer (2026-10-31). A per-connection option to
refuse an answer from another region is left out until then.
