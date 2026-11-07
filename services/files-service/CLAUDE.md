# files-service: working rules

Status: current.

The files service (`ops_files`, :8750) holds every file byte in the platform. It owns upload tickets, completion
with type sniffing and sha256 dedupe per team, file metadata, versions, references from other services, legal holds,
downloads, delete, the scan hook, and each tenant's storage settings (where each upload purpose stores its bytes,
its limits and its credential). Other services store and pass `file_id`s, never bytes or storage keys, and reach it
through `packages/ops_files_client` with a service token. Storage backends (local filesystem, S3, Azure Blob) come
from `packages/ops_storage`.

What is read from a file (extractions, document types) belongs to documents-service. files-service calls no other
service when it deletes a file; it reports file events to agents-service through its outbox. Shared service rules:
[services/CLAUDE.md](../CLAUDE.md). Cross-folder rules: [root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_files/app.py` | The FastAPI app: routes for people and the internal routes services call |
| `src/ops_files/tenant_files.py` | The hosted service's use cases, each held to the caller's tenant and team |
| `src/ops_files/service.py`, `repository.py` | `FileService`, the only code that reads or writes bytes; kept for in-process callers that have not moved to the client |
| `src/ops_files/models.py` | Domain types mirroring `apps/console/src/lib/types/files.ts` |
| `src/ops_files/settings.py`, `secrets.py` | Storage settings per purpose and storage credentials sealed with AES-256-GCM |
| `src/ops_files/sniffing.py`, `scanning.py` | What the bytes are (puremagic), and the `Scanner` contract for ClamAV, Defender or ICAP |
| `src/ops_files/store/` | All database code (`store/files.py:48` names the tenant role `ops_files_tenant`), the outbox relay, read requests |
| `migrations/` | Its own chain, version table `alembic_version_files` |
| `tests/` | Uploads, downloads, lifecycle, isolation, storage settings, the client; S3 on moto in-process, LocalStack and Azurite when running |

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Serve in the foreground on :8750 | `make stop` (the `make up` copy), then `make run` |
| Its tests | `make test`, or from the root `make test PKG=services/files-service` |
| One test file | `PYTEST_ADDOPTS=tests/test_sniffing.py make test`: this Makefile ignores `T=` |
| Lint, types, OpenAPI | `make lint`, `make typecheck`, `make openapi-check` (`make openapi` to regenerate) |
| Apply the chain | `make migrate` |
| Background process | `make logs FOLLOW=0`, `make health` |

The LocalStack and Azurite tests skip unless those containers answer; the commands that start them are in
[docs/services/files-service/tests.md](../../docs/services/files-service/tests.md). `make up` runs the stack's copy
with scanning off (`OPS_FILES_SCANNING=off`).

## Try it as a person

```bash
make api GET /v1/files AS=builder SVC=files Q='pageSize=5'
make api GET /v1/files/limits AS=viewer SVC=files
```

Uploads go through a presigned ticket and a second request with the bytes, so test them through a use case or the
console's `FileUpload` component rather than `make api`. Reference: [make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| Bytes in one place | No other service writes bytes to storage; a new caller uses `ops_files_client` |
| Team-held | Every file is the caller's team's; another team's file is missing on every route (uc-094) |
| Delete is guarded | `DELETE /v1/files/{id}` answers 409 while the file is referenced, held, retained or locked in storage; downloads need a clean scan |
| Settings are probed | A storage settings save writes, reads and deletes a small object on every new or changed target and is refused naming the purpose when the probe fails |
| Credentials | Kept by name, sealed, never returned |

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/files-service/overview.md](../../docs/services/files-service/overview.md) | Purpose, routes, rules, backends |
| [docs/services/files-service/tests.md](../../docs/services/files-service/tests.md) | The test list and the backend containers |
| [docs/usecases/files-service/](../../docs/usecases/README.md) | 3 use cases |
| [openapi.json](openapi.json) | The API; `openapi-untyped.txt` lists the one untyped operation still allowed |
