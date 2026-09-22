"""HTTP plumbing between API Gateway's proxy event and the handlers."""
import base64
import hashlib
import json

from . import config
from . import errors


class Headers(object):
    """Case-insensitive view over the request headers (RFC 7230)."""

    def __init__(self, raw):
        self._values = {}
        for key, value in (raw or {}).items():
            if key is not None:
                self._values[key.lower()] = value

    def get(self, name, default=None):
        value = self._values.get(name.lower())
        return default if value is None else value

    def __contains__(self, name):
        return name.lower() in self._values


class Request(object):
    """The parts of an API Gateway proxy event the handlers care about."""

    def __init__(self, event):
        self.event = event or {}
        context = self.event.get("requestContext") or {}
        self.request_id = context.get("requestId") or "unknown"
        self.method = (self.event.get("httpMethod") or "").upper()
        self.path = self.event.get("path") or ""
        self.headers = Headers(self.event.get("headers"))
        self.query = self.event.get("queryStringParameters") or {}
        self.origin = self.headers.get("Origin")
        self.client_id = self._client_id(context)

    @staticmethod
    def _client_id(context):
        """OAuth client that presented the access token, when there was one."""
        claims = ((context.get("authorizer") or {}).get("claims")) or {}
        return claims.get("client_id") or claims.get("sub")

    def raw_body(self):
        body = self.event.get("body")
        if body is None:
            return None
        if self.event.get("isBase64Encoded"):
            return base64.b64decode(body).decode("utf-8")
        return body

    def json_body(self):
        """Parse the request body, or raise a guideline-shaped 400."""
        raw = self.raw_body()
        if raw is None or raw.strip() == "":
            raise errors.missing_parameter(
                "A request body is required.", pointer="/data"
            )
        try:
            return json.loads(raw)
        except ValueError:
            raise errors.bad_request("The request body is not valid JSON.")


def negotiate(request, expects_body):
    """Content negotiation: 406 on an unsatisfiable ``Accept``, 415 on a
    non-JSON body. Both headers are optional and default to JSON.
    """
    accept = request.headers.get("Accept")
    if accept and not _accepts_json(accept):
        raise errors.not_acceptable(config.JSON_MEDIA_TYPE)

    if expects_body and request.raw_body():
        content_type = request.headers.get("Content-Type")
        if content_type and not _is_json_media_type(content_type):
            raise errors.unsupported_media_type(config.JSON_MEDIA_TYPE)


def _accepts_json(accept):
    for entry in accept.split(","):
        media_type = entry.split(";")[0].strip().lower()
        if media_type in ("*/*", "application/*", config.JSON_MEDIA_TYPE):
            return True
        # application/vnd.api+json and friends.
        if media_type.startswith("application/") and media_type.endswith("+json"):
            return True
    return False


def _is_json_media_type(content_type):
    return content_type.split(";")[0].strip().lower() == config.JSON_MEDIA_TYPE


def etag_for(document):
    """Strong entity tag over the exact bytes we are about to send."""
    digest = hashlib.sha256(serialise(document).encode("utf-8")).hexdigest()
    return '"{0}"'.format(digest[:32])


def serialise(document):
    # Sorted keys keep the ETag stable across invocations.
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def response(status, document=None, request=None, headers=None):
    """Build an API Gateway proxy response."""
    final_headers = {}
    if document is not None:
        final_headers["Content-Type"] = config.JSON_MEDIA_TYPE
    final_headers.update(headers or {})
    final_headers.update(cors_headers(request))

    result = {
        "statusCode": status,
        "headers": final_headers,
        "body": "" if document is None else serialise(document),
    }
    return result


def cors_headers(request):
    """Deny-by-default CORS: only the configured origin is ever echoed."""
    allowed = config.allowed_origin()
    headers = {"Vary": "Origin, Accept-Encoding"}
    if allowed and request is not None and request.origin == allowed:
        headers["Access-Control-Allow-Origin"] = allowed
    return headers


def error_response(error, request):
    request_id = request.request_id if request else None
    if isinstance(error, errors.ApiErrors):
        objects = error.as_error_objects(request_id)
    else:
        objects = [error.as_error_object(request_id)]

    document = {"errors": objects}
    if request_id:
        document["meta"] = {"requestId": request_id}

    headers = {"Cache-Control": "no-store"}
    headers.update(error.headers)
    return response(error.status, document, request, headers)
