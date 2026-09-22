"""GET /announcements, end to end against a mocked DynamoDB."""
import json

import pytest

from conftest import API_KEY, ALLOWED_ORIGIN, announcement, body_of, event


@pytest.fixture
def handlers(aws):
    from announcements.handlers import create_announcement, list_announcements
    return list_announcements.handler, create_announcement.handler


def seed(create, count, base_hour=9):
    """Create `count` announcements one hour apart, oldest first."""
    created = []
    for index in range(count):
        response = create(
            event(
                method="POST",
                body=announcement(
                    title="Announcement {0}".format(index),
                    date="2026-03-01T{0:02d}:00:00Z".format(base_hour + index),
                ),
                claims={"client_id": "publisher"},
            ),
            None,
        )
        assert response["statusCode"] == 201, response["body"]
        created.append(body_of(response)["data"])
    return created


def test_an_empty_collection_is_a_200_with_an_empty_array(handlers):
    list_handler, _ = handlers
    response = list_handler(event(), None)

    assert response["statusCode"] == 200
    document = body_of(response)
    assert document["data"] == []
    assert document["meta"] == {"count": 0, "pageSize": 0}
    assert "next" not in document["links"]


def test_announcements_come_back_newest_first_by_default(handlers):
    list_handler, create = handlers
    seed(create, 3)

    document = body_of(list_handler(event(), None))
    dates = [item["attributes"]["announcementDate"] for item in document["data"]]
    assert dates == sorted(dates, reverse=True)
    assert document["meta"]["count"] == 3


def test_sort_can_be_flipped_to_oldest_first(handlers):
    list_handler, create = handlers
    seed(create, 3)

    document = body_of(
        list_handler(event(query={"sort": "announcementDate"}), None)
    )
    dates = [item["attributes"]["announcementDate"] for item in document["data"]]
    assert dates == sorted(dates)


def test_a_page_carries_a_cursor_that_walks_the_whole_collection(handlers):
    list_handler, create = handlers
    seed(create, 5)

    seen = []
    query = {"limit": "2"}
    for _ in range(10):  # generous bound; the loop should break well before it
        document = body_of(list_handler(event(query=dict(query)), None))
        seen.extend(item["id"] for item in document["data"])
        assert document["meta"]["count"] == 5
        next_link = document["links"].get("next")
        if not next_link:
            break
        query["cursor"] = next_link.split("cursor=")[1]

    assert len(seen) == 5
    assert len(set(seen)) == 5, "a cursor must not replay or skip rows"


def test_the_last_page_has_no_next_link(handlers):
    list_handler, create = handlers
    seed(create, 2)

    document = body_of(list_handler(event(query={"limit": "50"}), None))
    assert len(document["data"]) == 2
    assert "next" not in document["links"]


def test_data_and_errors_never_coexist(handlers):
    list_handler, create = handlers
    seed(create, 1)

    ok = body_of(list_handler(event(), None))
    assert "data" in ok and "errors" not in ok

    failed = body_of(list_handler(event(query={"limit": "0"}), None))
    assert "errors" in failed and "data" not in failed


def test_a_list_response_is_conditionally_cacheable(handlers):
    list_handler, create = handlers
    seed(create, 1)

    first = list_handler(event(), None)
    etag = first["headers"]["ETag"]
    assert first["headers"]["Cache-Control"] == "public, max-age=60"

    second = list_handler(event(headers={"If-None-Match": etag}), None)
    assert second["statusCode"] == 304
    assert second["body"] == ""
    assert second["headers"]["ETag"] == etag


def test_the_etag_changes_when_the_collection_changes(handlers):
    list_handler, create = handlers
    seed(create, 1)
    before = list_handler(event(), None)["headers"]["ETag"]
    seed(create, 1, base_hour=20)
    after = list_handler(event(), None)["headers"]["ETag"]
    assert before != after


def test_links_are_built_on_the_path_the_client_actually_called(handlers):
    list_handler, _ = handlers
    response = list_handler(
        event(stage_path="/communications/announcements"), None
    )
    assert body_of(response)["links"]["self"].startswith(
        "/communications/announcements?"
    )


def test_undefined_query_parameters_are_ignored(handlers):
    """The guidelines ask for unknown parameters to be accepted, not rejected."""
    list_handler, create = handlers
    seed(create, 1)
    response = list_handler(event(query={"utm_source": "newsletter"}), None)
    assert response["statusCode"] == 200


def test_the_configured_origin_is_echoed_and_others_are_not(handlers):
    list_handler, _ = handlers

    allowed = list_handler(event(headers={"Origin": ALLOWED_ORIGIN}), None)
    assert allowed["headers"]["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN

    denied = list_handler(event(headers={"Origin": "https://evil.example"}), None)
    assert "Access-Control-Allow-Origin" not in denied["headers"]
    assert denied["headers"]["Vary"] == "Origin, Accept-Encoding"
