"""Error model.

Error payloads follow the JSON API error object shape, and the ``code`` member
is drawn from the standard PIL error code list (RESTful API Guidelines,
Appendix A - Reserved names / Standard errors).

``ApiError`` is the single way a handler signals failure. Anything else that
escapes a handler is converted into an opaque ``SERVER_ERROR`` so that no
internal failure detail ever reaches a client (guidelines, "Hide internal error
details").
"""


class ApiError(Exception):
    """A failure that can be rendered as a JSON API error document."""

    def __init__(self, status, code, title, detail=None, source=None, headers=None):
        super().__init__("{0} {1}: {2}".format(status, code, detail or title))
        self.status = int(status)
        self.code = code
        self.title = title
        self.detail = detail
        self.source = source
        self.headers = headers or {}

    def as_error_object(self, request_id=None):
        error = {"status": str(self.status), "code": self.code, "title": self.title}
        if request_id:
            error["id"] = request_id
        if self.detail:
            error["detail"] = self.detail
        if self.source:
            error["source"] = self.source
        return error


class ApiErrors(ApiError):
    """Several failures reported together.

    JSON API models ``errors`` as an array, so validating a payload once and
    reporting everything that is wrong with it is both cheaper for the client
    and friendlier than failing on the first problem.
    """

    def __init__(self, errors):
        if not errors:
            raise ValueError("ApiErrors requires at least one error")
        first = errors[0]
        super().__init__(first.status, first.code, first.title, first.detail, first.source)
        self.errors = errors

    def as_error_objects(self, request_id=None):
        return [error.as_error_object(request_id) for error in self.errors]


# --- Factories for the standard error codes -------------------------------


def missing_api_version():
    return ApiError(
        400,
        "MISSING_API_VERSION",
        "Missing API version",
        "The Api-Version header is required.",
        {"parameter": "Api-Version"},
    )


def invalid_api_version(supported):
    return ApiError(
        400,
        "INVALID_API_VERSION",
        "Invalid API version",
        "This endpoint only supports Api-Version {0}.".format(supported),
        {"parameter": "Api-Version"},
    )


def missing_api_key():
    return ApiError(
        403,
        "MISSING_API_KEY",
        "Missing API key",
        "The Api-Key header is required.",
        {"parameter": "Api-Key"},
    )


def invalid_api_key():
    return ApiError(
        403,
        "INVALID_API_KEY",
        "Invalid API key",
        "The supplied Api-Key is not valid.",
        {"parameter": "Api-Key"},
    )


def invalid_parameter_value(detail, parameter=None, pointer=None):
    return ApiError(
        400,
        "INVALID_PARAMETER_VALUE",
        "Invalid parameter value",
        detail,
        _source(parameter, pointer),
    )


def missing_parameter(detail, parameter=None, pointer=None):
    return ApiError(
        400,
        "MISSING_PARAMETER",
        "Missing required parameter",
        detail,
        _source(parameter, pointer),
    )


def bad_request(detail):
    return ApiError(400, "BAD_REQUEST", "Bad request", detail)


def client_generated_id_not_supported():
    return ApiError(
        403,
        "CLIENT_GENERATED_ID_NOT_SUPPORTED",
        "Client generated id not supported",
        "Announcement ids are assigned by the server.",
        {"pointer": "/data/id"},
    )


def resource_type_mismatch(expected):
    return ApiError(
        409,
        "RESOURCE_TYPE_MISMATCH",
        "Resource type mismatch",
        "Expected data.type to be {0}.".format(expected),
        {"pointer": "/data/type"},
    )


def not_acceptable(media_type):
    return ApiError(
        406,
        "NOT_ACCEPTABLE",
        "Not acceptable",
        "This API can only produce {0}.".format(media_type),
    )


def unsupported_media_type(media_type):
    return ApiError(
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "Unsupported media type",
        "This API only consumes {0}.".format(media_type),
    )


def server_error():
    return ApiError(
        500,
        "SERVER_ERROR",
        "Server error",
        "The request could not be processed. Quote the error id when reporting this.",
    )


def _source(parameter, pointer):
    if parameter:
        return {"parameter": parameter}
    if pointer:
        return {"pointer": pointer}
    return None
