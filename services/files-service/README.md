# Files service

File bytes for every service on :8750: upload tickets (signed storage URLs on S3 and Azure Blob, a streaming proxy
route on the local backend), completion with type sniffing, sha256 and per-team dedupe, metadata, downloads, delete,
legal holds, and internal routes other services call with a service token (server write, read, references, scan
results). Storage adapters come from `packages/ops_storage`; services call it through `packages/ops_files_client`.
Full docs: `docs/services/files-service/overview.md`; test list: `docs/services/files-service/tests.md`.

```bash
make run        # serve on :8750 (the root `make up` starts it as `files`)
make migrate    # its own chain, version table alembic_version_files
make verify     # ruff, pyright, pytest on the test database, OpenAPI gate; LocalStack and Azurite tests skip
```
