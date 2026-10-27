#!/usr/bin/env bash
# Sets up and changes the lane's Nexus through its REST API. Nothing here needs a file from inside the container.
#
#   nexus.sh setup                       wait for Nexus, make the PyPI and npm proxy repositories, allow anonymous reads
#   nexus.sh block <pypi|npm> <regex>    a routing rule that answers 403 to every path matching the regex
#   nexus.sh unblock <pypi|npm>          take the routing rule off
#
# The admin login is the throwaway one compose.yaml sets (admin / admin123); the instance listens on 127.0.0.1 only.
set -euo pipefail

PORT=${OPS_MIRROR_PORT:-18081}
BASE=http://127.0.0.1:$PORT
AUTH=${OPS_MIRROR_ADMIN:-admin:admin123}
PYPI_UPSTREAM=${OPS_MIRROR_PYPI_UPSTREAM:-https://pypi.org}
NPM_UPSTREAM=${OPS_MIRROR_NPM_UPSTREAM:-https://registry.npmjs.org}

say() { printf '%s\n' "$*"; }
die() { printf 'nexus.sh: %s\n' "$*" >&2; exit 1; }
api() {  # api METHOD PATH [JSON]: prints the body, fails on a status of 400 or more
  local method=$1 path=$2 body=${3:-} out code
  out=$(mktemp)
  if [ -n "$body" ]; then
    code=$(curl -s -o "$out" -w '%{http_code}' -u "$AUTH" -X "$method" -H 'Content-Type: application/json' -d "$body" "$BASE$path")
  else
    code=$(curl -s -o "$out" -w '%{http_code}' -u "$AUTH" -X "$method" "$BASE$path")
  fi
  if [ "$code" -ge 400 ]; then cat "$out" >&2; rm -f "$out"; die "$method $path answered $code"; fi
  cat "$out"; rm -f "$out"
}
repo_exists() { curl -s -o /dev/null -w '%{http_code}' -u "$AUTH" "$BASE/service/rest/v1/repositories/$1" | grep -q 200; }
repo_name() { case $1 in pypi) echo pypi-proxy ;; npm) echo npm-proxy ;; *) die "format is pypi or npm" ;; esac; }

wait_ready() {
  for _ in $(seq 1 120); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/service/rest/v1/status/writable" || true)" = 200 ] && return 0
    sleep 5
  done
  die "Nexus did not become writable at $BASE within 10 minutes"
}

proxy_body() {  # proxy_body NAME REMOTE [EXTRA_JSON_FIELDS]
  printf '{"name":"%s","online":true,"storage":{"blobStoreName":"default","strictContentTypeValidation":true},
"proxy":{"remoteUrl":"%s","contentMaxAge":1440,"metadataMaxAge":1440},
"negativeCache":{"enabled":true,"timeToLive":1440},
"httpClient":{"blocked":false,"autoBlock":false}%s}' "$1" "$2" "${3:-}"
}

cmd_setup() {
  wait_ready
  repo_exists pypi-proxy || api POST /service/rest/v1/repositories/pypi/proxy "$(proxy_body pypi-proxy "$PYPI_UPSTREAM" ',"pypi":{"removeQuarantined":false}')" >/dev/null
  repo_exists npm-proxy || api POST /service/rest/v1/repositories/npm/proxy "$(proxy_body npm-proxy "$NPM_UPSTREAM" ',"npm":{"removeQuarantined":false}')" >/dev/null
  api PUT /service/rest/v1/security/anonymous '{"enabled":true,"userId":"anonymous","realmName":"NexusAuthorizingRealm"}' >/dev/null
  say "nexus: $BASE/repository/pypi-proxy/simple and $BASE/repository/npm-proxy/ are ready (anonymous reads)"
}

set_routing_rule() {  # set_routing_rule FORMAT RULE_NAME|"" : attaches the rule to the proxy repository
  local format=$1 rule=$2 name current
  name=$(repo_name "$format")
  current=$(api GET "/service/rest/v1/repositories/$format/proxy/$name")
  printf '%s' "$current" | python3 -c '
import json, sys
repo, rule = json.load(sys.stdin), sys.argv[1]
# The API reads the attached rule as routingRuleName and takes it as routingRule.
repo.pop("routingRuleName", None)
repo["routingRule"] = rule or None
json.dump(repo, sys.stdout)' "$rule" | { body=$(cat); api PUT "/service/rest/v1/repositories/$format/proxy/$name" "$body" >/dev/null; }
}

cmd_block() {
  local format=$1 regex=$2 rule
  rule="block-$format"
  curl -s -o /dev/null -u "$AUTH" -X DELETE "$BASE/service/rest/v1/routing-rules/$rule" || true
  set_routing_rule "$format" ""
  curl -s -o /dev/null -u "$AUTH" -X DELETE "$BASE/service/rest/v1/routing-rules/$rule" || true
  api POST /service/rest/v1/routing-rules "$(python3 -c '
import json, sys
print(json.dumps({"name": sys.argv[1], "description": "lane test: block " + sys.argv[2], "mode": "BLOCK", "matchers": [sys.argv[2]]}))' "$rule" "$regex")" >/dev/null
  set_routing_rule "$format" "$rule"
  say "nexus: $(repo_name "$format") now answers 403 to paths matching $regex"
}

cmd_unblock() {
  local format=$1 rule="block-$1"
  set_routing_rule "$format" ""
  curl -s -o /dev/null -u "$AUTH" -X DELETE "$BASE/service/rest/v1/routing-rules/$rule" || true
  say "nexus: $(repo_name "$format") is open again"
}

case ${1:-} in
  setup) cmd_setup ;;
  block) [ $# -eq 3 ] || die "block <pypi|npm> <regex>"; cmd_block "$2" "$3" ;;
  unblock) [ $# -eq 2 ] || die "unblock <pypi|npm>"; cmd_unblock "$2" ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
