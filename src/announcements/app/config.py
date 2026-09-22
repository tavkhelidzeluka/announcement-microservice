"""Runtime configuration.

Everything environment-specific arrives through Lambda environment variables,
so the same artefact is promoted from dev to production unchanged.
"""
import os

#: Major version clients must send in the ``Api-Version`` header.
SUPPORTED_API_VERSION = "1"

#: Server defined page size: a default and a hard maximum, both required.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: Only sortable property, exposed through the ``sort`` reserved parameter.
SORTABLE_PROPERTY = "announcementDate"

#: The one media type this API speaks.
JSON_MEDIA_TYPE = "application/json"

#: Service base path, used to build the pagination links.
SERVICE_BASE_PATH = "/communications"

RESOURCE_TYPE = "announcements"


def table_name():
    return os.environ["TABLE_NAME"]


def api_key_secret_id():
    return os.environ["API_KEY_SECRET_ID"]


def allowed_origin():
    """Single allowed CORS origin. Unset means no origin is ever echoed."""
    return os.environ.get("ALLOWED_ORIGIN", "").strip()


def list_cache_max_age():
    return int(os.environ.get("LIST_CACHE_MAX_AGE_SECONDS", "60"))


def log_level():
    return os.environ.get("LOG_LEVEL", "INFO").upper()
