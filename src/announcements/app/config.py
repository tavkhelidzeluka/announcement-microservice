"""Runtime configuration, read once per execution environment.

Everything that varies per environment arrives through Lambda environment
variables so that the same artefact can be promoted from dev to production
unchanged.
"""
import os

#: Major version of the API contract this deployment implements. Clients must
#: send it in the ``Api-Version`` header (RESTful API Guidelines, "API
#: versioning": API's MUST reject client requests when no version is included
#: or when an invalid or unsupported version is included).
SUPPORTED_API_VERSION = "1"

#: Server defined pagination defaults. The guidelines require a default *and* a
#: maximum page size so that neither the client nor the service can be forced
#: into an unbounded read.
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
    """Single allowed CORS origin.

    CORS is deny-by-default: when no origin is configured, no
    ``Access-Control-Allow-Origin`` header is ever emitted.
    """
    return os.environ.get("ALLOWED_ORIGIN", "").strip()


def list_cache_max_age():
    return int(os.environ.get("LIST_CACHE_MAX_AGE_SECONDS", "60"))


def log_level():
    return os.environ.get("LOG_LEVEL", "INFO").upper()
