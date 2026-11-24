# Source reading library

Status: current. Used by kb-service's tool sources; files-service's watched folders are the next user (not built).

`packages/ops_sources` reads a source (a SharePoint library, a website, a Salesforce object) through its connection's
tools in tools-service, the same way for every service that reads one. The loop has one owner, so a fix to paging,
saved places or pacing lands once. The reading service keeps the place and its items behind a state port and
decides what a fetched item becomes: knowledge keeps a snapshot and indexes it; Files will keep a version.

| Part | Where | What it does |
|---|---|---|
| The contract | `packages/ops_sources/src/ops_sources/contract.py` | Names the roles a source answers (find places, changes since a place, fetch a version, access list) over the plugin's knowledge-source tools, and reads each answer (`places_of`, `listing_of`, `access_list`) |
| `ToolReader` | `reader.py` | tools-service as a reading service calls it: the sources a team can make, the hosts a source's values reach, and one gateway call (`POST /v1/calls`) |
| The state port | `state.py` | `Place` (cursor, watermark, changes cursor, last full listing, what a long listing saw so far, tombstones, paused) and `SourceState` (what is held per item; save the place; keep a marker; count a gone answer) |
| `read_changes` | `listing.py` | Every page of changes since the place, the place saved after each page; one restart when a saved page is refused; the page cap; a full listing first, weekly, or every run of a source that lists whole; a refused sign-in pauses the source |
| `Fetcher` | `fetching.py` | The changed items fetched a few at once and paced (the source's rate, or a slower `pace_s` its listing names), each sent its held tag; an item gone twice in a row is tombstoned |

## How a service uses it

1. Read the place from where it keeps the source, and give the loop a `SourceState` over its own items.
2. `read_changes(...)` lists what changed; `Listing.full` and `Listing.whole` say whether every item was seen, so
   the service may remove what was not listed.
3. `Fetcher(...).fetch_changed(..., on_listed=..., on_fetched=...)` hands each new version to the service in
   listing order.
4. `Listing.settle(place, status)` moves the place on after a finished run, then the service saves it.

kb-service's adapter is `_KnowledgeState` in `services/kb-service/src/ops_kb/tool_sources.py`: the place lives in
the knowledge source's `config`, and the held items are the source's knowledge items.

## Tests

| Failure mode | Test |
|---|---|
| A reader with its own state loses its place between pages, or fetches a file whose marker did not move | `packages/ops_sources/tests/test_reading.py` |
| A plugin breaks a role the loop reads it by (places, every page of changes, a version and its tag, the access list, a delete) | `ops_plugin_sdk.testing.knowledge_contract` (its own cases in `packages/ops_plugin_sdk/tests/test_knowledge_contract.py`), run by each plugin's own tests in the plugins repository (SharePoint, Confluence, Website) |
| Knowledge syncs differently through the package | kb-service's sync suite: `tests/test_tool_sources.py`, `test_source_contract.py`, `test_connector_plugins.py`, `test_web_source.py`, `test_schedule_health.py` |
