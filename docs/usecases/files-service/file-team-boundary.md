# Another team's file is missing on every files-service route

Status: passing. Id: `uc-094`. Service: `files-service`. Layers: api, ui (ui layer an earlier change). Card: an earlier change.

## Preconditions

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Sam, in Security, opens Priya's file's address and is told it is not found, with no team or file named | ui | 3 | 3 |
| S2 | Security's Files list does not hold it | ui | 5 | 5 |
| S3 | Priya, in Operations, opens it and sees it | ui | 8 | 8 |

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| platform-service with its dev seed (Priya Shah admin of `team_ops`, Sam Adeyemi admin of `team_security`) | started by the script (`platform()`) |
| files-service on its own chain, local backend, platform tokens, scanning `off` | started by the script (`files(dir, scanning="off")`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens an upload; Sam sends bytes to it and completes it | 404 and 404 |
| 2 | Priya sends the bytes and completes | the file is stored |
| 3 | Sam gets it, asks for a link, downloads and deletes it | 404 on each |
| 4 | Sam places a legal hold on it | skipped, "not found" |
| 5 | Sam lists his team's files | it is not there |
| 6 | Sam names `team_ops` in `X-Team-Id` | refused: he is not a member |
| 7 | A service token for another tenant reads it with `team=team_ops` | 404 |
| 8 | Priya gets it | 200 |

The answer is 404, never 403, so a caller cannot learn that a file id exists outside its team.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `files-service/scripts/test-uc-094-api.py` | passing |
| ui | `files-service/scripts/test-uc-094-ui.mjs` | passing: the file's page as Priya and as Sam, and Security's Files list |

## Non-vacuous check

Step 3. With the team check removed from `_owned` in `services/files-service/src/ops_files/tenant_files.py`, Sam reads
and deletes the file; this was seen failing.
