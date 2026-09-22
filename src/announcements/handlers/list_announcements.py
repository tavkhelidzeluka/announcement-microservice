"""GET /announcements - list announcements, cursor paginated."""
from ..app import config
from ..app import http
from ..app import pagination
from ..app.middleware import api_handler
from ..app.repository import AnnouncementRepository

_repository = None


def repository():
    """Built lazily and reused, so the DynamoDB client survives cold starts."""
    global _repository
    if _repository is None:
        _repository = AnnouncementRepository(config.table_name())
    return _repository


@api_handler(expects_body=False)
def handler(request, client_id):
    limit = pagination.parse_limit(request.query)
    direction = pagination.parse_sort(request.query)
    supplied_cursor = (request.query or {}).get("cursor")
    start_key = pagination.decode(supplied_cursor, direction)

    resources, last_evaluated_key = repository().list(
        limit=limit,
        exclusive_start_key=start_key,
        descending=direction == pagination.DESCENDING,
    )
    next_cursor = pagination.encode(last_evaluated_key, direction)

    document = {
        "data": resources,
        "meta": {"count": repository().count(), "pageSize": len(resources)},
        "links": pagination.links(
            _base_path(request), limit, direction, supplied_cursor, next_cursor
        ),
    }

    # Conditional GET: an unchanged collection costs the client nothing but a
    # round trip, and costs us no bandwidth.
    etag = http.etag_for(document)
    cache_control = "public, max-age={0}".format(config.list_cache_max_age())
    if request.headers.get("If-None-Match") == etag:
        return http.response(
            304, None, request, {"ETag": etag, "Cache-Control": cache_control}
        )

    return http.response(
        200, document, request, {"ETag": etag, "Cache-Control": cache_control}
    )


def _base_path(request):
    """Path the links are built on.

    ``requestContext.path`` is the path as the caller actually requested it,
    so the links keep working behind a custom domain with a base path mapping
    as well as against a raw stage URL.
    """
    context_path = (request.event.get("requestContext") or {}).get("path")
    return context_path or "{0}/announcements".format(config.SERVICE_BASE_PATH)
