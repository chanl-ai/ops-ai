#!/usr/bin/env bash
# Ask the one QA runner for a verdict instead of running the full suite yourself.
#
#   scripts/qa.sh request [sha]          ask the runner to test HEAD at once (sha defaults to HEAD)
#   scripts/qa.sh wait [sha] [minutes]   request, then wait for a verdict on that sha or a later commit containing it;
#                                        exit 0 GREEN, 1 RED (the runner's line is printed), 2 no verdict in time
#   scripts/qa.sh status [sha]           print the latest verdict that covers sha, if any
#
# The runner (the planning repo scripts/ops-ai/qa-watch.sh) tests HEAD, only what changed since its last green plus a full
# run every two hours, and writes each verdict to $QA_DIR/verdicts/<sha>. A verdict on a later commit covers every
# commit before it, so a builder whose commit landed under someone else's still gets an answer.
set -uo pipefail
QA_DIR=${QA_DIR:-/tmp/ops-ai-qa}
root=$(cd "$(dirname "$0")/.." && pwd)

covering() {
  local want=$1 f s best=""
  for f in $(ls -t "$QA_DIR/verdicts" 2>/dev/null); do
    s=${f%.*}
    if git -C "$root" merge-base --is-ancestor "$want" "$s" 2>/dev/null; then best="$QA_DIR/verdicts/$f"; break; fi
  done
  echo "$best"
}

cmd=${1:-status}
sha=$(git -C "$root" rev-parse --short "${2:-HEAD}")
case "$cmd" in
  request)
    mkdir -p "$QA_DIR/requests" && touch "$QA_DIR/requests/$sha"
    echo "qa: requested a run covering $sha" ;;
  status)
    v=$(covering "$sha"); [ -n "$v" ] && cat "$v" || echo "qa: no verdict covers $sha yet" ;;
  wait)
    minutes=${3:-60}
    pgrep -f "scripts/ops-ai/qa-watch.sh" >/dev/null || { echo "qa: the QA runner is not running; start it with make -C the planning repo opsai-qa-up"; exit 2; }
    mkdir -p "$QA_DIR/requests" && touch "$QA_DIR/requests/$sha"
    end=$(( $(date +%s) + minutes * 60 ))
    while [ "$(date +%s)" -lt "$end" ]; do
      v=$(covering "$sha")
      if [ -n "$v" ]; then cat "$v"; grep -q " GREEN " "$v" && exit 0 || exit 1; fi
      sleep 20
    done
    echo "qa: no verdict covering $sha within $minutes minutes"; exit 2 ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
