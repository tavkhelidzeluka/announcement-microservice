"""Test fixtures.

Everything runs against moto, so the whole suite is offline: no AWS account, no
credentials, no network. That keeps it usable in CI and on a laptop.
"""
import json
import os

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "announcements-test"
SECRET_ID = "announcements/test/api-key"
API_KEY = "test-api-key-0123456789abcdef"
CLIENT_ID = "test-client"
ALLOWED_ORIGIN = "https://www.philips.com"


@pytest.fixture(autouse=True)
def aws_environment(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("API_KEY_SECRET_ID", SECRET_ID)
    monkeypatch.setenv("ALLOWED_ORIGIN", ALLOWED_ORIGIN)
    monkeypatch.setenv("LIST_CACHE_MAX_AGE_SECONDS", "60")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")


@pytest.fixture
def aws(aws_environment):
    """A mocked AWS with the table and the API key secret already in place."""
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="eu-west-1")
        dynamodb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "announcementId", "AttributeType": "S"},
                {"AttributeName": "listPartition", "AttributeType": "S"},
                {"AttributeName": "announcementDateId", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "announcementId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "announcementDateIndex",
                    "KeySchema": [
                        {"AttributeName": "listPartition", "KeyType": "HASH"},
                        {"AttributeName": "announcementDateId", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        secrets = boto3.client("secretsmanager", region_name="eu-west-1")
        secrets.create_secret(
            Name=SECRET_ID,
            SecretString=json.dumps({"clientId": CLIENT_ID, "apiKey": API_KEY}),
        )
        _reset_module_state()
        yield
        _reset_module_state()


def _reset_module_state():
    """Clear the caches the handlers keep across invocations."""
    from announcements.app import repository, security
    from announcements.handlers import create_announcement, list_announcements

    repository.reset_client()
    security.reset_cache()
    list_announcements._repository = None
    create_announcement._repository = None


def event(
    method="GET",
    path="/announcements",
    query=None,
    headers=None,
    body=None,
    claims=None,
    request_id="test-request-id",
    stage_path=None,
):
    """Build an API Gateway REST API proxy event."""
    all_headers = {"Api-Key": API_KEY, "Api-Version": "1"}
    if headers is not None:
        for name, value in headers.items():
            if value is None:
                all_headers.pop(name, None)
            else:
                all_headers[name] = value

    context = {"requestId": request_id, "path": stage_path or "/v1/announcements"}
    if claims is not None:
        context["authorizer"] = {"claims": claims}

    return {
        "httpMethod": method,
        "path": path,
        "headers": all_headers,
        "queryStringParameters": query,
        "body": body if isinstance(body, str) or body is None else json.dumps(body),
        "isBase64Encoded": False,
        "requestContext": context,
    }


def body_of(response):
    return json.loads(response["body"])


def announcement(title="A title", description="A description",
                 date="2026-03-01T09:00:00Z"):
    return {
        "data": {
            "type": "announcements",
            "attributes": {
                "title": title,
                "description": description,
                "announcementDate": date,
            },
        }
    }
