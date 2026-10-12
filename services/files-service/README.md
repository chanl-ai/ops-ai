# Files service

File bytes for every service: uploads with size and digest checks, dedupe, downloads, references, scanning hook,
retention and legal holds. Service logic with tests, no HTTP server yet; storage backends come from
`packages/ops_storage` (filesystem, S3, Azure Blob). Full docs: `docs/services/files-service/overview.md`; test
list: `docs/services/files-service/tests.md`.

```bash
make verify     # ruff, pyright, pytest; LocalStack and Azurite tests skip without those containers
```
