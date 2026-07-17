# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Deterministic extractor producing normalized knowledge records from the
authoritative HA/backup test catalog (``src/vars/input-api.yaml``).
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from src.core.exceptions import HAExtractionError
from src.core.models.knowledge import AppliesTo, KnowledgeKind, KnowledgeRecord, KnowledgeRisk

HA_TEST_NAMESPACE = "ha-test"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_HA_CATALOG_PATH = REPO_ROOT / "src" / "vars" / "input-api.yaml"
KIND_BY_GROUP_PREFIX: Dict[str, KnowledgeKind] = {
    "HA_": KnowledgeKind.HA_FUNCTIONAL_TEST,
    "BACKUP_": KnowledgeKind.BACKUP_TEST,
}
RISK_BY_RAW_VALUE: Dict[str, KnowledgeRisk] = {
    "read-only": KnowledgeRisk.READ_ONLY,
    "destructive": KnowledgeRisk.DESTRUCTIVE,
}
TOPOLOGY_BY_RAW_VALUE: Dict[str, str] = {
    "scale_up": "scale-up",
    "scale_out_hsr": "scale-out-hsr",
}
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class _ExtractionContext:
    """Source metadata shared by every record in one catalog."""

    source_path: Path
    relative_path: str
    source_hash: str


def extract_ha_tests(
    source_path: Optional[Union[str, Path]] = None,
    repo_root: Optional[Union[str, Path]] = None,
) -> List[KnowledgeRecord]:
    """Extract normalized :class:`KnowledgeRecord` instances from every
    HA/backup test case in the catalog.

    :param source_path: Path to the ``input-api.yaml`` catalog file.
        Defaults to ``src/vars/input-api.yaml`` in this repository.
    :type source_path: Optional[Union[str, pathlib.Path]]
    :param repo_root: Root used to compute the stable ``source_ref`` path
        prefix. Defaults to this repository's root.
    :type repo_root: Optional[Union[str, pathlib.Path]]
    :returns: One normalized record per HA/backup test case.
    :rtype: List[KnowledgeRecord]
    :raises HAExtractionError: If the source file is missing or malformed,
        a test case lacks required ``mcp`` metadata, risk/provides values
        are invalid, or two test cases normalize to the same knowledge ID.
    """
    resolved_path = Path(source_path) if source_path is not None else DEFAULT_HA_CATALOG_PATH
    resolved_repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT

    if not resolved_path.is_file():
        raise HAExtractionError(f"HA catalog source file not found: {resolved_path}")

    document, raw_bytes = _load_catalog(resolved_path)
    context = _ExtractionContext(
        source_path=resolved_path,
        relative_path=_relative_source_path(resolved_path, resolved_repo_root),
        source_hash=f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
    )
    records: List[KnowledgeRecord] = []
    seen_ids: Dict[str, str] = {}

    for group in document["test_groups"]:
        group_name, kind, test_cases = _parse_group(group, resolved_path)
        for test_case in test_cases:
            record = _build_record(test_case, group_name, kind, context)
            _register_record(record, seen_ids)
            records.append(record)

    return records


def _load_catalog(source_path: Path) -> tuple[dict[str, Any], bytes]:
    """Load and validate the HA catalog's top-level structure."""
    raw_bytes = source_path.read_bytes()
    try:
        document = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as exc:
        raise HAExtractionError(f"{source_path}: invalid YAML ({exc})") from exc
    if not isinstance(document, dict) or not isinstance(document.get("test_groups"), list):
        raise HAExtractionError(
            f"{source_path}: expected a mapping with a top-level 'test_groups' list"
        )
    return document, raw_bytes


def _parse_group(
    group: object,
    source_path: Path,
) -> tuple[str, KnowledgeKind, list[object]]:
    """Validate one catalog group and return its normalized metadata."""
    if not isinstance(group, dict):
        raise HAExtractionError(
            f"{source_path}: test_groups entry must be a mapping, " f"got {type(group).__name__}"
        )
    group_name = group.get("name")
    if not group_name or not isinstance(group_name, str):
        raise HAExtractionError(f"{source_path}: test_groups entry missing 'name'")
    test_cases = group.get("test_cases")
    if not isinstance(test_cases, list):
        raise HAExtractionError(f"{source_path}: group '{group_name}' missing 'test_cases' list")
    return group_name, _resolve_kind(group_name, source_path), test_cases


def _register_record(record: KnowledgeRecord, seen_ids: Dict[str, str]) -> None:
    """Reject duplicate normalized IDs and register a unique record."""
    existing_ref = seen_ids.get(record.id)
    if existing_ref is not None:
        raise HAExtractionError(
            f"Duplicate normalized knowledge id '{record.id}' "
            f"(from {record.source_ref} and {existing_ref})"
        )
    seen_ids[record.id] = record.source_ref


def _resolve_kind(group_name: str, source_path: Path) -> KnowledgeKind:
    """Determine the knowledge kind from a group name prefix.

    :param group_name: The raw test group name (e.g. ``HA_DB_HANA``).
    :type group_name: str
    :param source_path: Path to the source file, used in error messages.
    :type source_path: pathlib.Path
    :returns: The resolved knowledge kind.
    :rtype: KnowledgeKind
    :raises HAExtractionError: If no known prefix matches.
    """
    for prefix, kind in KIND_BY_GROUP_PREFIX.items():
        if group_name.startswith(prefix):
            return kind
    raise HAExtractionError(
        f"{source_path}: group '{group_name}' does not match any known "
        f"prefix ({list(KIND_BY_GROUP_PREFIX.keys())})"
    )


def _build_record(
    test_case: object,
    group_name: str,
    kind: KnowledgeKind,
    context: _ExtractionContext,
) -> KnowledgeRecord:
    """Build one normalized record from a raw test case entry.

    :param test_case: One item from a group's ``test_cases`` list.
    :type test_case: object
    :param group_name: The parent group name (e.g. ``HA_DB_HANA``).
    :type group_name: str
    :param kind: The knowledge kind resolved from the group prefix.
    :type kind: KnowledgeKind
    :param context: Source metadata shared by all extracted records.
    :type context: _ExtractionContext
    :returns: The normalized knowledge record.
    :rtype: KnowledgeRecord
    :raises HAExtractionError: If the entry is not a mapping, is missing
        required fields, or has invalid ``mcp`` metadata.
    """
    if not isinstance(test_case, dict):
        raise HAExtractionError(
            f"{context.source_path}: test_cases entry in group '{group_name}' must be a mapping, "
            f"got {type(test_case).__name__}"
        )

    name, task_name, description = _parse_test_identity(test_case, group_name, context.source_path)
    risk, provides = _parse_mcp_metadata(test_case, task_name, group_name, context.source_path)
    applies_to = _build_applies_to(test_case.get("applicability"), group_name, context.source_path)
    group_slug = group_name.lower().replace("_", "-")

    return KnowledgeRecord(
        id=f"{HA_TEST_NAMESPACE}.{group_slug}.{task_name}",
        kind=kind,
        name=name.strip(),
        description=description.strip(),
        applies_to=applies_to,
        provides=provides,
        risk=risk,
        execution_ref=f"{HA_TEST_NAMESPACE}:{group_name}/{task_name}",
        source_ref=f"{context.relative_path}#{group_name}/{task_name}",
        source_hash=context.source_hash,
    )


def _parse_test_identity(
    test_case: dict[str, Any],
    group_name: str,
    source_path: Path,
) -> tuple[str, str, str]:
    """Validate and return a test case's required identity fields."""
    values = {
        "name": test_case.get("name"),
        "task_name": test_case.get("task_name"),
        "description": test_case.get("description"),
    }
    missing_fields = [field for field, value in values.items() if not value]
    if missing_fields:
        raise HAExtractionError(
            f"{source_path}: test case in group '{group_name}' missing required field(s): "
            f"{missing_fields}"
        )
    name = values["name"]
    task_name = values["task_name"]
    description = values["description"]
    if (
        not isinstance(name, str)
        or not isinstance(task_name, str)
        or not isinstance(description, str)
    ):
        raise HAExtractionError(
            f"{source_path}: test case 'name', 'task_name' and 'description' must be strings "
            f"(group={group_name!r}, task_name={task_name!r})"
        )

    if not _SLUG_RE.match(task_name):
        raise HAExtractionError(
            f"{source_path}: test case in group '{group_name}' has invalid task_name "
            f"{task_name!r} (must be lowercase alphanumeric with internal hyphens)"
        )
    return name, task_name, description


def _parse_mcp_metadata(
    test_case: dict[str, Any],
    task_name: str,
    group_name: str,
    source_path: Path,
) -> tuple[KnowledgeRisk, tuple[str, ...]]:
    """Validate explicit risk and evidence metadata for one test case."""
    mcp_block = test_case.get("mcp")
    if not isinstance(mcp_block, dict):
        raise HAExtractionError(
            f"{source_path}: test case '{task_name}' in group '{group_name}' "
            f"missing required 'mcp' metadata block"
        )

    raw_risk = mcp_block.get("risk")
    if raw_risk not in RISK_BY_RAW_VALUE:
        raise HAExtractionError(
            f"{source_path}: test case '{task_name}' in group '{group_name}' "
            f"has invalid mcp.risk value {raw_risk!r} "
            f"(allowed: {list(RISK_BY_RAW_VALUE.keys())})"
        )

    raw_provides = mcp_block.get("provides")
    if not isinstance(raw_provides, list) or not raw_provides:
        raise HAExtractionError(
            f"{source_path}: test case '{task_name}' in group '{group_name}' "
            f"has invalid mcp.provides (must be a non-empty list)"
        )
    if any(not isinstance(item, str) or not _SLUG_RE.match(item) for item in raw_provides):
        invalid_item = next(
            item for item in raw_provides if not isinstance(item, str) or not _SLUG_RE.match(item)
        )
        raise HAExtractionError(
            f"{source_path}: test case '{task_name}' in group '{group_name}' "
            f"has invalid mcp.provides entry {invalid_item!r} "
            f"(must be lowercase alphanumeric with internal hyphens)"
        )
    if len(raw_provides) != len(set(raw_provides)):
        raise HAExtractionError(
            f"{source_path}: test case '{task_name}' in group '{group_name}' "
            f"has duplicate entries in mcp.provides"
        )
    return RISK_BY_RAW_VALUE[raw_risk], tuple(sorted(raw_provides))


def _build_applies_to(applicability: object, group_name: str, source_path: Path) -> AppliesTo:
    """Map a raw ``applicability`` block to normalized :class:`AppliesTo`.

    :param applicability: The raw applicability value from a test case.
    :type applicability: object
    :param group_name: Parent group name, used in error messages.
    :type group_name: str
    :param source_path: Path to the source file, used in error messages.
    :type source_path: pathlib.Path
    :returns: The normalized applicability filters.
    :rtype: AppliesTo
    """
    if applicability is None:
        return AppliesTo()
    if not isinstance(applicability, dict):
        raise HAExtractionError(
            f"{source_path}: 'applicability' in group '{group_name}' must be a mapping, "
            f"got {type(applicability).__name__}"
        )

    raw_topology = applicability.get("topology")
    topology: List[str] = []
    if raw_topology is None:
        pass
    elif not isinstance(raw_topology, list):
        raise HAExtractionError(
            f"{source_path}: applicability.topology in group '{group_name}' "
            f"must be a list, got {type(raw_topology).__name__}"
        )
    else:
        for item in raw_topology:
            if not isinstance(item, str) or item not in TOPOLOGY_BY_RAW_VALUE:
                raise HAExtractionError(
                    f"{source_path}: unsupported applicability.topology value {item!r} "
                    f"in group '{group_name}'"
                )
            topology.append(TOPOLOGY_BY_RAW_VALUE[item])
        topology = sorted(set(topology))

    return AppliesTo(topology=tuple(topology))


def _relative_source_path(file_path: Path, repo_root: Path) -> str:
    """Compute a stable, forward-slashed path for use in ``source_ref``.

    :param file_path: Absolute path to the source file.
    :type file_path: pathlib.Path
    :param repo_root: Root the returned path is made relative to.
    :type repo_root: pathlib.Path
    :returns: The path relative to ``repo_root``, using forward slashes.
    :rtype: str
    """
    resolved_file = file_path.resolve()
    resolved_root = repo_root.resolve()
    try:
        relative = resolved_file.relative_to(resolved_root)
    except ValueError:
        relative = Path(os.path.relpath(resolved_file, resolved_root))
    return relative.as_posix()
