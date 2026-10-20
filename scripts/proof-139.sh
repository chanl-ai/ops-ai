#!/usr/bin/env bash
# c-139 proof so far (T001, T002, T004, T006, T007): the policy, deployment and contract tests in agents-service, the
# tools-service policy client, and uc-114 through the console.
set -euo pipefail
cd "$(dirname "$0")/.."
DB="${OPS_TEST_DATABASE_URL:-postgresql+asyncpg://ops:ops@localhost:5477/ops_test_c041rev}"
uv run --project . python scripts/test_db.py "$DB"
(cd services/agents-service && OPS_TEST_DATABASE_URL="$DB" OPS_DATABASE_URL="$DB" uv run pytest -q tests/api/test_publish_policy.py tests/api/test_publish_policy_contract.py)
(cd services/tools-service && OPS_TEST_DATABASE_URL="$DB" OPS_DATABASE_URL="$DB" uv run pytest -q tests/test_publish_policy_client.py)
node scripts/usecase.mjs test --uc uc-114 --layer ui
