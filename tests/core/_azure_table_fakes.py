# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Reusable in-memory Azure Table fakes for core storage tests."""

from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4


class _FakeMetadata:
    """Mimics entity metadata with an etag."""

    def __init__(self, etag: str) -> None:
        self._etag = etag

    def get(self, key: str, default: Any = None) -> Any:
        """Return metadata value by key.

        :param key: Metadata key.
        :type key: str
        :param default: Default value.
        :type default: Any
        :return: The metadata value.
        :rtype: Any
        """
        if key == "etag":
            return self._etag
        return default


class _FakeEntity(dict):
    """Dict with a metadata attribute, mimicking Azure Table entity."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.metadata = _FakeMetadata(str(uuid4()))


class FakeTableClient:
    """In-memory fake Azure Table client with ETag simulation."""

    def __init__(self) -> None:
        self._entities: Dict[str, _FakeEntity] = {}

    def _key(self, partition_key: str, row_key: str) -> str:
        return f"{partition_key}:{row_key}"

    def create_entity(self, entity: Mapping[str, Any]) -> Dict[str, str]:
        """Create a new entity in the fake table.

        :param entity: Entity data to store.
        :type entity: Mapping[str, Any]
        :return: Dict containing the new ETag.
        :rtype: Dict[str, str]
        :raises ResourceExistsError: If entity already exists.
        """
        from azure.core.exceptions import ResourceExistsError

        key = self._key(entity["PartitionKey"], entity["RowKey"])
        if key in self._entities:
            raise ResourceExistsError("Entity already exists")
        self._entities[key] = _FakeEntity(dict(entity))
        return {"etag": self._entities[key].metadata.get("etag")}

    def get_entity(self, partition_key: str, row_key: str) -> _FakeEntity:
        """Retrieve an entity by its composite key.

        :param partition_key: Partition key.
        :type partition_key: str
        :param row_key: Row key.
        :type row_key: str
        :return: The stored entity.
        :rtype: _FakeEntity
        :raises ResourceNotFoundError: If entity does not exist.
        """
        from azure.core.exceptions import ResourceNotFoundError

        key = self._key(partition_key, row_key)
        if key not in self._entities:
            raise ResourceNotFoundError("Entity not found")
        return self._entities[key]

    def update_entity(
        self,
        entity: Mapping[str, Any],
        *,
        mode: Any = None,
        etag: Any = None,
        match_condition: Any = None,
    ) -> Dict[str, str]:
        """Update an entity with optional ETag concurrency check.

        :param entity: Entity data to update.
        :type entity: Mapping[str, Any]
        :param mode: Update mode (unused in fake).
        :type mode: Any
        :param etag: Expected ETag for concurrency control.
        :type etag: Any
        :param match_condition: Match condition (unused in fake).
        :type match_condition: Any
        :return: Dict containing the new ETag.
        :rtype: Dict[str, str]
        :raises HttpResponseError: If ETag does not match (412).
        :raises ResourceNotFoundError: If entity does not exist.
        """
        from azure.core.exceptions import HttpResponseError

        key = self._key(entity["PartitionKey"], entity["RowKey"])
        if key not in self._entities:
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("Entity not found")
        current = self._entities[key]
        if etag is not None and current.metadata.get("etag") != etag:
            error = HttpResponseError("Precondition failed")
            error.status_code = 412
            raise error
        self._entities[key] = _FakeEntity(dict(entity))
        return {"etag": self._entities[key].metadata.get("etag")}

    def delete_entity(
        self,
        partition_key: str,
        row_key: str,
        *,
        etag: Any = None,
        match_condition: Any = None,
    ) -> None:
        """Delete an entity from the fake table.

        :param partition_key: Partition key.
        :type partition_key: str
        :param row_key: Row key.
        :type row_key: str
        :param etag: Expected ETag for concurrency control.
        :type etag: Any
        :param match_condition: Match condition (unused in fake).
        :type match_condition: Any
        :raises ResourceNotFoundError: If entity does not exist.
        :raises HttpResponseError: If ETag does not match (412).
        """
        from azure.core.exceptions import ResourceNotFoundError

        key = self._key(partition_key, row_key)
        if key not in self._entities:
            raise ResourceNotFoundError("Entity not found")
        current = self._entities[key]
        if etag is not None and current.metadata.get("etag") != etag:
            from azure.core.exceptions import HttpResponseError

            error = HttpResponseError("Precondition failed")
            error.status_code = 412
            raise error
        del self._entities[key]

    def query_entities(
        self, query_filter: str, *, parameters: Optional[Dict[str, Any]] = None
    ) -> List[_FakeEntity]:
        """Query entities by partition key parameter.

        :param query_filter: OData-style filter string (minimally parsed).
        :type query_filter: str
        :param parameters: Query parameters including ``pk``.
        :type parameters: Optional[Dict[str, Any]]
        :return: Matching entities.
        :rtype: List[_FakeEntity]
        """
        results = []
        params = parameters or {}
        pk = params.get("pk", "staf")
        for entity in self._entities.values():
            if entity.get("PartitionKey") != pk:
                continue
            results.append(entity)
        return results
