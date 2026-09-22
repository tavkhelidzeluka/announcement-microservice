"""The cross-cutting behaviour every endpoint shares.

Wrapping the handlers in one decorator keeps the guideline obligations -
client identification, version negotiation, content negotiation, error
shielding, structured access logging - in a single reviewable place instead of
duplicated per endpoint.
"""
import functools
import time

from . import errors
from . import http
from . import logging_
from . import security

logger = logging_.get_logger()


def api_handler(expects_body=False):
    """Decorate a ``handler(request, client_id) -> proxy response``.

    Checks run in this order:

    1. ``Api-Key`` - who is calling (403 when missing or invalid)
    2. ``Api-Version`` - which contract they were built against (400)
    3. ``Accept`` / ``Content-Type`` - what they can speak (406 / 415)
    4. the endpoint itself
    """

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(event, context):
            started = time.time()
            request = http.Request(event)
            client_id = None
            try:
                client_id = security.identify_client(request)
                security.check_api_version(request)
                http.negotiate(request, expects_body)
                result = handler(request, client_id)
            except errors.ApiError as error:
                result = http.error_response(error, request)
                _log(request, result, client_id, started, error=error)
                return result
            except Exception:
                # Nothing internal escapes: the client gets an opaque 500
                # carrying only the request id, the detail stays in the log.
                logger.exception(
                    "Unhandled error while processing request",
                    extra={
                        "requestId": request.request_id,
                        "path": request.path,
                        "httpMethod": request.method,
                        "clientId": client_id,
                    },
                )
                result = http.error_response(errors.server_error(), request)
                _log(request, result, client_id, started)
                return result

            _log(request, result, client_id, started)
            return result

        return wrapper

    return decorator


def _log(request, result, client_id, started, error=None):
    fields = {
        "requestId": request.request_id,
        "httpMethod": request.method,
        "path": request.path,
        "statusCode": result["statusCode"],
        "durationMs": int((time.time() - started) * 1000),
        "clientId": client_id,
        "apiVersion": request.headers.get("Api-Version"),
    }
    if error is not None:
        fields["errorCode"] = error.code
    if result["statusCode"] >= 500:
        logger.error("Request failed", extra=fields)
    elif result["statusCode"] >= 400:
        logger.warning("Request rejected", extra=fields)
    else:
        logger.info("Request handled", extra=fields)
