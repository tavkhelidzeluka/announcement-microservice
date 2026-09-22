"""Cross-cutting obligations from the PIL RESTful API Guidelines.

Every test here maps onto a MUST in the guidelines, so a regression shows up as
a named failure rather than as a subtle change in an error body.
"""
import pytest

from conftest import API_KEY, body_of, event


@pytest.fixture
def call(aws):
    from announcements.handlers import list_announcements
    return list_announcements.handler


def error_of(response):
    document = body_of(response)
    assert "data" not in document, "errors and data must not coexist"
    assert document["meta"]["requestId"] == "test-request-id"
    return document["errors"][0]


# --- Api-Version ----------------------------------------------------------

def test_a_request_without_an_api_version_is_rejected(call):
    response = call(event(headers={"Api-Version": None}), None)
    assert response["statusCode"] == 400
    error = error_of(response)
    assert error["code"] == "MISSING_API_VERSION"
    assert error["source"] == {"parameter": "Api-Version"}


def test_a_blank_api_version_is_treated_as_missing(call):
    response = call(event(headers={"Api-Version": "   "}), None)
    assert error_of(response)["code"] == "MISSING_API_VERSION"


@pytest.mark.parametrize("version", ["2", "0", "1.0", "v1", "abc"])
def test_an_unsupported_api_version_is_rejected(call, version):
    response = call(event(headers={"Api-Version": version}), None)
    assert response["statusCode"] == 400
    assert error_of(response)["code"] == "INVALID_API_VERSION"


# --- Api-Key --------------------------------------------------------------

def test_a_request_without_an_api_key_is_forbidden(call):
    response = call(event(headers={"Api-Key": None}), None)
    assert response["statusCode"] == 403
    assert error_of(response)["code"] == "MISSING_API_KEY"


def test_an_unknown_api_key_is_forbidden(call):
    response = call(event(headers={"Api-Key": "not-a-real-key"}), None)
    assert response["statusCode"] == 403
    assert error_of(response)["code"] == "INVALID_API_KEY"


def test_header_names_are_matched_case_insensitively(call):
    """HTTP header names are case-insensitive even though the guidelines
    mandate Train-Case on the wire."""
    response = call(
        {
            "httpMethod": "GET",
            "path": "/announcements",
            "headers": {"api-key": API_KEY, "API-VERSION": "1"},
            "queryStringParameters": None,
            "body": None,
            "requestContext": {"requestId": "test-request-id"},
        },
        None,
    )
    assert response["statusCode"] == 200


# --- Content negotiation --------------------------------------------------

def test_an_unsatisfiable_accept_header_is_not_acceptable(call):
    response = call(event(headers={"Accept": "application/xml"}), None)
    assert response["statusCode"] == 406
    assert error_of(response)["code"] == "NOT_ACCEPTABLE"


@pytest.mark.parametrize(
    "accept",
    ["application/json", "*/*", "application/*", "application/vnd.api+json",
     "text/html, application/json;q=0.9"],
)
def test_accept_headers_that_include_json_are_served(call, accept):
    assert call(event(headers={"Accept": accept}), None)["statusCode"] == 200


def test_an_unsupported_content_type_on_a_body_is_415(aws):
    from announcements.handlers import create_announcement
    from conftest import announcement

    response = create_announcement.handler(
        event(
            method="POST",
            body=announcement(),
            headers={"Content-Type": "text/plain"},
            claims={"client_id": "publisher"},
        ),
        None,
    )
    assert response["statusCode"] == 415
    assert error_of(response)["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_missing_content_type_defaults_to_json(aws):
    from announcements.handlers import create_announcement
    from conftest import announcement

    response = create_announcement.handler(
        event(
            method="POST",
            body=announcement(),
            headers={"Content-Type": None},
            claims={"client_id": "publisher"},
        ),
        None,
    )
    assert response["statusCode"] == 201


# --- Responses ------------------------------------------------------------

def test_responses_are_json(call):
    response = call(event(), None)
    assert response["headers"]["Content-Type"] == "application/json"


def test_no_internal_detail_leaks_when_something_unexpected_fails(aws, monkeypatch):
    """A broken dependency must produce an opaque 500, never a stack trace."""
    from announcements.handlers import list_announcements

    def explode(*args, **kwargs):
        raise RuntimeError("connection to table announcements-test refused")

    monkeypatch.setattr(
        list_announcements.repository(), "list", explode, raising=True
    )

    response = list_announcements.handler(event(), None)
    assert response["statusCode"] == 500

    error = error_of(response)
    assert error["code"] == "SERVER_ERROR"
    assert error["id"] == "test-request-id"
    body = response["body"]
    for leak in ("RuntimeError", "Traceback", "announcements-test", "refused"):
        assert leak not in body, "internal detail leaked: {0}".format(leak)


def test_checks_run_in_a_defined_order(call):
    """Client identification comes before version negotiation, so a request
    with neither header is answered as a 403 rather than ambiguously."""
    response = call(event(headers={"Api-Key": None, "Api-Version": None}), None)
    assert response["statusCode"] == 403
    assert error_of(response)["code"] == "MISSING_API_KEY"
