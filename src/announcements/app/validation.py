"""Request payload validation.

API Gateway already rejects payloads that do not match the JSON Schema in the
OpenAPI document, which keeps malformed traffic off the Lambda bill. This layer
runs anyway: it is the one that produces guideline-shaped errors with a JSON
Pointer to the offending member, and it is what the unit tests exercise.

All problems with a payload are reported in one response - JSON API models
``errors`` as an array precisely so a client can fix everything in one go.
"""
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from . import config
from . import errors

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 4000

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)

_ALLOWED_ATTRIBUTES = ("title", "description", "announcementDate")
_ALLOWED_RESOURCE_MEMBERS = ("type", "attributes")


def parse_create_document(document):
    """Validate a create payload and return normalised attributes.

    Returns a dict with ``title``, ``description`` and ``announcementDate``
    (RFC 3339, normalised to UTC).
    """
    if not isinstance(document, dict):
        raise errors.bad_request("The request body must be a JSON object.")

    data = document.get("data")
    if data is None:
        raise errors.missing_parameter(
            "The member data is required.", pointer="/data"
        )
    if not isinstance(data, dict):
        raise errors.invalid_parameter_value(
            "data must be a JSON API resource object.", pointer="/data"
        )

    # JSON API: a server that does not accept client generated ids must answer
    # 403 rather than silently ignoring the id.
    if "id" in data:
        raise errors.client_generated_id_not_supported()

    resource_type = data.get("type")
    if resource_type is None:
        raise errors.missing_parameter(
            "The member type is required.", pointer="/data/type"
        )
    # JSON API: a type that does not match the endpoint is a conflict, not a
    # validation error.
    if resource_type != config.RESOURCE_TYPE:
        raise errors.resource_type_mismatch(config.RESOURCE_TYPE)

    unknown_members = _unknown(
        sorted(set(data) - set(_ALLOWED_RESOURCE_MEMBERS)), "/data/{0}", "Member"
    )
    if unknown_members:
        raise errors.ApiErrors(unknown_members)

    attributes = data.get("attributes")
    if attributes is None:
        raise errors.missing_parameter(
            "The member attributes is required.", pointer="/data/attributes"
        )
    if not isinstance(attributes, dict):
        raise errors.invalid_parameter_value(
            "attributes must be a JSON object.", pointer="/data/attributes"
        )

    collected = _unknown(
        sorted(set(attributes) - set(_ALLOWED_ATTRIBUTES)),
        "/data/attributes/{0}",
        "Attribute",
    )

    title = _validate_text(attributes, "title", TITLE_MAX_LENGTH, collected)
    description = _validate_text(
        attributes, "description", DESCRIPTION_MAX_LENGTH, collected
    )
    announcement_date = _validate_date_time(attributes, "announcementDate", collected)

    if collected:
        raise errors.ApiErrors(collected)

    return {
        "title": title,
        "description": description,
        "announcementDate": announcement_date,
    }


def _unknown(names, pointer_template, noun):
    """Reject members the contract does not define.

    The OpenAPI schemas set ``additionalProperties: false``; refusing unknown
    members here too means a client learns about a typo straight away instead
    of silently losing data.
    """
    return [
        errors.invalid_parameter_value(
            "{0} {1} is not recognised by this API.".format(noun, name),
            pointer=pointer_template.format(name),
        )
        for name in names
    ]


def _validate_text(attributes, name, max_length, collected):
    pointer = "/data/attributes/{0}".format(name)
    value = attributes.get(name)

    if value is None:
        collected.append(
            errors.missing_parameter(
                "The member {0} is required.".format(name), pointer=pointer
            )
        )
        return None
    if not isinstance(value, str):
        collected.append(
            errors.invalid_parameter_value(
                "{0} must be a string.".format(name), pointer=pointer
            )
        )
        return None

    trimmed = value.strip()
    if not trimmed:
        collected.append(
            errors.invalid_parameter_value(
                "{0} must not be blank.".format(name), pointer=pointer
            )
        )
        return None
    if len(trimmed) > max_length:
        collected.append(
            errors.invalid_parameter_value(
                "{0} must be at most {1} characters.".format(name, max_length),
                pointer=pointer,
            )
        )
        return None
    return trimmed


def _validate_date_time(attributes, name, collected):
    pointer = "/data/attributes/{0}".format(name)
    value = attributes.get(name)

    if value is None:
        collected.append(
            errors.missing_parameter(
                "The member {0} is required.".format(name), pointer=pointer
            )
        )
        return None
    if not isinstance(value, str):
        collected.append(
            errors.invalid_parameter_value(
                "{0} must be an RFC 3339 date-time string.".format(name),
                pointer=pointer,
            )
        )
        return None

    normalised = normalise_date_time(value)
    if normalised is None:
        collected.append(
            errors.invalid_parameter_value(
                "{0} must be an RFC 3339 date-time, for example "
                "2026-03-01T09:00:00Z.".format(name),
                pointer=pointer,
            )
        )
    return normalised


def normalise_date_time(value):
    """Parse an RFC 3339 date-time and render it in UTC, or return ``None``.

    The guidelines ask APIs to accept other timezone offsets but to normalise
    to UTC. Storing one canonical representation also keeps the sort key of the
    announcement date index consistent.
    """
    match = _RFC3339.match(value.strip())
    if not match:
        return None

    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    offset = match.group(8)

    try:
        moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None

    if offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6]))
        moment = moment - sign * delta

    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
