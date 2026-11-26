# ops_sources: working rules

Status: current.

The one loop that reads a source through its connection's tools: changes since a saved place with every page read,
paced fetches, gone-twice. kb-service uses it today; files-service's watched folders will. It imports no service and
owns no table. Usage: [README.md](README.md); design: [docs/packages/ops_sources/overview.md](../../docs/packages/ops_sources/overview.md).
Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Public API | `read_changes`, `Listing`, `Fetcher`, `Fetched`, `Pacer`, `ToolReader`, `Place`, `Held`, `SourceState`, `Reader`, `SourceTools`, `Answer`, `places_of`, `listing_of`, `access_list`, and the limits `MAX_PAGES`, `FULL_EVERY`, `GONE_TWICE`, `AT_ONCE` |
| Contract | The roles are the plugin SDK's knowledge-source contract (`ops_plugin_sdk.manifest.KnowledgeSource`); a plugin is checked against them with `ops_plugin_sdk.testing.knowledge_contract` |
| State | The caller keeps the place and its items behind `SourceState`; `held` must answer an item written earlier in the same run as written |
| Depends on | `ops_identity` (`ServiceClient`), `ops_service_kit` |
| Used by | kb-service (`ops_kb.tool_sources`) |
| Tests | `make test PKG=packages/ops_sources`; the knowledge state is guarded by kb-service's sync suite |
| Lint, types | `uv run ruff check packages/ops_sources`, `uv run pyright packages/ops_sources` |

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`), [configuration](../../docs/architecture/standards/configuration.md) (`CF1` to `CF6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
