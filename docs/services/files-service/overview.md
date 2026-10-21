# Files

Status: first slice built (c-087). files-service runs on :8750 (`make up` starts it as `files`) with its own
PostgreSQL tables and migration chain, tenant and team scoped routes, platform tokens verified locally, and a typed
client for other services (`packages/ops_files_client`). The local backend works on the dev stack through proxy
routes; S3 and Azure Blob sign upload and download URLs and move bytes through obstore, covered by unit tests on
fakes. The sync library (`FileService`) stays for the in-process callers that have not moved yet. Design:
this page.

| Item | Detail |
|---|---|
| Purpose | Every file byte in the platform goes through this service. Other services store and pass `file_id`s, never bytes or storage keys. Bytes travel from the browser to object storage on a short-lived presigned URL; the service holds metadata. |
| Owns | File metadata in its tables (`files`, `file_blobs`, `file_versions`, `file_references`, `file_legal_holds`, `file_idempotency`; chain `alembic_version_files`) and the objects in the files bucket or container. |
| Depends on | An object store (Amazon S3 or S3-compatible with Object Lock, or Azure Blob Storage with version-level immutability), a malware scanner (ClamAV, Defender or ICAP behind `Scanner`), `services/shared` once it exists. |
| Console contract | `apps/console/src/lib/types/files.ts`. `ops_files.models` mirrors it in snake_case and accepts the camelCase JSON. |

What is read from a file (extractions, document types) is documents-service's, which reads bytes through this
service's client as the caller's team (`docs/services/documents-service/overview.md`). files-service calls no other
service when it deletes a file.

The service map that applies to every service is `docs/architecture/service-map.md`; trust rules are in
`docs/architecture/identity-and-tenancy.md`.

## Run the checks

Needs Python 3.12 and uv. Docker runs the optional LocalStack and Azurite containers; without them those
cases skip with a reason.

```bash
cd services/files-service
uv sync
docker run -d --name ops-files-localstack -p 4566:4566 -e SERVICES=s3 -e S3_SKIP_SIGNATURE_VALIDATION=0 localstack/localstack:3.8
docker run -d --name ops-files-azurite -p 10000:10000 mcr.microsoft.com/azure-storage/azurite azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck --loose
uv run ruff check
uv run pyright
uv run pytest -rs
```

The failure modes the tests guard, and which backend runs each, are in `docs/services/files-service/tests.md`.

## Hosted service

| Route | What it does |
|---|---|
| `POST /v1/files/uploads` | Ticket: a signed PUT (S3, Azure) or, on the local backend and in proxy mode, this service's content route. `Idempotency-Key`: a retry gets the same file id; the key with another request is 409 |
| `PUT /v1/files/uploads/{id}/content` | Proxy upload: the body streamed into storage, refused past the declared size or with another type (409) |
| `POST /v1/files/uploads/{id}/complete` | Size, the type proven from the first 8 KB (puremagic) and checked against the purpose's allowed types, sha256 from the stored bytes, dedupe through `file_blobs`; 409 on a size or digest mismatch and 415 on a refused type, the object deleted either way. The file is recorded as the proven type. Repeated or concurrent completes of one ticket return the same file |
| `GET /v1/files`, `GET /v1/files/{id}` | The team's available files (`uploadedBy=me`, `purpose`, `refType`, `refId`), and one file's detail; the storage location only for admins of the file's team (files 8.1) |
| `POST /v1/files/{id}/download-url`, `GET /v1/files/{id}/content` | A short-lived link (signed GET, or the proxy route); 423 until scanned clean |
| `DELETE /v1/files/{id}` | 409 while referenced, held, retained, or locked in storage |
| `POST /v1/files/legal-hold` | `{ids, hold, reason}`; an admin of the team only (403), sets the storage-level hold too |
| `POST /v1/files`, `GET /v1/files/{id}[/content]` | Server write (with `Idempotency-Key`) and reads for services, with a service token and `team` |
| `POST`, `DELETE /v1/files/{id}/references...` | Attach (409 unless clean) and detach |
| `POST /v1/files/scan-results` | The scan hook: a scanner's verdict for a file of its token's tenant |

| Setting | Meaning |
|---|---|
| `OPS_FILES_PORT`, `OPS_FILES_URL` | Port (8750) and the base URL other services use |
| `OPS_FILES_DIR` | Local backend root (`.data/files`) |
| `OPS_FILES_PUBLIC_URL` | The service's public base, path included (e.g. `https://ops.example/api/files`), when a proxy serves it under a path it strips; upload and download URLs are built on it. Unset, the request's own base |
| `OPS_FILES_SCANNING` | `hook` by default (pending until the scan hook), `off` (dev only, set by `make up`: clean at completion, files 5.3.1; files-service refuses it outside dev), `eicar` (inline EICAR engine) |

```bash
make up && make health              # files on :8750 beside the other services
make usecase-test UC=uc-093         # upload, complete, get, scan hook, download, hold, delete
make usecase-test UC=uc-094         # another team's file is 404 everywhere
```

## What exists

| Module | What it does |
|---|---|
| `ops_files.service` | `FileService`: `create_upload`, `complete_upload`, `get`, `download_url`, `add_reference`, `remove_reference`, `delete`, `record_scan` and `quarantine` (scan-result hook), `set_retention`, `set_legal_hold`. Typed refusals (`FileMissingError`, `SizeMismatchError`, `DigestMismatchError`, `QuarantinedError`, `FileReferencedError`, `FileHeldError`, `FileRetainedError`, `RetentionChangeError`, …) |
| `ops_storage.base` | `ObjectStore` protocol, `PresignedRequest`, `ObjectInfo`, storage errors, the key pattern, retention-change rule |
| `ops_storage.s3` | boto3 adapter: presigned PUT, SSE-KMS by key alias, Object Lock retention and legal hold, delete of every version |
| `ops_storage.azure_blob` | azure-storage-blob adapter: user delegation SAS, encryption scope, version-level immutability policy and legal hold |
| `ops_storage.local` | Filesystem adapter for development and tests, with the same signing, size, overwrite, retention and hold rules |
| `ops_files.repository` | `FileRepository` protocol and `InMemoryFileRepository` |
| `ops_files.scanning` | `Scanner` protocol and `EicarScanner`, a fake that detects the EICAR test string |
| `ops_files.tenant_files` | `TenantFiles`: the hosted service's async use cases, tenant and team scoped |
| `ops_files.app`, `ops_files.__main__` | FastAPI app and entry point on `settings.files_port` |
| `ops_files.store` | Tables and `FilesStore`, portable SQL; `file_blobs` holds the dedupe guarantee |
| `ops_files.sniffing` | `prove`: the type the bytes are (puremagic); the declared type and the name only choose among the types the bytes allow, text is bytes with no signature and no control characters, and binary with no known signature is refused |
| `ops_storage.streaming` | The obstore byte path every adapter uses: create-only streamed writes, streamed and ranged reads |
| `packages/ops_files_client` | `FilesClient` for other services: write, get, stream, read, attach, detach, report a scan |
| `ops_files.models` | Pydantic models for `FileRecord`, `FileDetail`, `UploadRequest`, `UploadTicket`, `CompletedUpload`, `DownloadLink`, `RetentionClass`, `PurposeLimit` |

## Rules the code enforces

| Rule | Where |
|---|---|
| Keys are `{team}/{purpose}/{yyyy}/{mm}/{file_id}`. The name a person gives a file is display metadata and never reaches a key; every store refuses a key outside `KEY_PATTERN` | `service.create_upload`, `storage.base.validate_key` |
| Team comes from the caller's context. A file in another team is reported as missing | `service._owned` |
| `complete_upload` checks the stored size and type against the declaration, computes sha256 from the stored bytes, compares any declared digest, and deletes the object on a mismatch | `service.complete_upload` |
| Dedupe compares the digest the service computed, within one team only. A duplicate's upload is discarded and the existing file returned with `deduplicated: true` | `service.complete_upload`, `repository.find_available_by_digest` |
| Downloads need a clean scan. Infected and unscanned files are refused; a scan that flags a file later marks its references blocked | `service.download_url`, `service._apply_scan` |
| A signed GET lasts at most `max_download_url_seconds` (the console's `signedUrlMinutes`); each store also has its own cap | `service.download_url`, `storage.base.check_expiry` |
| Delete is refused while referenced, held, or inside a keep-until-end or WORM period; storage refuses held and retained deletes too | `service.delete`, each store's `delete` |
| Retention only moves later and only gets stricter, in the service and in every store | `service.set_retention`, `storage.base.check_retention_change` |
| WORM classes set compliance-mode retention in storage; the file becomes `immutable` | `service.complete_upload`, `service.set_retention` |
| `file.deleted` and `file.read_requested` are written to `files_outbox` in the transaction that makes the change, and a relay delivers them to agents-service at least once; delivered rows are pruned after 7 days, rows still being retried are kept | `store.event_relay`, `ops_store.outbox.Relay` |

## Decisions

| Decision | Why |
|---|---|
| S3 uploads use a presigned PUT with signed `Content-Length`, `Content-Type`, `If-None-Match: *` and SSE-KMS headers, not a presigned POST with `content-length-range` | S3 rejects any request whose headers differ from the signed ones, so the exact declared size is enforced at the edge, a different key fails the signature, and a reused URL cannot overwrite (412). A POST policy enforces a range, and its safety depends on a hand-written policy where a missing `key` condition lets the client choose the key. A PUT is also what Azure and the local store take, so the console uploads one way. Verified against LocalStack (403 for other key, other length, other type; 412 for overwrite) |
| Azure SAS tokens are user delegation SAS; account-key SAS is refused unless `allow_account_key_sas` is set (tests only) | A user delegation key comes from Entra ID, expires in at most seven days and can be revoked without rotating the account key that every other client uses |
| Azure upload SAS grants `create` only | Azure refuses a write to an existing blob under that permission, so a reused URL cannot replace scanned content (verified on Azurite: 403 with `create` only, 201 with `write` added) |
| Size is checked again in `complete_upload` on every backend | An Azure SAS cannot bind the request length, and S3-compatible stores differ in what they verify |
| The digest is computed by streaming the stored object | A client-declared digest is a claim; dedupe on a claim would let a caller who knows another file's hash obtain it |
| Dedupe returns the existing file and discards the new upload | Matches the console's `CompletedUpload.deduplicated`. The second upload's name, purpose and retention class are not kept; the caller adds its reference to the returned file |
| A file a document type is tested against has the purpose `document_type_sample` (c-379), shown as "Document type sample" | The documents seed uploaded its samples as case attachments, so Files showed 66 sample PDFs as email attachments. Dedupe keeps the first upload's purpose, so re-running the seed cannot relabel them; `files_0010` gives the purpose to case and chat attachments kept only by `test_set` references (documents-service's sample references). When a sample's bytes are uploaded again with another purpose (a mailed attachment), dedupe gives the file that purpose (c-380); an attachment uploaded again as a sample stays the attachment |
| `delete` on S3 removes every version of the key | In a versioned bucket (Object Lock requires versioning) a plain delete adds a delete marker and the bytes remain |
| Retention is never shortened, including S3 governance mode | S3 lets a caller with `s3:BypassGovernanceRetention` shorten governance retention; the service never uses that permission, which keeps the three backends identical |

## Configuration

`FilesConfig` (`ops_files.service`), plus one store config.

| Setting | Meaning |
|---|---|
| `retention_classes`, `default_retention_class` | The console's `RetentionClass` list. A WORM class must have a period |
| `upload_url_seconds` | Upload URL lifetime (default 900) |
| `max_download_url_seconds` | Longest download link (default 300); must not exceed the store's cap |
| `max_upload_bytes`, `limits` | Default size cap and per-purpose `PurposeLimit` (size, checked at the ticket, and allowed extensions, checked at completion against the proven type) |
| `environment`, `region`, `encryption` | Reported on the admin `StorageLocation` |
| `S3Config.bucket`, `kms_key_id`, `max_url_seconds` | Bucket (Object Lock enabled), KMS key id or alias, signing cap (at most seven days) |
| `AzureBlobConfig.container`, `encryption_scope`, `max_url_seconds`, `allow_account_key_sas` | Container (version-level immutability enabled), encryption scope, signing cap, tests-only account-key switch |

## Not built yet

| Gap | Note |
|---|---|
| Callers moved onto the service | Chat attachments (agents-service `activities/attachments.ChatFileStore`, its own `fl_` ids and 90-day retention on the object) and knowledge intake (kb-service `ops_kb.files`) still run their own stores; each moves to `FilesClient` and maps or migrates its existing ids |
| S3 and Azure from settings | `__main__` builds the local backend only; the adapters take S3 and Azure when a caller builds them |
| Multipart and resumable uploads, Uppy in the console upload component | Not started (design step 6) |
| Retention run, upload expiry, abort sweep, scan reconciliation loops | Not started; the service has no `loops()` yet |
| ClamAV, Defender and GuardDuty adapters | The hook route is built; the engines are not |
| A tenant-wide Platform admin role for legal holds | Holds need an admin of the file's team until platform-service has that role |
| Checksum header on uploads to Object Lock buckets | Real S3 requires one per PUT; moto does not, so it is untested |
| New versions of a file | `versions` holds version 1 only |
| Asynchronous scanning | The scanner runs inline in `complete_upload` when configured; `record_scan` is the hook for an engine that reports later |
| Previews, evidence export, storage settings and connection test from `files.ts` | Not started |
| Expiry sweep (delete after `delete_after` for non-WORM classes) | Not started |
| Azure immutability and legal hold against a real account | **Unverified**: Azurite does not implement them, so `AzureBlobObjectStore.set_retention`, `set_legal_hold` and the version-by-version delete have not run |
| Azure user delegation SAS against a real account | **Unverified**: Azurite has no Entra ID; tests use an account-key SAS |
| Upload and digest read the object twice when a scanner is configured | Acceptable at current sizes; one pass can feed both later |

## Licences

Runtime dependencies:

| Package | Licence | Used for |
|---|---|---|
| pydantic, pydantic-core, annotated-types, typing-inspection | MIT | Models |
| typing-extensions | PSF-2.0 | Models |
| boto3, botocore, s3transfer | Apache-2.0 | S3 |
| jmespath, six | MIT | Through botocore |
| python-dateutil | Apache-2.0 or BSD-3-Clause | Through botocore |
| urllib3 | MIT | HTTP for botocore and requests |
| azure-storage-blob, azure-core | MIT | Azure Blob |
| obstore | MIT (engine MIT or Apache-2.0) | Streamed byte path in every storage adapter |
| puremagic | MIT | Type sniffing at completion |
| cryptography | Apache-2.0 or BSD-3-Clause | Through azure-storage-blob |
| cffi | MIT-0 | Through cryptography |
| pycparser | BSD-3-Clause | Through cffi |
| isodate | BSD-3-Clause | Through azure-storage-blob |
| requests | Apache-2.0 | Through azure-core |
| certifi | MPL-2.0 | CA bundle through requests (unmodified, file-level copyleft only) |
| idna | BSD-3-Clause | Through requests |
| charset-normalizer | MIT | Through requests |

Development only: pytest (MIT), ruff (MIT), pyright (MIT), moto (Apache-2.0), boto3-stubs and
mypy-boto3-s3 (MIT), httpx (BSD-3-Clause). Test containers: LocalStack community image (Apache-2.0),
Azurite (MIT).
