# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Deterministic extractor producing normalized knowledge records from the
authoritative configuration-check YAML definitions
(``src/roles/configuration_checks/tasks/files/*.yml``).
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Union
import yaml

from src.core.exceptions import ConfigurationCheckExtractionError
from src.core.models.knowledge import AppliesTo, KnowledgeKind, KnowledgeRecord, KnowledgeRisk

CONFIGURATION_CHECK_NAMESPACE = "configuration-check"
_RAW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIGURATION_CHECKS_DIR = (
    REPO_ROOT / "src" / "roles" / "configuration_checks" / "tasks" / "files"
)
OS_FAMILY_BY_RAW_OS_TYPE: Dict[str, str] = {
    "SLES_SAP": "suse",
    "REDHAT": "redhat",
    "OracleLinux": "oraclelinux",
    "ORACLELINUX": "oraclelinux",
    "Windows": "windows",
}
COMPONENT_BY_RAW_DATABASE_TYPE: Dict[str, str] = {
    "HANA": "hana",
    "SQLSERVER": "sqlserver",
    "Oracle": "oracle",
    "Db2": "db2",
    "ASE": "ase",
}
TOPOLOGY_BY_RAW_HIGH_AVAILABILITY: Dict[str, str] = {
    "scale_up": "scale-up",
    "scale_out": "scale-out",
}


def extract_configuration_checks(
    source_dir: Optional[Union[str, Path]] = None,
    repo_root: Optional[Union[str, Path]] = None,
) -> List[KnowledgeRecord]:
    """
    Extract normalized :class:`KnowledgeRecord` instances from every
    configuration-check YAML file in ``source_dir``.

    :param source_dir: Directory containing ``*.yml`` configuration-check
        files. Defaults to
        ``src/roles/configuration_checks/tasks/files`` in this repository.
    :type source_dir: Optional[Union[str, pathlib.Path]]
    :param repo_root: Root used to compute the stable, human-readable
        ``source_ref`` path prefix. Defaults to this repository's root.
    :type repo_root: Optional[Union[str, pathlib.Path]]
    :returns: One normalized record per source check, across all files.
    :rtype: List[KnowledgeRecord]
    :raises ConfigurationCheckExtractionError: If the source directory is
        missing, a file has an unsupported structure, a check is missing a
        required field, an applicability value is malformed/unmapped, or two
        checks normalize to the same knowledge id.
    """
    resolved_source_dir = (
        Path(source_dir) if source_dir is not None else DEFAULT_CONFIGURATION_CHECKS_DIR
    )
    resolved_repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT

    if not resolved_source_dir.is_dir():
        raise ConfigurationCheckExtractionError(
            f"Configuration-check source directory not found: {resolved_source_dir}"
        )

    records: List[KnowledgeRecord] = []
    source_ref_by_id: Dict[str, str] = {}

    for yaml_path in sorted(resolved_source_dir.glob("*.yml")):
        for record in _extract_file(yaml_path, resolved_repo_root):
            existing_source_ref = source_ref_by_id.get(record.id)
            if existing_source_ref is not None:
                raise ConfigurationCheckExtractionError(
                    f"Duplicate normalized knowledge id '{record.id}' "
                    f"(from {record.source_ref} and {existing_source_ref})"
                )
            source_ref_by_id[record.id] = record.source_ref
            records.append(record)

    return records


def _extract_file(yaml_path: Path, repo_root: Path) -> List[KnowledgeRecord]:
    """Parse one configuration-check YAML file into normalized records.

    :param yaml_path: Path to the configuration-check YAML file.
    :type yaml_path: pathlib.Path
    :param repo_root: Root used to compute the stable ``source_ref`` prefix.
    :type repo_root: pathlib.Path
    :returns: Normalized records for every check declared in the file.
    :rtype: List[KnowledgeRecord]
    :raises ConfigurationCheckExtractionError: If the file is not valid YAML
        or does not have the expected ``checks: [...]`` structure.
    """
    raw_bytes = yaml_path.read_bytes()
    try:
        document = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as exc:
        raise ConfigurationCheckExtractionError(f"{yaml_path}: invalid YAML ({exc})") from exc

    if not isinstance(document, dict) or not isinstance(document.get("checks"), list):
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: expected a mapping with a top-level 'checks' list"
        )

    relative_path = _relative_source_path(yaml_path, repo_root)
    source_hash = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"

    return [
        _build_record(entry, yaml_path, relative_path, source_hash) for entry in document["checks"]
    ]


def _build_record(
    entry: object, yaml_path: Path, relative_path: str, source_hash: str
) -> KnowledgeRecord:
    """Build one normalized :class:`KnowledgeRecord` from a raw check entry.

    :param entry: One item of the source file's ``checks`` list.
    :type entry: object
    :param yaml_path: Path to the source YAML file, used in error messages.
    :type yaml_path: pathlib.Path
    :param relative_path: Stable, repo-relative path used in ``source_ref``.
    :type relative_path: str
    :param source_hash: ``sha256:<hex>`` digest of the exact source file
        bytes, shared by every check extracted from that file.
    :type source_hash: str
    :returns: The normalized record for this check.
    :rtype: KnowledgeRecord
    :raises ConfigurationCheckExtractionError: If the entry is not a
        mapping, is missing a required field, or has a malformed
        applicability block.
    """
    if not isinstance(entry, dict):
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: check entry must be a mapping, got {type(entry).__name__}"
        )

    raw_id = entry.get("id")
    name = entry.get("name")
    description = entry.get("description")
    missing_fields = [
        field_name
        for field_name, value in (("id", raw_id), ("name", name), ("description", description))
        if not value
    ]
    if missing_fields:
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: check {raw_id!r} is missing required field(s): {missing_fields}"
        )
    if not isinstance(raw_id, str) or not isinstance(name, str) or not isinstance(description, str):
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: check 'id', 'name' and 'description' must be strings (id={raw_id!r})"
        )

    raw_id = raw_id.strip()
    name = name.strip()
    description = description.strip()
    blank_fields = [
        field_name
        for field_name, value in (("id", raw_id), ("name", name), ("description", description))
        if not value
    ]
    if blank_fields:
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: check {raw_id!r} is missing required field(s): {blank_fields}"
        )
    if not _RAW_ID_RE.fullmatch(raw_id):
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: check has invalid id {raw_id!r} "
            "(must be alphanumeric with internal hyphens)"
        )

    applies_to = _build_applies_to(entry.get("applicability"), yaml_path, raw_id)

    return KnowledgeRecord(
        id=f"{CONFIGURATION_CHECK_NAMESPACE}.{raw_id.lower()}",
        kind=KnowledgeKind.DIAGNOSTIC_PROBE,
        name=name,
        description=description,
        applies_to=applies_to,
        provides=(),
        risk=KnowledgeRisk.READ_ONLY,
        execution_ref=f"{CONFIGURATION_CHECK_NAMESPACE}:{raw_id}",
        source_ref=f"{relative_path}#{raw_id}",
        source_hash=source_hash,
    )


def _build_applies_to(applicability: object, yaml_path: Path, raw_id: str) -> AppliesTo:
    """
    Map a raw ``applicability`` block to normalized :class:`AppliesTo`.

    :param applicability: The raw ``applicability`` value from the check, or
        ``None`` if absent.
    :type applicability: object
    :param yaml_path: Path to the source YAML file, used in error messages.
    :type yaml_path: pathlib.Path
    :param raw_id: Raw source check id, used in error messages.
    :type raw_id: str
    :returns: The normalized applicability filters.
    :rtype: AppliesTo
    :raises ConfigurationCheckExtractionError: If ``applicability`` is
        present but not a mapping.
    """
    if applicability is None:
        return AppliesTo()
    if not isinstance(applicability, dict):
        raise ConfigurationCheckExtractionError(
            f"{yaml_path}: 'applicability' for check {raw_id!r} must be a mapping"
        )

    return AppliesTo(
        component=tuple(
            _map_enum_values(
                applicability.get("database_type"),
                COMPONENT_BY_RAW_DATABASE_TYPE,
                "database_type",
                yaml_path,
                raw_id,
            )
        ),
        os_family=tuple(
            _map_enum_values(
                applicability.get("os_type"),
                OS_FAMILY_BY_RAW_OS_TYPE,
                "os_type",
                yaml_path,
                raw_id,
            )
        ),
        topology=tuple(_map_topology(applicability.get("high_availability"), yaml_path, raw_id)),
    )


def _map_enum_values(
    value: object,
    mapping: Dict[str, str],
    field_name: str,
    yaml_path: Path,
    raw_id: str,
) -> List[str]:
    """
    Map a raw applicability value (scalar or list) through an explicit lookup table.

    :param value: The raw applicability value, ``None``, a single raw
        string, or a list of raw strings.
    :type value: object
    :param mapping: Explicit raw-value to normalized-value lookup table.
    :type mapping: Dict[str, str]
    :param field_name: Name of the applicability field, used in error
        messages.
    :type field_name: str
    :param yaml_path: Path to the source YAML file, used in error messages.
    :type yaml_path: pathlib.Path
    :param raw_id: Raw source check id, used in error messages.
    :type raw_id: str
    :returns: Sorted, deduplicated normalized values.
    :rtype: List[str]
    :raises ConfigurationCheckExtractionError: If a value is not a raw
        string present in ``mapping``.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    normalized_values = set()
    for item in items:
        if not isinstance(item, str) or item not in mapping:
            raise ConfigurationCheckExtractionError(
                f"{yaml_path}: unsupported applicability.{field_name} value {item!r} "
                f"for check {raw_id!r}"
            )
        normalized_values.add(mapping[item])
    return sorted(normalized_values)


def _map_topology(value: object, yaml_path: Path, raw_id: str) -> List[str]:
    """
    Map a raw ``applicability.high_availability`` value to topology names.

    :param value: The raw ``applicability.high_availability`` value.
    :type value: object
    :param yaml_path: Path to the source YAML file, used in error messages.
    :type yaml_path: pathlib.Path
    :param raw_id: Raw source check id, used in error messages.
    :type raw_id: str
    :returns: Sorted, deduplicated normalized topology values.
    :rtype: List[str]
    :raises ConfigurationCheckExtractionError: If a value is not a
        recognized topology name.
    """
    if value is None or isinstance(value, bool):
        return []
    return _map_enum_values(
        value, TOPOLOGY_BY_RAW_HIGH_AVAILABILITY, "high_availability", yaml_path, raw_id
    )


def _relative_source_path(yaml_path: Path, repo_root: Path) -> str:
    """
    Compute a stable, forward-slashed path for use in ``source_ref``.

    :param yaml_path: Absolute path to the source YAML file.
    :type yaml_path: pathlib.Path
    :param repo_root: Root the returned path is made relative to.
    :type repo_root: pathlib.Path
    :returns: The path of ``yaml_path`` relative to ``repo_root``, using
        forward slashes.
    :rtype: str
    """
    resolved_yaml_path = yaml_path.resolve()
    resolved_repo_root = repo_root.resolve()
    try:
        relative = resolved_yaml_path.relative_to(resolved_repo_root)
    except ValueError:
        relative = Path(os.path.relpath(resolved_yaml_path, resolved_repo_root))
    return relative.as_posix()
