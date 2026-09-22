"""Payload validation: the shape of the errors matters as much as rejecting."""
import pytest

from announcements.app import errors, validation


def parse(**overrides):
    attributes = {
        "title": "A title",
        "description": "A description",
        "announcementDate": "2026-03-01T09:00:00Z",
    }
    attributes.update(overrides)
    attributes = {k: v for k, v in attributes.items() if v is not _ABSENT}
    return validation.parse_create_document(
        {"data": {"type": "announcements", "attributes": attributes}}
    )


_ABSENT = object()


def test_accepts_a_well_formed_announcement():
    assert parse() == {
        "title": "A title",
        "description": "A description",
        "announcementDate": "2026-03-01T09:00:00Z",
    }


def test_trims_surrounding_whitespace():
    assert parse(title="  Padded  ")["title"] == "Padded"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-03-01T09:00:00Z", "2026-03-01T09:00:00Z"),
        ("2026-03-01t09:00:00z", "2026-03-01T09:00:00Z"),
        # Offsets are accepted and normalised to UTC, as the guidelines ask.
        ("2026-03-01T10:00:00+01:00", "2026-03-01T09:00:00Z"),
        ("2026-03-01T04:00:00-05:00", "2026-03-01T09:00:00Z"),
        ("2026-03-01T09:00:00.123Z", "2026-03-01T09:00:00Z"),
    ],
)
def test_normalises_date_times_to_utc(value, expected):
    assert parse(announcementDate=value)["announcementDate"] == expected


@pytest.mark.parametrize(
    "value",
    [
        "2026-03-01",           # a full date is not a date-time
        "01-03-2026T09:00:00Z",
        "2026-13-01T09:00:00Z",  # month 13
        "2026-02-30T09:00:00Z",  # not a real day
        "2026-03-01T09:00:00",   # no timezone
        "yesterday",
        "",
    ],
)
def test_rejects_anything_that_is_not_an_rfc3339_date_time(value):
    with pytest.raises(errors.ApiError) as caught:
        parse(announcementDate=value)
    assert caught.value.code == "INVALID_PARAMETER_VALUE"
    assert caught.value.source == {"pointer": "/data/attributes/announcementDate"}


def test_reports_every_problem_at_once():
    with pytest.raises(errors.ApiErrors) as caught:
        parse(title=_ABSENT, description="", announcementDate="nope")
    pointers = [error.source["pointer"] for error in caught.value.errors]
    assert pointers == [
        "/data/attributes/title",
        "/data/attributes/description",
        "/data/attributes/announcementDate",
    ]
    assert caught.value.errors[0].code == "MISSING_PARAMETER"
    assert caught.value.errors[1].code == "INVALID_PARAMETER_VALUE"


def test_rejects_a_blank_title():
    with pytest.raises(errors.ApiError) as caught:
        parse(title="   ")
    assert caught.value.code == "INVALID_PARAMETER_VALUE"


def test_rejects_an_over_long_title():
    with pytest.raises(errors.ApiError) as caught:
        parse(title="x" * (validation.TITLE_MAX_LENGTH + 1))
    assert caught.value.status == 400


def test_rejects_a_non_string_title():
    with pytest.raises(errors.ApiError) as caught:
        parse(title=42)
    assert caught.value.code == "INVALID_PARAMETER_VALUE"


def test_rejects_unknown_attributes():
    with pytest.raises(errors.ApiError) as caught:
        parse(author="someone")
    assert caught.value.source == {"pointer": "/data/attributes/author"}


def test_rejects_a_client_generated_id():
    """JSON API requires 403, not a silent overwrite of the server's id."""
    with pytest.raises(errors.ApiError) as caught:
        validation.parse_create_document(
            {"data": {"type": "announcements", "id": "abc", "attributes": {}}}
        )
    assert caught.value.status == 403
    assert caught.value.code == "CLIENT_GENERATED_ID_NOT_SUPPORTED"


def test_rejects_a_mismatched_resource_type():
    with pytest.raises(errors.ApiError) as caught:
        validation.parse_create_document(
            {"data": {"type": "articles", "attributes": {}}}
        )
    assert caught.value.status == 409
    assert caught.value.code == "RESOURCE_TYPE_MISMATCH"


@pytest.mark.parametrize(
    "document,pointer",
    [
        ({}, "/data"),
        ({"data": {"attributes": {}}}, "/data/type"),
        ({"data": {"type": "announcements"}}, "/data/attributes"),
    ],
)
def test_reports_missing_members_with_a_json_pointer(document, pointer):
    with pytest.raises(errors.ApiError) as caught:
        validation.parse_create_document(document)
    assert caught.value.code == "MISSING_PARAMETER"
    assert caught.value.source == {"pointer": pointer}
