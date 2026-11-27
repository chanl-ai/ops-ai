#!/usr/bin/env bash
# `make requeue PR=n`: put a pull request back at the end of the merge queue after a fix. A queued pull request keeps
# the commit it was queued with, so it is taken out first (GraphQL dequeuePullRequest), the script waits until GitHub
# reports it out of the queue (from then a push to the branch is tested, not dropped), and auto-merge queues it again.
set -euo pipefail
pr=${1:?usage: requeue.sh <pull request number>}
state() {
  gh api graphql -F o='{owner}' -F n='{repo}' -F p="$pr" -f query='
    query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){id isInMergeQueue isDraft state}}}' \
    --jq '.data.repository.pullRequest | [.id, (.isInMergeQueue|tostring), (.isDraft|tostring), .state] | @tsv'
}
IFS=$'\t' read -r id queued draft open < <(state)
[ "$open" = OPEN ] || { echo "requeue: #$pr is $open"; exit 1; }
if [ "$queued" = true ]; then
  gh api graphql -f id="$id" -f query='mutation($id:ID!){dequeuePullRequest(input:{id:$id}){mergeQueueEntry{id}}}' >/dev/null
  for _ in $(seq 30); do
    IFS=$'\t' read -r id queued draft open < <(state)
    [ "$queued" = false ] && break
    sleep 2
  done
  [ "$queued" = false ] || { echo "requeue: #$pr is still in the queue after 60 seconds"; exit 1; }
  echo "requeue: #$pr is out of the queue"
else
  echo "requeue: #$pr was not in the queue"
fi
[ "$draft" = false ] || { echo "requeue: #$pr is a draft, which the queue refuses; mark it ready (gh pr ready $pr) and run this again"; exit 1; }
gh pr merge "$pr" --auto --merge
echo "requeue: #$pr joins the queue when its checks pass"
