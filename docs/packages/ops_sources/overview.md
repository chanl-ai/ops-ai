# Source reading library

Status: current. Used by kb-service's tool sources; files-service's watched folders are the next user (not built).

`packages/ops_sources` reads a source (a SharePoint library, a website, a Salesforce object) through its connection's
tools in tools-service, the same way for every service that reads one. The loop has one owner, so a fix to paging,
saved places or pacing lands once. The reading service keeps the place and its items behind a state port and
decides what a fetched item becomes: knowledge keeps a snapshot and indexes it; Files will keep a version.

| Part | Where | What it does |
|---|---|---|
| The contract | `packages/ops_sources/src/ops_sources/contract.py` | Names the roles a source answers (find places, changes since a place, fetch a version, access list) over the plugin's knowledge-source tools, and reads each answer (`places_of`, `listing_of`, `access_list`: None when the source did not say, `[]` when it listed nobody). `Declared` is a source as tools-service declares it; `SourceTools.of` maps a declared or stored row to its tools, keeping a null tool as None |
| `find_places` | `places.py` | Asks the source's scopes tool for the places a person can pick, as the team's connection; the knowledge picker and Files' watched folders use it |
| `ToolReader` | `reader.py` | tools-service as a reading service calls it: the sources a team can make, the hosts a source's values reach, and one gateway call (`POST /v1/calls`) |
| The state port | `state.py` | `Place` (cursor, watermark, changes cursor, last full listing, what a long listing saw so far, tombstones, failed fetches, paused) and `SourceState` (what is held per item; save the place; keep a marker; count a gone answer) |
| `read_changes` | `listing.py` | Every page of changes since the place, the place saved after each page; one restart when a saved page is refused; the page cap; a full listing first, weekly, or every run of a source that lists whole; a refused sign-in pauses the source; an item whose fetch failed on `FETCH_TRIES` (3) runs for its marker is left, still seen, until the marker moves |
| `Fetcher` | `fetching.py` | The changed items fetched a few at once and paced (the source's rate, or a slower `pace_s` its listing names), each sent its held tag; an item gone twice in a row is tombstoned; any other failed fetch is kept in the place for its marker, said once per marker (`Fetched.failed_first`) and tried again (`Fetched.retrying`, so the reading service ends the run partial) until `FETCH_TRIES` runs have; a rate limit or an unreachable gateway is no try, and a code the caller names `final` (too large) is left at once |

## How a service uses it

1. Read the place from where it keeps the source, and give the loop a `SourceState` over its own items.
2. `read_changes(...)` lists what changed; `Listing.full` and `Listing.whole` say whether every item was seen, so
   the service may remove what was not listed. `Listing.skipped` holds the items listed but not taken in, each with
   its reason, so a service can record one (a file too large) as failed rather than removed. A row refused for its
   size also carries `skipped_code: "TOO_LARGE"`, which tells it apart from one a rule left out.
3. `Fetcher(...).fetch_changed(..., on_listed=..., on_fetched=...)` hands each new version to the service in
   listing order.
4. `Listing.settle(place, status)` moves the place on after a finished run, then the service saves it. Only a
   run settled as success takes the watermark and the changes cursor the last page named, so a run whose fetches
   failed lists the same changes again.

`contract.refusal_of` and `contract.source_values` check a declared source before a service saves one (a team
sign-in, the declared inputs and their types); kb-service's create and files-service's watch create both ask them.

files-service's adapter is `FileState` in `services/files-service/src/ops_files/watches.py`: the place lives on the
watch, and the held items are the watch's source files. kb-service's adapter is `_KnowledgeState` in `services/kb-service/src/ops_kb/tool_sources.py`: the place lives in
the knowledge source's `config`, and the held items are the source's knowledge items.

## Tests

| Failure mode | Test |
|---|---|
| A reader with its own state loses its place between pages, or fetches a file whose marker did not move | `packages/ops_sources/tests/test_reading.py` |
| A plugin breaks a role the loop reads it by (places, every page of changes, a version and its tag, the access list, a delete) | `ops_plugin_sdk.testing.knowledge_contract` (its own cases in `packages/ops_plugin_sdk/tests/test_knowledge_contract.py`), run by each plugin's own tests in the plugins repository (SharePoint, Confluence, Website) |
| Knowledge syncs differently through the package | kb-service's sync suite: `tests/test_tool_sources.py`, `test_source_contract.py`, `test_connector_plugins.py`, `test_web_source.py`, `test_schedule_health.py` |

`ops_plugin_sdk.testing` pages through a listing with its own `_list_all` rather than this package: it calls the
plugin in process and in sync against the plugin's fake, and the plugin SDK ships to the plugins repository without
the service packages this loop needs.
