"""POST /announcements.

Private: the Cognito authorizer has already validated the access token and the
``announcements/write`` scope, so this handler only deals with the payload.
"""
import uuid

from ..app import config
from ..app import http
from ..app import validation
from ..app.middleware import api_handler
from ..app.repository import AnnouncementRepository

_repository = None


def repository():
    global _repository
    if _repository is None:
        _repository = AnnouncementRepository(config.table_name())
    return _repository


@api_handler(expects_body=True)
def handler(request, client_id):
    attributes = validation.parse_create_document(request.json_body())

    # Server assigned RFC 4122 UUID, so the ordering key carries no meaning.
    announcement_id = str(uuid.uuid4())
    resource = repository().create(
        announcement_id, attributes, created_by=request.client_id or client_id
    )

    return http.response(
        201, {"data": resource}, request, {"Cache-Control": "no-store"}
    )
