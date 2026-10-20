"""agents-service's one door to its database: every table and query lives in this package as repository classes that
declare the guarantees they rely on (`requires`, ops_store.Guarantee). Routers and the runtime call repositories and
never build SQL themselves (docs/architecture/data.md)."""
