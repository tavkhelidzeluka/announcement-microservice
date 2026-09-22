"""POST /announcements, end to end against a mocked DynamoDB."""
import json
import uuid

import pytest

from conftest import announcement, body_of, event


@pytest.fixture
def handlers(aws):
    from announcements.handlers import create_announcement, list_announcements
    return create_announcement.handler, list_announcements.handler


PUBLISHER = {"client_id": "publisher", "scope": "announcements/write"}


def test_a_valid_announcement_is_created(handlers):
    create, _ = handlers
    response = create(
        event(method="POST", body=announcement(), claims=PUBLISHER), None
    )

    assert response["statusCode"] == 201
    assert response["headers"]["Cache-Control"] == "no-store"

    resource = body_of(response)["data"]
    assert resource["type"] == "announcements"
    assert uuid.UUID(resource["id"]).version == 4
    assert resource["attributes"] == {
        "title": "A title",
        "description": "A description",
        "announcementDate": "2026-03-01T09:00:00Z",
    }
    # Reserved, read-only resource metadata from the guidelines.
    assert set(resource["meta"]) == {"created", "lastModified"}


def test_a_created_announcement_is_immediately_listable(handlers):
    create, list_handler = handlers
    created = body_of(
        create(event(method="POST", body=announcement(), claims=PUBLISHER), None)
    )["data"]

    document = body_of(list_handler(event(), None))
    assert [item["id"] for item in document["data"]] == [created["id"]]
    assert document["meta"]["count"] == 1


def test_each_create_gets_its_own_id(handlers):
    create, _ = handlers
    ids = {
        body_of(
            create(event(method="POST", body=announcement(), claims=PUBLISHER), None)
        )["data"]["id"]
        for _ in range(3)
    }
    assert len(ids) == 3


def test_the_payload_is_validated(handlers):
    create, _ = handlers
    payload = announcement()
    del payload["data"]["attributes"]["title"]

    response = create(event(method="POST", body=payload, claims=PUBLISHER), None)
    assert response["statusCode"] == 400

    error = body_of(response)["errors"][0]
    assert error["code"] == "MISSING_PARAMETER"
    assert error["source"] == {"pointer": "/data/attributes/title"}
    assert error["id"] == "test-request-id"


def test_a_missing_body_is_a_400(handlers):
    create, _ = handlers
    response = create(event(method="POST", body=None, claims=PUBLISHER), None)
    assert response["statusCode"] == 400
    assert body_of(response)["errors"][0]["code"] == "MISSING_PARAMETER"


def test_a_body_that_is_not_json_is_a_400_not_a_500(handlers):
    create, _ = handlers
    response = create(
        event(method="POST", body="{not json", claims=PUBLISHER), None
    )
    assert response["statusCode"] == 400
    assert body_of(response)["errors"][0]["code"] == "BAD_REQUEST"


def test_a_client_generated_id_is_refused(handlers):
    create, _ = handlers
    payload = announcement()
    payload["data"]["id"] = str(uuid.uuid4())

    response = create(event(method="POST", body=payload, claims=PUBLISHER), None)
    assert response["statusCode"] == 403
    assert body_of(response)["errors"][0]["code"] == "CLIENT_GENERATED_ID_NOT_SUPPORTED"


def test_a_mismatched_type_is_a_conflict(handlers):
    create, _ = handlers
    payload = announcement()
    payload["data"]["type"] = "articles"

    response = create(event(method="POST", body=payload, claims=PUBLISHER), None)
    assert response["statusCode"] == 409


def test_the_publishing_oauth_client_is_recorded(aws):
    """Who published an announcement is worth knowing, and it is not exposed
    in the representation."""
    import boto3

    from announcements.handlers import create_announcement
    from conftest import TABLE_NAME

    created = body_of(
        create_announcement.handler(
            event(method="POST", body=announcement(), claims=PUBLISHER), None
        )
    )["data"]

    item = boto3.client("dynamodb", region_name="eu-west-1").get_item(
        TableName=TABLE_NAME,
        Key={"announcementId": {"S": created["id"]}},
    )["Item"]
    assert item["createdBy"]["S"] == "publisher"
    assert "createdBy" not in created["attributes"]
