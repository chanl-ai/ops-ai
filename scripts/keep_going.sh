#!/usr/bin/env bash
# One verify check, run so that a failure is recorded instead of stopping the run (c-367): python-verify runs every
# check through this and fails at the end listing each one that failed, so one red never hides the reds after it.
#
#   scripts/keep_going.sh <list-file> <command> [args...]   run a check; on failure append it to <list-file>
#   scripts/keep_going.sh --report <list-file>              print every failed check and exit 1 if there was one
set -uo pipefail
if [ "${1:-}" = "--report" ]; then
  list="$2"
  if [ -s "$list" ]; then
    echo "verify: $(wc -l <"$list" | tr -d ' ') check(s) failed:"
    sed 's/^/  - /' "$list"
    rm -f "$list"
    exit 1
  fi
  rm -f "$list"
  echo "verify: every check passed"
  exit 0
fi
list="$1"
shift
"$@"
code=$?
if [ "$code" -ne 0 ]; then
  echo "$* (exit $code) [in $PWD]" >>"$list"
fi
exit 0
