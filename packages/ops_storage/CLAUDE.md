# ops_storage: working rules

Status: current.

Object storage behind one protocol (ADR-0010) with S3, Azure Blob and local filesystem backends. Package rules and
test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Public API | `ObjectStore`, `StreamingObjectStore`, `ObjectInfo`, `PresignedRequest`, `RetentionMode`, and the errors (`StorageError`, `ObjectNotFoundError`, `ObjectExistsError`, `ObjectLockedError`, `InvalidKeyError`, `ExpiryTooLongError`, `RetentionShortenError`, `UploadRejectedError`) in `base.py` |
| Backends | `local`, `s3`, `azure_blob`, plus `streaming`; import a backend module directly so only its SDK loads (`src/ops_storage/__init__.py:3`) |
| Contract | The caller picks the backend from its own settings; nothing here reads settings |
| Used by | files-service (agents-service lists it as a dependency without importing it) |
| Tests | None here; files-service's suite runs the backends: `make test PKG=services/files-service`. Its S3 and Azure Blob cases need LocalStack and Azurite and skip when those containers are not running |
| Lint, types | `uv run ruff check packages/ops_storage`, `uv run pyright packages/ops_storage` |

Design: [docs/architecture/decisions/object-storage.md](../../docs/architecture/decisions/object-storage.md).
