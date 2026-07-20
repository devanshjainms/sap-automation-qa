# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Shared Azure Table Storage serialization and client helpers.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from azure.core.credentials import TokenCredential
from azure.data.tables import TableServiceClient
from src.core.contracts.storage import TableClientProtocol
from src.core.exceptions import EntityTooLargeError

_MAX_STRING_PROPERTY_BYTES = 64 * 1024
_MAX_ENTITY_BYTES = 1024 * 1024


def validate_entity_size(entity: Dict[str, Any], entity_kind: str) -> None:
    """
    Reject a table entity that violates Azure Table Storage size limits.

    :param entity: Entity that would be written.
    :param entity_kind: Human-readable entity kind, used in error messages.
    :raises EntityTooLargeError: If any string property exceeds 64 KiB, or
        the entity's total approximate size exceeds 1 MiB.
    """
    row_key = entity.get("RowKey", "<unknown>")
    total = 0
    for key, value in entity.items():
        total += len(key.encode("utf-16-le"))
        if isinstance(value, str):
            size = len(value.encode("utf-16-le"))
            if size > _MAX_STRING_PROPERTY_BYTES:
                raise EntityTooLargeError(
                    f"{entity_kind} {row_key}: property '{key}' is {size} bytes, "
                    f"exceeding the Azure Table Storage 64 KiB string property limit"
                )
            total += size
        elif value is not None:
            total += len(str(value).encode("utf-16-le"))
    if total > _MAX_ENTITY_BYTES:
        raise EntityTooLargeError(
            f"{entity_kind} {row_key}: entity is approximately {total} bytes, "
            f"exceeding the Azure Table Storage 1 MiB entity size limit"
        )


def datetime_to_string(value: Optional[datetime]) -> str:
    """Convert a datetime to an ISO-8601 string for table storage.

    :param value: Datetime to convert.
    :returns: ISO string, or ``""`` when ``value`` is None.
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def string_to_datetime(value: Optional[str]) -> Optional[datetime]:
    """Convert an ISO-8601 string back to a datetime.

    :param value: ISO string, possibly empty or None.
    :returns: Parsed datetime, or None when ``value`` is empty/None.
    """
    return datetime.fromisoformat(value) if value else None


def require_field(entity: Dict[str, Any], field: str, entity_kind: str) -> Any:
    """Fetch a required field from a table entity.

    :param entity: Raw table entity.
    :param field: Required field name.
    :param entity_kind: Human-readable entity kind, used in the error message.
    :returns: The field's value.
    :raises ValueError: If the field is missing.
    """
    if field not in entity:
        row_key = entity.get("RowKey", "<unknown>")
        raise ValueError(
            f"Malformed {entity_kind} entity {row_key}: missing required field '{field}'"
        )
    return entity[field]


def close_resource(resource: Any) -> None:
    """Close a resource when it exposes a callable ``close`` method.

    :param resource: Resource to close, or None.
    """
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def extract_etag(value: Any) -> Optional[str]:
    """Extract a concrete ETag from an Azure response or table entity.

    :param value: Azure response or table entity.
    :returns: ETag when present, otherwise None.
    """
    metadata = getattr(value, "metadata", None)
    etag = metadata.get("etag") if metadata is not None else None
    if not isinstance(etag, str) and hasattr(value, "get"):
        candidate = value.get("etag")
        etag = candidate if isinstance(candidate, str) else None
    return etag


def create_table_resources(
    endpoint: str, table_name: str, credential: TokenCredential
) -> tuple[TableServiceClient, TableClientProtocol]:
    """Build owning service resources and a table client.

    :param endpoint: Azure Table Storage endpoint URL.
    :param table_name: Table to create (if missing) and connect to.
    :param credential: Caller-owned Azure credential.
    :returns: Owning service client and table client.
    """
    service = TableServiceClient(endpoint=endpoint, credential=credential)
    try:
        service.create_table_if_not_exists(table_name)
        client = service.get_table_client(table_name)
    except Exception:
        close_resource(service)
        raise
    return service, client
