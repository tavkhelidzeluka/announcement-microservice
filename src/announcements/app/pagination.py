"""Cursor based pagination.

Cursors rather than offsets: announcements are appended continuously, so an
offset scheme would hand clients duplicated or skipped rows, and DynamoDB has
no ``OFFSET``. A cursor is an opaque, versioned envelope around DynamoDB's
``LastEvaluatedKey``; clients follow ``links.next`` instead of building them.
"""
import base64
import json

from . import config
from . import errors

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 512

#: What DynamoDB puts in ``LastEvaluatedKey`` for a query on the date index.
_KEY_MEMBERS = frozenset(("announcementId", "listPartition", "announcementDateId"))

DESCENDING = "desc"
ASCENDING = "asc"


def parse_limit(query):
    """Validate the reserved ``limit`` parameter.

    Absent means the server defined default; out of range is a client error.
    """
    raw = (query or {}).get("limit")
    if raw is None or raw == "":
        return config.DEFAULT_PAGE_SIZE

    try:
        limit = int(str(raw).strip())
    except ValueError:
        raise errors.invalid_parameter_value(
            "limit must be an integer between 1 and {0}.".format(config.MAX_PAGE_SIZE),
            parameter="limit",
        )

    if limit < 1 or limit > config.MAX_PAGE_SIZE:
        raise errors.invalid_parameter_value(
            "limit must be an integer between 1 and {0}.".format(config.MAX_PAGE_SIZE),
            parameter="limit",
        )
    return limit


def parse_sort(query):
    """Validate the reserved ``sort`` parameter and return the direction."""
    raw = (query or {}).get("sort")
    if raw is None or raw == "":
        return DESCENDING

    value = str(raw).strip()
    descending = value.startswith("-")
    prop = value[1:] if descending else value
    if prop != config.SORTABLE_PROPERTY:
        raise errors.invalid_parameter_value(
            "sort only supports {0} and -{0}.".format(config.SORTABLE_PROPERTY),
            parameter="sort",
        )
    return DESCENDING if descending else ASCENDING


def encode(last_evaluated_key, direction):
    """Turn a DynamoDB ``LastEvaluatedKey`` into a cursor."""
    if not last_evaluated_key:
        return None
    payload = {
        "v": _CURSOR_VERSION,
        "s": direction,
        "k": {name: value["S"] for name, value in last_evaluated_key.items()},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode(cursor, direction):
    """Turn a cursor back into a DynamoDB ``ExclusiveStartKey``.

    Every failure mode is a 400, never a 500, and never a read outside the
    collection the caller asked for.
    """
    if cursor is None or cursor == "":
        return None

    invalid = errors.invalid_parameter_value(
        "cursor is not a valid pagination cursor for this request. "
        "Follow links.next instead of constructing cursors.",
        parameter="cursor",
    )

    if len(cursor) > _MAX_CURSOR_LENGTH:
        raise invalid

    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except Exception:
        raise invalid

    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise invalid
    if payload.get("s") != direction:
        raise invalid

    key = payload.get("k")
    if not isinstance(key, dict) or set(key) != _KEY_MEMBERS:
        raise invalid
    if not all(isinstance(value, str) and value for value in key.values()):
        raise invalid
    # The index is single-partition by construction; refuse to be pointed at
    # anything else.
    if key["listPartition"] != "ALL":
        raise invalid

    return {name: {"S": value} for name, value in key.items()}


def links(base_path, limit, sort, self_cursor, next_cursor):
    """Build the ``first``/``self``/``next`` pagination links.

    ``prev`` and ``last`` are omitted: forward-only is what keeps cursors
    stable and cheap, and the guidelines list those links as optional.
    """
    result = {
        "self": _link(base_path, limit, sort, self_cursor),
        "first": _link(base_path, limit, sort, None),
    }
    if next_cursor:
        result["next"] = _link(base_path, limit, sort, next_cursor)
    return result


def _link(base_path, limit, sort, cursor):
    query = ["limit={0}".format(limit)]
    if sort != DESCENDING:
        query.append("sort={0}".format(config.SORTABLE_PROPERTY))
    else:
        query.append("sort=-{0}".format(config.SORTABLE_PROPERTY))
    if cursor:
        query.append("cursor={0}".format(cursor))
    return "{0}?{1}".format(base_path, "&".join(query))
