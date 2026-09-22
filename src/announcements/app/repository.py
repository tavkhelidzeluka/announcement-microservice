"""DynamoDB access.

Table design
------------
The table is keyed on ``announcementId`` (a UUID), which is what a future
get-by-id would use. Listing needs a different access pattern - "all
announcements, newest first" - so it is served by a global secondary index:

    listPartition (HASH)  = "ALL"
    announcementDateId (RANGE) = "<announcementDate>#<announcementId>"

Because the sort key ends in the UUID, ordering is total and stable even when
two announcements share a timestamp, which is what makes a cursor point at
exactly one row.

The single-value partition key is a deliberate simplification: announcements
are a low-volume, read-heavy collection, so one partition (10 GB, 3 000 RCU)
is ample and it keeps "list everything in date order" a single ``Query``.
``docs/architecture.md`` describes the date-bucketed variant to move to if that
ever stops being true.

The item under the reserved id ``__stats__`` holds the collection size. It is
updated in the same transaction as the announcement, so ``meta.count`` is
exact rather than an eventually-consistent estimate. It carries no
``listPartition`` attribute and therefore never appears in the index, and so
never in a list response.
"""
import os

import boto3
from botocore.config import Config

from . import validation

STATS_ID = "__stats__"
LIST_PARTITION = "ALL"
INDEX_NAME = "announcementDateIndex"

_client = None


def _dynamodb():
    global _client
    if _client is None:
        _client = boto3.client(
            "dynamodb",
            region_name=os.environ.get("AWS_REGION"),
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=1,
                read_timeout=3,
            ),
        )
    return _client


def reset_client():
    """Test seam."""
    global _client
    _client = None


class AnnouncementRepository(object):
    def __init__(self, table_name, client=None):
        self.table_name = table_name
        self._explicit_client = client

    @property
    def client(self):
        return self._explicit_client or _dynamodb()

    def create(self, announcement_id, attributes, created_by=None):
        """Store an announcement and bump the collection counter atomically."""
        now = validation.utc_now()
        item = {
            "announcementId": {"S": announcement_id},
            "listPartition": {"S": LIST_PARTITION},
            "announcementDateId": {
                "S": "{0}#{1}".format(attributes["announcementDate"], announcement_id)
            },
            "title": {"S": attributes["title"]},
            "description": {"S": attributes["description"]},
            "announcementDate": {"S": attributes["announcementDate"]},
            "created": {"S": now},
            "lastModified": {"S": now},
        }
        if created_by:
            item["createdBy"] = {"S": created_by}

        self.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": item,
                        # A UUID collision is vanishingly unlikely, but a
                        # silent overwrite of somebody else's announcement is
                        # not a failure mode worth leaving open.
                        "ConditionExpression": "attribute_not_exists(announcementId)",
                    }
                },
                {
                    "Update": {
                        "TableName": self.table_name,
                        "Key": {"announcementId": {"S": STATS_ID}},
                        "UpdateExpression": "ADD announcementCount :one",
                        "ExpressionAttributeValues": {":one": {"N": "1"}},
                    }
                },
            ]
        )
        return to_resource(item)

    def list(self, limit, exclusive_start_key=None, descending=True):
        """Return ``(resources, last_evaluated_key)`` for one page."""
        request = {
            "TableName": self.table_name,
            "IndexName": INDEX_NAME,
            "KeyConditionExpression": "listPartition = :partition",
            "ExpressionAttributeValues": {":partition": {"S": LIST_PARTITION}},
            "ScanIndexForward": not descending,
            "Limit": limit,
        }
        if exclusive_start_key:
            request["ExclusiveStartKey"] = exclusive_start_key

        result = self.client.query(**request)
        resources = [to_resource(item) for item in result.get("Items", [])]
        return resources, result.get("LastEvaluatedKey")

    def count(self):
        """Total number of announcements, for ``meta.count``."""
        result = self.client.get_item(
            TableName=self.table_name,
            Key={"announcementId": {"S": STATS_ID}},
            ProjectionExpression="announcementCount",
        )
        item = result.get("Item")
        if not item:
            return 0
        return int(item["announcementCount"]["N"])


def to_resource(item):
    """Map a DynamoDB item onto the JSON API resource object in the contract."""
    resource = {
        "type": "announcements",
        "id": item["announcementId"]["S"],
        "attributes": {
            "title": item["title"]["S"],
            "description": item["description"]["S"],
            "announcementDate": item["announcementDate"]["S"],
        },
    }
    meta = {}
    for name in ("created", "lastModified"):
        if name in item:
            meta[name] = item[name]["S"]
    if meta:
        resource["meta"] = meta
    return resource
