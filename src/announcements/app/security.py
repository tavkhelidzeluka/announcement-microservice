"""Client identification through the ``Api-Key`` header.

API Gateway usage plan keys are unusable here: they are hard-wired to the
``x-api-key`` header, which the guidelines override with ``Api-Key``. The keys
live in Secrets Manager instead, cached per execution environment so the hot
path is a string comparison rather than a network call.
"""
import hmac
import json
import os
import time

import boto3

from . import config
from . import errors

_CACHE_TTL_SECONDS = 300
_cache = {"value": None, "expires_at": 0.0}
_client = None


def _secrets_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION")
        )
    return _client


def _load_keys():
    """Return the set of accepted API keys, refreshing the cache when stale."""
    now = time.time()
    if _cache["value"] is not None and now < _cache["expires_at"]:
        return _cache["value"]

    secret = _secrets_client().get_secret_value(SecretId=config.api_key_secret_id())
    payload = json.loads(secret["SecretString"])

    # Accepting a list as well as a single object keeps key rotation and
    # multi-client onboarding a data change rather than a code change.
    if isinstance(payload, list):
        entries = payload
    else:
        entries = [payload]
    keys = {}
    for entry in entries:
        key = entry.get("apiKey")
        if key:
            keys[key] = entry.get("clientId", "unknown")

    _cache["value"] = keys
    _cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return keys


def reset_cache():
    """Test seam."""
    _cache["value"] = None
    _cache["expires_at"] = 0.0
    global _client
    _client = None


def identify_client(request):
    """Validate the ``Api-Key`` header and return the client id behind it."""
    supplied = request.headers.get("Api-Key")
    if not supplied:
        raise errors.missing_api_key()

    for known_key, client_id in _load_keys().items():
        # Constant time: a timing oracle on an API key is a credential leak.
        if hmac.compare_digest(supplied, known_key):
            return client_id
    raise errors.invalid_api_key()


def check_api_version(request):
    """Reject requests without a usable ``Api-Version`` header."""
    version = request.headers.get("Api-Version")
    if version is None or version.strip() == "":
        raise errors.missing_api_version()
    if version.strip() != config.SUPPORTED_API_VERSION:
        raise errors.invalid_api_version(config.SUPPORTED_API_VERSION)
