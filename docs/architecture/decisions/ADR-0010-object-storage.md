# ADR-0010 Object storage

Status: accepted (draft for review).

## Context

ADR-0006 puts evidence bundles, mail attachments, payloads and uploads in WORM-capable object storage but
does not say which product or how the platform talks to it. Banks run on different clouds: some are on
AWS, some on Azure, some on-premises with an S3-compatible appliance. The platform needs one Files API
(`../../specs/10-files.md`) whose behaviour does not change with the bank's choice: presigned direct
uploads, server-side encryption with the bank's key, retention, legal hold and storage-enforced
immutability for evidence.

The three storage properties ADR-0006 requires are available on both major clouds:

| Property | Amazon S3 | Azure Blob Storage |
|---|---|---|
| Direct browser upload on a signed link for one object | Presigned PUT URL ([AWS][s3-presign]) | User delegation SAS ([Microsoft][az-sas]) |
| Encryption with the bank's key | SSE-KMS with a customer-managed key | Encryption scope backed by Key Vault ([Microsoft][az-scope]) |
| Nobody can delete or shorten retention, including the root account | Object Lock compliance mode ([AWS][s3-lock]) | Locked time-based immutability policy ([Microsoft][az-immut]) |
| Legal hold with no expiry | Object Lock legal hold | Legal hold on the version or container |

## Options

| Option | Fit for AWS banks | Fit for Azure banks | Fit for on-premises | What it costs | Score |
|---|---|---|---|---|---|
| S3 API only, with S3-compatible gateways in front of Azure or on-premises stores | Native | A gateway in front of Blob Storage; immutability and SAS semantics are translated, and Object Lock compliance mode must be proven through the gateway | Native where the appliance implements Object Lock | One adapter; a gateway to run and assess for every non-AWS bank | 3 |
| Azure Blob only | Not acceptable to an AWS bank | Native | Rare | One adapter; excludes AWS banks | 1 |
| **Storage adapter with two first-class backends (S3 API and Azure Blob)** | Native | Native | S3 adapter against the appliance, if it implements Object Lock | Two adapters behind one protocol, each tested against its emulator and a real account | **5** |

The S3-gateway option looks cheaper but moves the hard part (proving WORM, legal hold and signed-link
behaviour) into a component the bank's risk function would have to assess separately. The adapter
keeps each backend's native controls, which are the ones auditors already know.

## Decision

| Item | Choice |
|---|---|
| Interface | One `ObjectStore` protocol in the files service: presign PUT and GET for one key, read object info, set retention, set and clear legal hold, delete every version |
| Backends | `s3` (Amazon S3 and S3-compatible stores with Object Lock) and `azure_blob`, both first class; a filesystem adapter with the same rules for development and tests |
| Choice per environment | Settings → Storage names the backend, bucket or container, region, key and immutability setting for each environment, and the Integrations connection that signs in |
| Credentials | Held only by the files service through that connection. No other service can sign a URL |
| Keys | `{team}/{purpose}/{yyyy}/{mm}/{fileId}`; evidence under `evidence/`. Display names never reach a key |
| Evidence | Compliance-mode Object Lock or a locked immutability policy; production cannot be saved without it |

The library is in `services/files/` (`ops_files.storage.s3`, `ops_files.storage.azure_blob`,
`ops_files.storage.local`). Its tests run the same failure modes against moto, LocalStack and Azurite
(`services/files/tests/README.md`).

## Consequences

| Consequence | Detail |
|---|---|
| Every storage feature is built twice | A new storage capability (for example multipart upload) needs both adapters and both test runs before it ships |
| Behaviour is the same on either cloud | The console, the Files API and the other services never know which backend is in use |
| The second backend is tested but not operated in phase 1 | Production runs on one backend; the other is exercised in CI and in development |
| S3-compatible appliances are in scope only with Object Lock | An appliance without compliance-mode Object Lock cannot hold evidence |

### What would change this decision

- The bank standardises on a third store with its own immutability API (for example a Google Cloud
  bucket with a locked retention policy). Then a third adapter behind the same protocol.
- A bank's network forbids browsers from reaching storage. Then the files service fronts storage with a
  streaming proxy using the same tickets; the adapter stays.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| The bank's cloud of choice only, one backend in production; both adapters built and tested in CI; WORM evidence, legal hold, SSE with the bank's key, presigned upload and download | Second backend in production, migration between backends, multipart upload, cross-region replication inside the jurisdiction |

## Sources

[s3-presign]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
[s3-lock]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
[az-sas]: https://learn.microsoft.com/en-us/rest/api/storageservices/create-user-delegation-sas
[az-scope]: https://learn.microsoft.com/en-us/azure/storage/blobs/encryption-scope-overview
[az-immut]: https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-storage-overview
