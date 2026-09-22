#!/usr/bin/env bash
#
# Tear the environment down, API stack first so the exports it imports are free.
set -euo pipefail

SERVICE=announcements
ENVIRONMENT=dev
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)     ENVIRONMENT="$2"; shift 2 ;;
    --region)  REGION="$2";      shift 2 ;;
    --service) SERVICE="$2";     shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ "$ENVIRONMENT" == prod ]]; then
  echo "Refusing to delete a prod environment. Do it deliberately, by hand." >&2
  exit 1
fi

for STACK in "$SERVICE-$ENVIRONMENT-api" "$SERVICE-$ENVIRONMENT-foundation"; do
  echo "==> deleting $STACK"
  aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION"
done

echo "Done. The DynamoDB table has UpdateReplacePolicy: Retain but no deletion"
echo "policy override outside prod, so it is removed with the stack."
