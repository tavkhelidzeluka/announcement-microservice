#!/usr/bin/env bash
#
# Exercise a deployed environment end to end.
#
#   ./scripts/smoke_test.sh --env dev --region eu-north-1
#
# `make validate` checks the contract and the templates offline, but it cannot
# see how API Gateway *interprets* the document on import - a security scheme
# it silently ignores is still valid OpenAPI. Only a request against a real
# deployment catches that, so these assertions run after every deploy.
set -uo pipefail

ENVIRONMENT=dev
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}"
SERVICE=announcements

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --service) SERVICE="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$("$ROOT/scripts/show_credentials.sh" --env "$ENVIRONMENT" --region "$REGION" \
        --service "$SERVICE" --json |
        python3 -c 'import json,sys
for k, v in json.load(sys.stdin).items():
    print("export %s=%r" % (k.upper(), v))')"

TOKEN="$(curl -fsS -u "$CLIENTID:$CLIENTSECRET" "$TOKENURL" \
          -d grant_type=client_credentials -d scope=announcements/write |
         python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
[[ -n "$TOKEN" ]] || { echo "could not obtain an access token" >&2; exit 1; }

pass=0; fail=0
body=$(mktemp); trap 'rm -f "$body"' EXIT

status() { curl -s -o "$body" -w '%{http_code}' "$@"; }

expect() { # description expected-status expected-code curl-args...
  local what="$1" want="$2" want_code="$3"; shift 3
  local got; got="$(status "$@")"
  local code=""
  [[ -n "$want_code" ]] && code="$(python3 -c '
import json, sys
try: print(json.load(open(sys.argv[1]))["errors"][0].get("code", ""))
except Exception: print("")' "$body")"

  if [[ "$got" == "$want" ]] && { [[ -z "$want_code" ]] || [[ "$code" == "$want_code" ]]; }; then
    pass=$((pass + 1)); printf '  ok   %-46s %s %s\n' "$what" "$got" "$code"
  else
    fail=$((fail + 1))
    printf '  FAIL %-46s want %s %s, got %s %s\n' "$what" "$want" "$want_code" "$got" "$code"
  fi
}

V=(-H "Api-Version: 1")
K=(-H "Api-Key: $APIKEY")
J=(-H 'Content-Type: application/json')
A=(-H "Authorization: Bearer $TOKEN")
VALID='{"data":{"type":"announcements","attributes":{"title":"Smoke test","description":"Created by scripts/smoke_test.sh.","announcementDate":"2026-03-01T09:00:00Z"}}}'

echo "== client identification and versioning =="
expect "no Api-Version"            400 MISSING_API_VERSION  "$BASEURL/announcements" "${K[@]}"
expect "unsupported Api-Version"   400 INVALID_API_VERSION  "$BASEURL/announcements" "${K[@]}" -H 'Api-Version: 99'
expect "no Api-Key"                403 MISSING_API_KEY      "$BASEURL/announcements" "${V[@]}"
expect "invalid Api-Key"           403 INVALID_API_KEY      "$BASEURL/announcements" "${V[@]}" -H 'Api-Key: not-a-key'

echo "== the create endpoint is private =="
expect "POST with no token"        401 UNAUTHORIZED "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" -d "$VALID"
expect "POST with a bogus token"   401 ""           "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" -H 'Authorization: Bearer not.a.jwt' -d "$VALID"
expect "POST with a valid token"   201 ""           "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" "${A[@]}" -d "$VALID"

echo "== payload validation follows JSON API =="
expect "missing title"             400 MISSING_PARAMETER "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" "${A[@]}" \
  -d '{"data":{"type":"announcements","attributes":{"description":"d","announcementDate":"2026-03-01T09:00:00Z"}}}'
expect "bad announcementDate"      400 INVALID_PARAMETER_VALUE "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" "${A[@]}" \
  -d '{"data":{"type":"announcements","attributes":{"title":"t","description":"d","announcementDate":"01-03-2026"}}}'
expect "client-generated id"       403 CLIENT_GENERATED_ID_NOT_SUPPORTED "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" "${A[@]}" \
  -d '{"data":{"id":"11111111-2222-4333-8444-555555555555","type":"announcements","attributes":{"title":"t","description":"d","announcementDate":"2026-03-01T09:00:00Z"}}}'
expect "mismatched resource type"  409 RESOURCE_TYPE_MISMATCH "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${J[@]}" "${A[@]}" \
  -d '{"data":{"type":"articles","attributes":{"title":"t","description":"d","announcementDate":"2026-03-01T09:00:00Z"}}}'
expect "unsupported content type"  415 UNSUPPORTED_MEDIA_TYPE "$BASEURL/announcements" -X POST "${V[@]}" "${K[@]}" "${A[@]}" -H 'Content-Type: text/plain' -d "$VALID"

echo "== listing, pagination and negotiation =="
expect "list"                      200 "" "$BASEURL/announcements" "${V[@]}" "${K[@]}"
expect "limit below range"         400 INVALID_PARAMETER_VALUE "$BASEURL/announcements?limit=0"    "${V[@]}" "${K[@]}"
expect "limit above maximum"       400 INVALID_PARAMETER_VALUE "$BASEURL/announcements?limit=1000" "${V[@]}" "${K[@]}"
expect "tampered cursor"           400 INVALID_PARAMETER_VALUE "$BASEURL/announcements?cursor=Zm9yZ2Vk" "${V[@]}" "${K[@]}"
expect "unsortable property"       400 INVALID_PARAMETER_VALUE "$BASEURL/announcements?sort=title" "${V[@]}" "${K[@]}"
expect "undefined parameter"       200 "" "$BASEURL/announcements?utm_source=x" "${V[@]}" "${K[@]}"
expect "unacceptable Accept"       406 NOT_ACCEPTABLE "$BASEURL/announcements" "${V[@]}" "${K[@]}" -H 'Accept: application/xml'
expect "unsupported method"        405 METHOD_NOT_ALLOWED "$BASEURL/announcements" -X DELETE "${V[@]}" "${K[@]}"
expect "unknown path"              404 RESOURCE_NOT_FOUND "$BASEURL/announcementz" "${V[@]}" "${K[@]}"

echo "== conditional GET =="
etag="$(curl -s -D - -o /dev/null "$BASEURL/announcements" "${V[@]}" "${K[@]}" |
        tr -d '\r' | awk -F': ' 'tolower($1)=="etag"{print $2}')"
expect "If-None-Match matches"     304 "" "$BASEURL/announcements" "${V[@]}" "${K[@]}" -H "If-None-Match: $etag"

echo "== cursor pagination walks the collection =="
first="$(curl -s "$BASEURL/announcements?limit=1" "${V[@]}" "${K[@]}")"
cursor="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["links"].get("next","").split("cursor=")[-1])' "$first")"
id1="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["data"][0]["id"])' "$first")"
if [[ -n "$cursor" ]]; then
  id2="$(curl -s "$BASEURL/announcements?limit=1&cursor=$cursor" "${V[@]}" "${K[@]}" |
         python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["data"][0]["id"] if d["data"] else "")')"
  if [[ -n "$id2" && "$id1" != "$id2" ]]; then
    pass=$((pass + 1)); printf '  ok   %-46s %s -> %s\n' "next page is a different resource" "${id1:0:8}" "${id2:0:8}"
  else
    fail=$((fail + 1)); printf '  FAIL %-46s %s -> %s\n' "next page is a different resource" "$id1" "$id2"
  fi
else
  printf '  skip %-46s (fewer than two announcements)\n' "cursor pagination"
fi

echo "== no internal detail escapes =="
leak="$(curl -s "$BASEURL/announcements?limit=abc" "${V[@]}" "${K[@]}" |
        grep -ciE 'Traceback|boto3|botocore|/var/task|arn:aws' || true)"
if [[ "$leak" == "0" ]]; then
  pass=$((pass + 1)); printf '  ok   %-46s\n' "error body exposes nothing internal"
else
  fail=$((fail + 1)); printf '  FAIL %-46s\n' "error body exposes internal detail"
fi

echo
echo "passed=$pass failed=$fail"
[[ "$fail" -eq 0 ]]
