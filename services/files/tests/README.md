# files tests

Status: current.

One test per failure mode. The list comes first; each row names the test that guards it. Every test runs
once per storage backend through the `harness` fixture in `conftest.py`:

| Backend | When it runs | Limits |
|---|---|---|
| `local` | Always | none; the filesystem store enforces every rule |
| `s3-moto` | Always (moto server in-process) | Moto accepts any presigned signature, so U1 and U3 skip |
| `s3-localstack` | When LocalStack answers on `OPS_FILES_LOCALSTACK_URL` (default `http://127.0.0.1:4566`) | none found; it verifies SigV4 signatures, signed headers, `If-None-Match` and Object Lock |
| `azure-azurite` | When Azurite answers on `OPS_FILES_AZURITE_URL` (default `http://127.0.0.1:10000/devstoreaccount1`) | Azurite returns "not implemented" for immutability policies and legal holds, so L2, L4 and L5 skip. Uses an account-key SAS, because Azurite has no Entra ID to issue a user delegation key |

```bash
docker run -d --name ops-files-localstack -p 4566:4566 -e SERVICES=s3 -e S3_SKIP_SIGNATURE_VALIDATION=0 localstack/localstack:3.8
docker run -d --name ops-files-azurite -p 10000:10000 mcr.microsoft.com/azure-storage/azurite azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck --loose
uv run pytest -rs
```

Without the two containers the LocalStack and Azurite cases skip and say why.

## Upload

| # | Failure mode | Test |
|---|---|---|
| U1 | A presigned upload URL works for a different key | `test_upload.py::test_upload_url_bound_to_its_key` |
| U2 | An upload larger than the declared size is accepted | `test_upload.py::test_upload_larger_than_declared_refused` |
| U3 | The upload URL is reused after completion and replaces content that was already hashed and scanned | `test_upload.py::test_upload_url_cannot_replace_completed_content` |
| U4 | Bytes stored with a content type other than the declared one are accepted | `test_upload.py::test_content_type_other_than_declared_refused` |
| U5 | The stored bytes differ from the digest the client declared and nobody notices | `test_upload.py::test_digest_mismatch_detected` |
| U6 | Dedupe across teams hands one team another team's object | `test_upload.py::test_dedupe_never_crosses_teams` |
| U7 | Identical content in one team is stored twice | `test_upload.py::test_dedupe_within_team_reuses_object` |
| U8 | A user-supplied file name reaches the storage key (path traversal) | `test_upload.py::test_user_filename_never_in_storage_key` |

## Download

| # | Failure mode | Test |
|---|---|---|
| D1 | A download link serves bytes other than those uploaded (presign, upload, complete and download unwired) | `test_download.py::test_download_serves_the_uploaded_bytes` |
| D2 | A quarantined file can be downloaded, at upload or after the scan hook flags it | `test_download.py::test_download_of_quarantined_file_refused` |
| D3 | A file that has not been scanned can be downloaded | `test_download.py::test_download_before_scan_refused` |
| D4 | A team downloads another team's file | `test_download.py::test_cross_team_download_refused` |
| D5 | A signed GET lives longer than the configured maximum (read from the URL, not the service) | `test_download.py::test_signed_get_lifetime_capped` |

## Lifecycle

| # | Failure mode | Test |
|---|---|---|
| L1 | A referenced file is deleted | `test_lifecycle.py::test_delete_while_referenced_refused` |
| L2 | A file under legal hold is deleted, through the service or directly in storage | `test_lifecycle.py::test_delete_while_held_refused` |
| L3 | A file is deleted inside a keep-until-end retention period | `test_lifecycle.py::test_delete_within_retention_refused` |
| L4 | Retention on an immutable file is shortened or removed through the service | `test_lifecycle.py::test_retention_not_shortened_on_locked_file` |
| L5 | Storage accepts an earlier retention date or a weaker mode on a locked object | `test_lifecycle.py::test_storage_refuses_shorter_retention` |
| L6 | Delete leaves earlier versions in a versioned bucket, so the bytes survive | `test_lifecycle.py::test_delete_removes_every_version` |
| L7 | Copy overwrites an existing object | `test_lifecycle.py::test_copy_never_overwrites` |

## Results

`uv run pytest -rs` with both containers running: 87 passed, 5 skipped.

| Backend | Failure modes run | Skipped |
|---|---|---|
| `local` | 20 of 20 | none |
| `s3-moto` | 18 of 20 | U1, U3 |
| `s3-localstack` | 20 of 20 | none |
| `azure-azurite` | 17 of 20 | L2, L4, L5 |

## Seen failing

Each test below was run against a deliberately broken implementation, seen failing for the stated reason,
and the code restored.

| Test | Broken by | Failure seen |
|---|---|---|
| U3 | Dropping `IfNoneMatch` from the S3 presign, granting `write` with `create` on the Azure SAS, removing the local overwrite check | `assert 200 >= 400` on local and LocalStack, `assert 201 >= 400` on Azurite |
| U3 | (found by the test, not seeded) the first version sent the ticket's `If-None-Match` header on the reuse, so it passed with the S3 guard removed | the test now drops that header, as a reuser would |
| U2 | Removing both size checks in `complete_upload` | failed on moto and Azurite; local and LocalStack still refused at the edge |
| U5 | Skipping the declared-digest comparison | `DID NOT RAISE DigestMismatchError` on all four |
| U6 | Dropping the team filter from `find_available_by_digest` | `assert True is False` (`deduplicated`) on all four |
| U8 | Appending the display name to the key | `re.fullmatch(...)` returned `None` on `../../../etc/passwd`; `InvalidKeyError` on the others |
| D2 | Removing the quarantine and scan-status checks in `download_url` | `DID NOT RAISE QuarantinedError` on all four |
| L2 | Removing the legal-hold check in `delete` | failed on local, moto and LocalStack (storage raised `ObjectLockedError` instead) |
| L5 | Making `check_retention_change` return early | failed on local, moto and LocalStack |
