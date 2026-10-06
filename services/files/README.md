# Files

Status: library in progress. Uploads, completion with size and digest checks, dedupe, downloads, references,
delete rules, scanning hook, retention and legal holds exist as a Python library with tests against a
filesystem store, S3 (moto and LocalStack) and Azure Blob (Azurite). There is no HTTP server and no
PostgreSQL repository yet.

| Item | Detail |
|---|---|
| Purpose | Every file byte in the platform goes through this service. Other services store and pass `file_id`s, never bytes or storage keys. Bytes travel from the browser to object storage on a short-lived presigned URL; the service holds metadata. |
| Owns | File metadata (PostgreSQL, later; an in-memory repository today) and the objects in the files bucket or container. |
| Depends on | An object store (Amazon S3 or S3-compatible with Object Lock, or Azure Blob Storage with version-level immutability), a malware scanner (ClamAV, Defender or ICAP behind `Scanner`), `services/shared` once it exists. |
| Console contract | `apps/console/src/lib/types/files.ts`. `ops_files.models` mirrors it in snake_case and accepts the camelCase JSON. |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.

## Run the checks

Needs Python 3.12 and uv. Docker runs the optional LocalStack and Azurite containers; without them those
cases skip with a reason.

```bash
cd services/files
uv sync
docker run -d --name ops-files-localstack -p 4566:4566 -e SERVICES=s3 -e S3_SKIP_SIGNATURE_VALIDATION=0 localstack/localstack:3.8
docker run -d --name ops-files-azurite -p 10000:10000 mcr.microsoft.com/azure-storage/azurite azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck --loose
uv run ruff check
uv run pyright
uv run pytest -rs
```

The failure modes the tests guard, and which backend runs each, are in `tests/README.md`.

## What exists

| Module | What it does |
|---|---|
| `ops_files.service` | `FileService`: `create_upload`, `complete_upload`, `get`, `download_url`, `add_reference`, `remove_reference`, `delete`, `record_scan` and `quarantine` (scan-result hook), `set_retention`, `set_legal_hold`. Typed refusals (`FileMissingError`, `SizeMismatchError`, `DigestMismatchError`, `QuarantinedError`, `FileReferencedError`, `FileHeldError`, `FileRetainedError`, `RetentionChangeError`, …) |
| `ops_files.storage.base` | `ObjectStore` protocol, `PresignedRequest`, `ObjectInfo`, storage errors, the key pattern, retention-change rule |
| `ops_files.storage.s3` | boto3 adapter: presigned PUT, SSE-KMS by key alias, Object Lock retention and legal hold, delete of every version |
| `ops_files.storage.azure_blob` | azure-storage-blob adapter: user delegation SAS, encryption scope, version-level immutability policy and legal hold |
| `ops_files.storage.local` | Filesystem adapter for development and tests, with the same signing, size, overwrite, retention and hold rules |
| `ops_files.repository` | `FileRepository` protocol and `InMemoryFileRepository` |
| `ops_files.scanning` | `Scanner` protocol and `EicarScanner`, a fake that detects the EICAR test string |
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

## Decisions

| Decision | Why |
|---|---|
| S3 uploads use a presigned PUT with signed `Content-Length`, `Content-Type`, `If-None-Match: *` and SSE-KMS headers, not a presigned POST with `content-length-range` | S3 rejects any request whose headers differ from the signed ones, so the exact declared size is enforced at the edge, a different key fails the signature, and a reused URL cannot overwrite (412). A POST policy enforces a range, and its safety depends on a hand-written policy where a missing `key` condition lets the client choose the key. A PUT is also what Azure and the local store take, so the console uploads one way. Verified against LocalStack (403 for other key, other length, other type; 412 for overwrite) |
| Azure SAS tokens are user delegation SAS; account-key SAS is refused unless `allow_account_key_sas` is set (tests only) | A user delegation key comes from Entra ID, expires in at most seven days and can be revoked without rotating the account key that every other client uses |
| Azure upload SAS grants `create` only | Azure refuses a write to an existing blob under that permission, so a reused URL cannot replace scanned content (verified on Azurite: 403 with `create` only, 201 with `write` added) |
| Size is checked again in `complete_upload` on every backend | An Azure SAS cannot bind the request length, and S3-compatible stores differ in what they verify |
| The digest is computed by streaming the stored object | A client-declared digest is a claim; dedupe on a claim would let a caller who knows another file's hash obtain it |
| Dedupe returns the existing file and discards the new upload | Matches the console's `CompletedUpload.deduplicated`. The second upload's name, purpose and retention class are not kept; the caller adds its reference to the returned file |
| `delete` on S3 removes every version of the key | In a versioned bucket (Object Lock requires versioning) a plain delete adds a delete marker and the bytes remain |
| Retention is never shortened, including S3 governance mode | S3 lets a caller with `s3:BypassGovernanceRetention` shorten governance retention; the service never uses that permission, which keeps the three backends identical |

## Configuration

`FilesConfig` (`ops_files.service`), plus one store config.

| Setting | Meaning |
|---|---|
| `retention_classes`, `default_retention_class` | The console's `RetentionClass` list. A WORM class must have a period |
| `upload_url_seconds` | Upload URL lifetime (default 900) |
| `max_download_url_seconds` | Longest download link (default 300); must not exceed the store's cap |
| `max_upload_bytes`, `limits` | Default size cap and per-purpose `PurposeLimit` (size and allowed extensions) |
| `environment`, `region`, `encryption` | Reported on the admin `StorageLocation` |
| `S3Config.bucket`, `kms_key_id`, `max_url_seconds` | Bucket (Object Lock enabled), KMS key id or alias, signing cap (at most seven days) |
| `AzureBlobConfig.container`, `encryption_scope`, `max_url_seconds`, `allow_account_key_sas` | Container (version-level immutability enabled), encryption scope, signing cap, tests-only account-key switch |

## Not built yet

| Gap | Note |
|---|---|
| HTTP API and PostgreSQL repository | The repository needs a unique index on (team, digest) for available files so two concurrent completions cannot both store the content |
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
