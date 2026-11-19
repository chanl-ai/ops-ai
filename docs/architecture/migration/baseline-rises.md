# Baseline rises on this branch

Status: current as of 2026-11-17. Compared with `origin/develop`, working tree included. A baseline is an exception list; every row in it is a site that must be fixed, not kept.

Counts are rows summed by their numbers (a row `3 x` counts 3; a JSON baseline counts its numbers and listed paths). "Rows raised" is how many rows (keys) are higher than on `origin/develop`. "(absent)" means the file does not exist on `origin/develop`, so every row in it is new on this branch.

| Baseline file | Before | After | Rows raised |
|---|---|---|---|
| `.github/standards-maintainers.txt` | (absent) | 1 | 1 |
| `access-exceptions-allowlist.txt` | 177 | 175 | 76 |
| `apps/console/scripts/data-baseline.json` | (absent) | 47 | 34 |
| `list-slice-baseline.txt` | (absent) | 5 | 3 |
| `packages/contracts/typed-boundaries-baseline.txt` | (absent) | 11 | 2 |
| `packages/ops_access/typed-boundaries-baseline.txt` | (absent) | 18 | 2 |
| `packages/ops_agent_kernel/typed-boundaries-baseline.txt` | (absent) | 164 | 11 |
| `packages/ops_checkpointer/typed-boundaries-baseline.txt` | (absent) | 4 | 1 |
| `packages/ops_documents_client/config-literals-baseline.txt` | (absent) | 4 | 3 |
| `packages/ops_documents_client/typed-boundaries-baseline.txt` | (absent) | 24 | 2 |
| `packages/ops_email/config-literals-baseline.txt` | (absent) | 2 | 2 |
| `packages/ops_email/typed-boundaries-baseline.txt` | (absent) | 18 | 5 |
| `packages/ops_engine/typed-boundaries-baseline.txt` | (absent) | 395 | 17 |
| `packages/ops_extract/config-literals-baseline.txt` | (absent) | 1 | 1 |
| `packages/ops_extract/typed-boundaries-baseline.txt` | (absent) | 120 | 11 |
| `packages/ops_files_client/config-literals-baseline.txt` | (absent) | 1 | 1 |
| `packages/ops_files_client/typed-boundaries-baseline.txt` | (absent) | 12 | 2 |
| `packages/ops_identity/config-literals-baseline.txt` | (absent) | 2 | 2 |
| `packages/ops_identity/typed-boundaries-baseline.txt` | (absent) | 33 | 7 |
| `packages/ops_ingest/typed-boundaries-baseline.txt` | (absent) | 21 | 5 |
| `packages/ops_plugin_sdk/typed-boundaries-baseline.txt` | (absent) | 63 | 8 |
| `packages/ops_policy/typed-boundaries-baseline.txt` | (absent) | 9 | 2 |
| `packages/ops_service_kit/config-literals-baseline.txt` | (absent) | 1 | 1 |
| `packages/ops_service_kit/typed-boundaries-baseline.txt` | (absent) | 51 | 9 |
| `packages/ops_signin/typed-boundaries-baseline.txt` | (absent) | 20 | 2 |
| `packages/ops_storage/typed-boundaries-baseline.txt` | (absent) | 2 | 2 |
| `packages/ops_store/tests/isolation_sites/agents-service.txt` | (absent) | 8 | 7 |
| `packages/ops_store/tests/isolation_sites/install/agents-service.txt` | (absent) | 3 | 3 |
| `packages/ops_store/tests/isolation_sites/install/models-service.txt` | (absent) | 24 | 6 |
| `packages/ops_store/tests/isolation_sites/install/platform-service.txt` | (absent) | 3 | 1 |
| `packages/ops_store/tests/isolation_sites/models-service.txt` | (absent) | 24 | 4 |
| `packages/ops_store/tests/isolation_sites/ops_engine.txt` | (absent) | 2 | 2 |
| `packages/ops_store/tests/isolation_sites/platform-service.txt` | (absent) | 3 | 1 |
| `packages/ops_store/tests/loop_health/agents.txt` | (absent) | 8 | 8 |
| `packages/ops_store/typed-boundaries-baseline.txt` | (absent) | 54 | 14 |
| `scripts/access-baselines/agents.txt` | (absent) | 1 | 1 |
| `scripts/access-baselines/console.txt` | (absent) | 1 | 1 |
| `scripts/access-baselines/tools.txt` | (absent) | 4 | 4 |
| `services/agents-service/config-literals-baseline.txt` | (absent) | 32 | 10 |
| `services/agents-service/typed-boundaries-baseline.txt` | (absent) | 2365 | 302 |
| `services/documents-service/config-literals-baseline.txt` | (absent) | 2 | 1 |
| `services/documents-service/typed-boundaries-baseline.txt` | (absent) | 244 | 14 |
| `services/files-service/typed-boundaries-baseline.txt` | (absent) | 27 | 8 |
| `services/kb-service/config-literals-baseline.txt` | (absent) | 2 | 2 |
| `services/kb-service/typed-boundaries-baseline.txt` | (absent) | 143 | 4 |
| `services/models-service/config-literals-baseline.txt` | (absent) | 2 | 2 |
| `services/models-service/typed-boundaries-baseline.txt` | (absent) | 59 | 11 |
| `services/platform-service/config-literals-baseline.txt` | (absent) | 2 | 2 |
| `services/platform-service/typed-boundaries-baseline.txt` | (absent) | 148 | 34 |
| `services/tools-service/config-literals-baseline.txt` | (absent) | 33 | 18 |
| `services/tools-service/typed-boundaries-baseline.txt` | (absent) | 939 | 57 |

Notes:
- The typed-boundaries baselines do not exist on `origin/develop`; they start on this branch and hold today's findings. The history check (`scripts/check_typed_boundaries.py --commits`) reports 1101 rises inside the branch's own commits (2026-11-17, `OPS_STANDARDS_REVIEW=required make checks-history`); those are rows raised after a file's first commit. The same run reports 55 access-exception, 8 portable-store, 119 config-literal and 90 console JSON rises, and the four pytest ratchets fail.
- `access-exceptions-allowlist.txt` fell in total (177 to 175) but 76 of its keys rose; rows moved between keys.
- `portable-baseline.txt` fell (49 to 25) and is not listed.
- `apps/console/scripts/data-baseline.json` was added whole; `scripts/check_console_baselines.py --commits` now reads its history like the .txt baselines.

Each file above is a work list: the builder of that service or package brings its rows back down, and no row is raised to go green.
