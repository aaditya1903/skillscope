#!/usr/bin/env bash
# Build the container stack, load the token-free demonstration corpus, prove
# the API and interface answer, then tear everything down.
#
# This uses no GitHub token, no network access to GitHub and no model download.
set -euo pipefail

COMPOSE=(docker compose --profile app)
API="http://127.0.0.1:${API_PORT:-8000}"
FRONTEND="http://127.0.0.1:${FRONTEND_PORT:-5173}"

cleanup() {
  local status=$?
  if [[ $status -ne 0 ]]; then
    echo "--- api logs ---" >&2
    "${COMPOSE[@]}" logs --no-color --tail 60 api >&2 || true
    echo "--- demo-loader logs ---" >&2
    "${COMPOSE[@]}" logs --no-color --tail 60 demo-loader >&2 || true
  fi
  # Remove only this stack's volumes by name. `down --volumes` would also
  # delete the development database volume declared in the same file.
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
  docker volume rm --force \
    skillscope_demo_postgres_data \
    skillscope_demo_evidence \
    skillscope_demo_config >/dev/null 2>&1 || true
  exit $status
}
trap cleanup EXIT

fail() {
  echo "docker smoke failed: $1" >&2
  exit 1
}

echo "==> Building images"
"${COMPOSE[@]}" build

echo "==> Starting the stack"
"${COMPOSE[@]}" up -d --wait --wait-timeout "${SMOKE_TIMEOUT:-300}"

echo "==> Checking liveness"
curl --fail --silent --show-error "$API/healthz" >/dev/null || fail "/healthz did not answer"

echo "==> Checking readiness"
readiness=$(curl --fail --silent --show-error "$API/readyz") || fail "/readyz did not answer"
grep -q '"status":"ready"' <<<"$readiness" || fail "readiness reported: $readiness"

echo "==> Checking each retrieval mode"
for mode in bm25 dense hybrid; do
  curl --fail --silent --show-error --get "$API/api/v1/search" \
    --data-urlencode "q=review a code diff for missing tests" \
    --data-urlencode "mode=$mode" \
    --data-urlencode "limit=5" \
    | python3 scripts/check_search_response.py "$mode" \
    || fail "$mode search returned no usable result"
done

echo "==> Checking skill detail"
skill_id=$(curl --fail --silent --get "$API/api/v1/search" \
  --data-urlencode "q=review a code diff" --data-urlencode "limit=1" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["results"][0]["skill_id"])')
curl --fail --silent "$API/api/v1/skills/$skill_id" >/dev/null || fail "skill detail did not answer"

echo "==> Checking statistics"
curl --fail --silent "$API/api/v1/stats" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["retrieval_eligible_skill_count"] > 0, d' \
  || fail "statistics reported an empty corpus"

echo "==> Checking error handling"
status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "$API/api/v1/skills/00000000-0000-4000-8000-000000000000")
[[ "$status" == "404" ]] || fail "a missing skill returned $status rather than 404"

echo "==> Checking the interface"
curl --fail --silent "$FRONTEND/" | grep -q "<title>SkillScope</title>" \
  || fail "the interface did not serve its entry document"

echo "docker smoke passed"
