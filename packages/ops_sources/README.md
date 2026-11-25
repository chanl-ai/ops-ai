# ops_sources

Reads a source through its connection's tools in tools-service: every page of changes since a saved place, the
changed items fetched a few at once and paced, gone-twice removal. The reading service keeps the place and its items
behind the `SourceState` port. Design and parts: [docs/packages/ops_sources/overview.md](../../docs/packages/ops_sources/overview.md).

```python
from ops_sources import Fetcher, Place, SourceTools, read_changes

tools = SourceTools(list="list_files", get="get_file", changes="list_file_changes", get_takes_tag=True)
listing = await read_changes(reader, state, place, tools, tenant="local", team="team_ap", values=values,
                             connection_id="con_ap", full=False, trigger="schedule", act="files-check:watch_1",
                             counts=counts)
await Fetcher(reader, state, tools, listing, tenant="local", team="team_ap", act="files-check:watch_1").fetch_changed(
    place, counts, listing.errors, listing.log, on_listed=keep, on_fetched=keep)
listing.settle(place, listing.status)
await state.save(place)
```

Tests: `make test PKG=packages/ops_sources`.
