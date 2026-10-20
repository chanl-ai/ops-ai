# Another team's file is missing on every files-service route

Status: passing. Id: `uc-094`. Service: `files-service`. Layers: api. Card: c-087.

## Preconditions

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

## Non-vacuous check

Step 3. With the team check removed from `_owned` in `services/files-service/src/ops_files/tenant_files.py`, Sam reads
and deletes the file; this was seen failing (`.codeloop/evidence/087/`).
