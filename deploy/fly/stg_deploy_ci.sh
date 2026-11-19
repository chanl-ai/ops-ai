#!/bin/sh
# make stg-deploy-ci: start .github/workflows/deploy-staging.yml on GitHub and watch it to the end; exits non-zero when
# the run fails. The deploy runs on a runner with the staging environment's secrets, so nothing is needed locally but
# `gh` signed in with write access.
#   REF        branch, tag or commit to deploy (default develop); it must be pushed
#   SKIP_WALK  1 leaves out the click walk (the signed-in request still runs)
#   REASON     shown in the run's summary
#   WORKFLOW_REF  the branch whose copy of the workflow runs (default develop); a different thing from REF
set -eu
ref=${REF:-develop}
wf_ref=${WORKFLOW_REF:-develop}
walk=false
[ "${SKIP_WALK:-0}" != 1 ] || walk=true
reason=${REASON:-"started with make stg-deploy-ci"}
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh workflow run deploy-staging.yml --ref "$wf_ref" -f ref="$ref" -f skip_walk="$walk" -f reason="$reason"
# `gh workflow run` prints no run id: wait for the dispatched run created after `since`.
id=""
for _ in $(seq 30); do
  id=$(gh run list --workflow deploy-staging.yml --event workflow_dispatch --branch "$wf_ref" --limit 5 \
    --json databaseId,createdAt --jq "[.[] | select(.createdAt >= \"$since\")] | last | .databaseId // empty")
  [ -z "$id" ] || break
  sleep 2
done
[ -n "$id" ] || { echo "stg-deploy-ci: the run did not appear; see gh run list --workflow deploy-staging.yml"; exit 1; }
echo "stg-deploy-ci: $(gh run view "$id" --json url --jq .url)"
gh run watch "$id" --exit-status --interval 15
