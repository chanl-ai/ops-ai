# A member stores a file once and it is downloaded, held and deleted under its rules

Status: passing. Id: `uc-093`. Service: `files-service`. Layers: api. Card: c-087.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| platform-service with its dev seed (James Richardson builder and Priya Shah admin of `team_ops`) | started by the script (`platform()`) |
| files-service on its own chain, local backend, platform tokens, scanning `hook` | started by the script (`files(dir)`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James asks for an upload ticket for a PDF | the ticket's URL is files-service's own content route (local backend) |
| 2 | He sends the bytes there and completes | 204, then the file with its sha256, retention class `standard`, not deduplicated |
| 3 | He gets the file | metadata, scan `pending`, one version |
| 4 | He asks for a download link | 423: not scanned clean |
| 5 | A scanner posts `clean` to the scan hook with its service token | the file is `clean` |
| 6 | He asks again and downloads | the same bytes, as an attachment |
| 7 | He lists his own uploads | the file is there |
| 8 | He places a legal hold | 403 |
| 9 | Priya places it; James deletes | the hold is placed; delete answers 409 |
| 10 | Priya releases it; James deletes and gets it | 204, then 404 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `files-service/scripts/test-uc-093-api.py` | passing |

## Non-vacuous check

Steps 4 and 9. With `_readable` in `services/files-service/src/ops_files/tenant_files.py` not checking the scan, step 4
answers 200. With the hold check removed from `delete`, step 9 fell through to storage, whose legal hold refused it as an unhandled 500; storage refusals now answer 409 too. Both were seen failing
(`.codeloop/evidence/087/`).
