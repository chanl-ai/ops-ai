# documents-service

What is read from a file: extractions and their corrections, document types with versions, samples and test runs, and
(next) page layouts, templates and classification. It never holds file bytes: it reads them through files-service as
the caller's team, so a file the team cannot see is not found.

Full description, routes, rules and the sample documents' test cases: `docs/services/documents-service/overview.md`.

| Task | Command |
|---|---|
| Serve on :8760 | `make run` (`uv run python -m ops_documents`) |
| Apply its migrations (`alembic_version_documents`) | `make migrate` |
| Lint, typecheck, tests, OpenAPI gate | `make verify` |
| Seed the demo's document types | `uv run python scripts/seed_document_types.py` |
