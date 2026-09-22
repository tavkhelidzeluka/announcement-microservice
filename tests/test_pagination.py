"""Pagination parameters and the opaque cursor."""
import base64
import json

import pytest

from announcements.app import config, errors, pagination


def test_limit_defaults_to_the_server_defined_page_size():
    assert pagination.parse_limit({}) == config.DEFAULT_PAGE_SIZE
    assert pagination.parse_limit(None) == config.DEFAULT_PAGE_SIZE


def test_limit_is_honoured_within_range():
    assert pagination.parse_limit({"limit": "5"}) == 5
    assert pagination.parse_limit({"limit": str(config.MAX_PAGE_SIZE)}) == 100


@pytest.mark.parametrize("value", ["0", "-1", "101", "abc", "1.5", " "])
def test_an_invalid_limit_is_a_client_error(value):
    with pytest.raises(errors.ApiError) as caught:
        pagination.parse_limit({"limit": value})
    assert caught.value.status == 400
    assert caught.value.code == "INVALID_PARAMETER_VALUE"
    assert caught.value.source == {"parameter": "limit"}


def test_sort_defaults_to_newest_first():
    assert pagination.parse_sort({}) == pagination.DESCENDING


def test_sort_accepts_both_directions_of_the_one_sortable_property():
    assert pagination.parse_sort({"sort": "announcementDate"}) == pagination.ASCENDING
    assert pagination.parse_sort({"sort": "-announcementDate"}) == pagination.DESCENDING


@pytest.mark.parametrize("value", ["title", "-title", "announcementdate", "-"])
def test_sorting_on_anything_else_is_rejected(value):
    with pytest.raises(errors.ApiError) as caught:
        pagination.parse_sort({"sort": value})
    assert caught.value.source == {"parameter": "sort"}


KEY = {
    "announcementId": {"S": "9a5f3c1e-6b2d-4f8a-9c0e-1d2b3a4c5d6e"},
    "listPartition": {"S": "ALL"},
    "announcementDateId": {"S": "2026-03-01T09:00:00Z#9a5f3c1e"},
}


def test_a_cursor_round_trips():
    cursor = pagination.encode(KEY, pagination.DESCENDING)
    assert pagination.decode(cursor, pagination.DESCENDING) == KEY


def test_no_cursor_is_issued_on_the_last_page():
    assert pagination.encode(None, pagination.DESCENDING) is None
    assert pagination.decode(None, pagination.DESCENDING) is None


def test_a_cursor_is_bound_to_the_sort_order_it_was_issued_for():
    """Replaying a descending cursor against an ascending query would silently
    return the wrong window, so it is refused instead."""
    cursor = pagination.encode(KEY, pagination.DESCENDING)
    with pytest.raises(errors.ApiError) as caught:
        pagination.decode(cursor, pagination.ASCENDING)
    assert caught.value.code == "INVALID_PARAMETER_VALUE"


def encoded(payload):
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!",
        base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
        encoded({"v": 99, "s": "desc", "k": {}}),                    # future version
        encoded({"v": 1, "s": "desc", "k": {"announcementId": "x"}}),  # partial key
        encoded({"v": 1, "s": "desc", "k": dict(
            announcementId="x", listPartition="OTHER",
            announcementDateId="y")}),                                # other partition
        encoded({"v": 1, "s": "desc", "k": dict(
            announcementId="x", listPartition="ALL",
            announcementDateId="y", extra="z")}),                     # extra member
        encoded({"v": 1, "s": "desc", "k": dict(
            announcementId=1, listPartition="ALL",
            announcementDateId="y")}),                                # wrong type
        "x" * 600,                                                    # oversized
    ],
)
def test_a_tampered_cursor_is_a_400_not_a_500(cursor):
    with pytest.raises(errors.ApiError) as caught:
        pagination.decode(cursor, pagination.DESCENDING)
    assert caught.value.status == 400
    assert caught.value.source == {"parameter": "cursor"}


def test_links_expose_first_and_self_always_and_next_only_when_there_is_more():
    links = pagination.links("/communications/announcements", 20,
                             pagination.DESCENDING, None, "abc")
    assert links["self"] == "/communications/announcements?limit=20&sort=-announcementDate"
    assert links["first"] == links["self"]
    assert links["next"].endswith("&cursor=abc")

    last_page = pagination.links("/communications/announcements", 20,
                                 pagination.DESCENDING, "abc", None)
    assert "next" not in last_page
    assert "cursor=abc" in last_page["self"]
    assert "cursor" not in last_page["first"]
