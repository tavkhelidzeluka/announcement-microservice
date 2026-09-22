#!/usr/bin/env bash
#
# Deploy the announcements microservice.
#
#   ./scripts/deploy.sh --artifact-bucket my-cfn-artifacts [--env dev] [--region eu-west-1]
#
# The two stacks are deployed in order because the API stack's OpenAPI document
# has to name the Cognito user pool and the Lambda functions that the
# foundation stack creates. Everything between the two deploys is generated -
# there is nothing to edit by hand.
set -euo pipefail

SERVICE=announcements
ENVIRONMENT=dev
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}"
STAGE=v1
ARTIFACT_BUCKET=""
ALLOWED_ORIGIN="https://www.philips.com"
ALARM_EMAIL=""
CONFIGURE_APIGW_ROLE="true"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-bucket) ARTIFACT_BUCKET="$2"; shift 2 ;;
    --env)             ENVIRONMENT="$2";     shift 2 ;;
    --region)          REGION="$2";          shift 2 ;;
    --stage)           STAGE="$2";           shift 2 ;;
    --service)         SERVICE="$2";         shift 2 ;;
    --allowed-origin)  ALLOWED_ORIGIN="$2";  shift 2 ;;
    --alarm-email)     ALARM_EMAIL="$2";     shift 2 ;;
    --skip-apigw-account-role) CONFIGURE_APIGW_ROLE="false"; shift ;;
    -h|--help)         usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

[[ -n "$ARTIFACT_BUCKET" ]] || { echo "--artifact-bucket is required" >&2; usage 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
FOUNDATION_STACK="$SERVICE-$ENVIRONMENT-foundation"
API_STACK="$SERVICE-$ENVIRONMENT-api"
PYTHON="${PYTHON:-python3}"

mkdir -p "$BUILD"
echo "==> region=$REGION environment=$ENVIRONMENT artifacts=s3://$ARTIFACT_BUCKET"

# ---------------------------------------------------------------------------
# 1. Foundation stack: table, Cognito, secret, Lambda functions, alarms.
#    `package` zips src/ and rewrites Code: ../src into an S3 reference.
# ---------------------------------------------------------------------------
echo "==> packaging foundation stack"
aws cloudformation package \
  --template-file "$ROOT/infrastructure/foundation.yaml" \
  --s3-bucket "$ARTIFACT_BUCKET" \
  --s3-prefix "$SERVICE/$ENVIRONMENT/code" \
  --output-template-file "$BUILD/foundation.packaged.yaml" \
  --region "$REGION" >/dev/null

echo "==> deploying $FOUNDATION_STACK"
aws cloudformation deploy \
  --template-file "$BUILD/foundation.packaged.yaml" \
  --stack-name "$FOUNDATION_STACK" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION" \
  --parameter-overrides \
    "ServiceName=$SERVICE" \
    "EnvironmentName=$ENVIRONMENT" \
    "AllowedOrigin=$ALLOWED_ORIGIN" \
    "AlarmEmail=$ALARM_EMAIL"

output() {
  aws cloudformation describe-stacks \
    --stack-name "$1" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
USER_POOL_ARN="$(output "$FOUNDATION_STACK" UserPoolArn)"
TOKEN_URL="$(output "$FOUNDATION_STACK" TokenUrl)"
LIST_FUNCTION="$(output "$FOUNDATION_STACK" ListFunctionName)"
CREATE_FUNCTION="$(output "$FOUNDATION_STACK" CreateFunctionName)"

# ---------------------------------------------------------------------------
# 2. Merge the published contract with its AWS bindings and upload it.
#    The object key carries a hash of the document, so a contract change
#    produces a new key and CloudFormation genuinely re-imports the API instead
#    of quietly leaving the old definition in place.
# ---------------------------------------------------------------------------
echo "==> building the OpenAPI document API Gateway will import"
"$PYTHON" "$ROOT/scripts/build_openapi.py" \
  --output "$BUILD/openapi.aws.yaml" \
  --set "AWS_REGION=$REGION" \
  --set "AWS_ACCOUNT_ID=$ACCOUNT_ID" \
  --set "LIST_FUNCTION_NAME=$LIST_FUNCTION" \
  --set "CREATE_FUNCTION_NAME=$CREATE_FUNCTION" \
  --set "USER_POOL_ARN=$USER_POOL_ARN" \
  --set "TOKEN_URL=$TOKEN_URL" \
  --set "ALLOWED_ORIGIN=$ALLOWED_ORIGIN"

SPEC_HASH="$($PYTHON - "$BUILD/openapi.aws.yaml" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest()[:16])
PY
)"
SPEC_KEY="$SERVICE/$ENVIRONMENT/openapi/$SPEC_HASH.yaml"
aws s3 cp "$BUILD/openapi.aws.yaml" "s3://$ARTIFACT_BUCKET/$SPEC_KEY" --region "$REGION" >/dev/null
echo "    s3://$ARTIFACT_BUCKET/$SPEC_KEY"

# ---------------------------------------------------------------------------
# 3. API stack.
# ---------------------------------------------------------------------------
echo "==> deploying $API_STACK"
aws cloudformation deploy \
  --template-file "$ROOT/infrastructure/api.yaml" \
  --stack-name "$API_STACK" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION" \
  --parameter-overrides \
    "FoundationStackName=$FOUNDATION_STACK" \
    "ServiceName=$SERVICE" \
    "EnvironmentName=$ENVIRONMENT" \
    "StageName=$STAGE" \
    "OpenApiBucket=$ARTIFACT_BUCKET" \
    "OpenApiKey=$SPEC_KEY" \
    "AllowedOrigin=$ALLOWED_ORIGIN" \
    "ConfigureApiGatewayCloudWatchRole=$CONFIGURE_APIGW_ROLE"

# ---------------------------------------------------------------------------
# 4. Publish the imported definition to the stage.
#
#    AWS::ApiGateway::Deployment is a point-in-time snapshot of the API. When
#    CloudFormation updates the RestApi body it does *not* create a new
#    snapshot, so the stage would keep serving the previous contract. This is a
#    known CloudFormation limitation, not something the templates can express;
#    one explicit call fixes it and is safe to repeat.
# ---------------------------------------------------------------------------
REST_API_ID="$(output "$API_STACK" RestApiId)"
echo "==> publishing deployment to stage $STAGE"
aws apigateway create-deployment \
  --rest-api-id "$REST_API_ID" \
  --stage-name "$STAGE" \
  --description "openapi $SPEC_HASH" \
  --region "$REGION" >/dev/null

cat <<EOF

Deployed.

  API              $(output "$API_STACK" AnnouncementsUrl)
  Token endpoint   $TOKEN_URL
  OAuth client id  $(output "$FOUNDATION_STACK" PublisherClientId)
  Dashboard        $(output "$API_STACK" DashboardUrl)

Fetch the credentials the Postman collection needs with:

  ./scripts/show_credentials.sh --env $ENVIRONMENT --region $REGION
EOF
