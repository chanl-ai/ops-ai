# A Security admin sets where each purpose stores its files and with which credential

Status: current. Id: `uc-105`. Service: `console`. Layers: ui. Card: c-100.

An admin on the Security team opens Settings, Storage and points each upload purpose at a target: the files
service's own disk, S3 or Azure Blob, with a bucket or container, region, endpoint, credential by name and upload path.
A credential's values go to files-service once, are kept encrypted and are never shown or returned again. A save is a
new version, made with the Save button only, and every new or changed target is tested first. Design:
[files-service design](../../services/files-service/overview.md); interview: c-100 Q1-Q5.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Sam Adeyemi, admin on team_security | platform-service dev seed |

The script starts the stack with platform sign-in and files-service; no cloud account is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open Settings, Storage | "Not saved yet" |
| 2 | Add credential `BANK_S3` with an access key and a secret | Listed by name; the secret is in no response and not on the page |
| 3 | Set a default target, add a Chat attachment target in folder `chat-store`, Save | PUT 200; "Version 1" |
| 3b | Read the notice at the top, then press Test on a target | the deployment's scanning mode reads as a sentence ("Files are not scanned."), never "Scanning is hook"; the test draws Write, Read and Delete as a step list, each done |
| 4 | Upload a chat attachment | It is stored in `chat-store` |
| 5 | Point the chat target at an unreachable S3 endpoint with `BANK_S3`, Save | 422 shown on the chat target; the saved version stays 1 with the chat target on disk |
| 6 | Fail the credentials request, reload | the credentials section says it could not load, with Try again; it does not say "No credentials yet" |
| 7 | Remove `BANK_S3` | a confirm names it; the credential is still listed until the confirm, then gone |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-105-ui.mjs` | passing |

## Non-vacuous check

Run against the page before c-116 T006, steps 3b (both checks), 6 and 7 failed (scanning read "Scanning is off, set by the deployment", no step list, "No credentials yet" under a failed request). Step 5 reads the settings back from files-service after the refused save. Skipping the probe in
`StorageSettings.save` (`services/files-service/src/ops_files/settings.py`) saves version 2 and fails it, as
`test_a_failing_probe_leaves_the_saved_version_unchanged` also shows.
