#!/usr/bin/env bash
#
# Print the values the Postman environment needs: the Api-Key, the OAuth client
# credentials and the endpoints. Secrets are read straight from Secrets Manager
# and Cognito, so nothing sensitive is ever committed to the repository.
set -euo pipefail

SERVICE=announcements
ENVIRONMENT=dev
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}"
FORMAT=text

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)     ENVIRONMENT="$2"; shift 2 ;;
    --region)  REGION="$2";      shift 2 ;;
    --service) SERVICE="$2";     shift 2 ;;
    --json)    FORMAT=json;      shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

FOUNDATION_STACK="$SERVICE-$ENVIRONMENT-foundation"
API_STACK="$SERVICE-$ENVIRONMENT-api"

output() {
  aws cloudformation describe-stacks --stack-name "$1" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

SECRET_ARN="$(output "$FOUNDATION_STACK" ApiKeySecretArn)"
API_KEY="$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" \
  --region "$REGION" --query SecretString --output text \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["apiKey"])')"

USER_POOL_ID="$(output "$FOUNDATION_STACK" UserPoolId)"
CLIENT_ID="$(output "$FOUNDATION_STACK" PublisherClientId)"
CLIENT_SECRET="$(aws cognito-idp describe-user-pool-client \
  --user-pool-id "$USER_POOL_ID" --client-id "$CLIENT_ID" \
  --region "$REGION" --query 'UserPoolClient.ClientSecret' --output text)"

BASE_URL="$(output "$API_STACK" InvokeUrl)"
TOKEN_URL="$(output "$FOUNDATION_STACK" TokenUrl)"

if [[ "$FORMAT" == json ]]; then
  python3 - "$BASE_URL" "$TOKEN_URL" "$API_KEY" "$CLIENT_ID" "$CLIENT_SECRET" <<'PY'
import json, sys
base, token, key, cid, secret = sys.argv[1:6]
print(json.dumps({
    "baseUrl": base, "tokenUrl": token, "apiKey": key,
    "clientId": cid, "clientSecret": secret, "apiVersion": "1",
}, indent=2))
PY
else
  cat <<EOF
baseUrl       $BASE_URL
tokenUrl      $TOKEN_URL
apiVersion    1
apiKey        $API_KEY
clientId      $CLIENT_ID
clientSecret  $CLIENT_SECRET
EOF
fi
