#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Convert HA cluster constants YAML to JSONL seed rules.

Reads the Pacemaker cluster configuration constants from:

- ``src/roles/ha_db_hana/tasks/files/constants.yaml``
- ``src/roles/ha_scs/tasks/files/constants.yaml``

These YAML files define expected values for CRM config properties,
operation/resource defaults, constraints, resource-specific attributes
and operation timeouts, OS parameters, and Azure LB settings.

Each leaf value node becomes a knowledge Rule that the triage engine
can evaluate against a live cluster's CIB XML.

Usage::

    python scripts/constants_to_jsonl.py [--output-dir DIR]

Phase 1 artifact — see STAF.md Section 7.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")


# ── Constants ──────────────────────────────────────────────────────

_STORAGE_TYPES = {"ANF", "AFS"}

_SECTION_SOURCE_MAP = {
    "CRM_CONFIG_DEFAULTS": "crm_config",
    "OP_DEFAULTS": "op_defaults",
    "RSC_DEFAULTS": "rsc_defaults",
    "CONSTRAINTS": "constraints",
    "AZURE_LOADBALANCER": "azure_lb",
}

_VARIANT_APPLICABILITY: dict[str, dict] = {
    "REDHAT": {"os_family": ["REDHAT"]},
    "SUSE": {"os_family": ["SUSE"]},
    "AFA": {},
    "ISCSI": {},
    "ASD": {},
    "angi_scale_out_hsr": {
        "hana_topology": ["scale_out_hsr"],
        "hsr_provider": ["SAPHanaSR-angi"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parents[1]

_DB_CONSTANTS = (
    _REPO_ROOT / "src" / "roles" / "ha_db_hana" / "tasks" / "files" / "constants.yaml"
)
_SCS_CONSTANTS = (
    _REPO_ROOT / "src" / "roles" / "ha_scs" / "tasks" / "files" / "constants.yaml"
)


# ── Generic tree walker ───────────────────────────────────────────

def _walk_and_emit(
    data,
    path_parts: list[str],
    rules: list[dict],
    counter: list[int],
    *,
    id_prefix: str,
    section: str,
    source: str,
    applicability: dict,
    tags: list[str],
) -> None:
    """Recursively walk a YAML dict, emitting a Rule at each value leaf."""
    if not isinstance(data, dict):
        return

    if "value" in data:
        counter[0] += 1
        param = ".".join(path_parts)
        rules.append({
            "id": f"{id_prefix}-{counter[0]:04d}",
            "name": param,
            "description": f"{section}: {param}",
            "category": "ha_cluster",
            "severity": "HIGH" if data.get("required") else "MEDIUM",
            "applicability": _clean_applicability(applicability),
            "validator": {
                "type": "exact_match",
                "source": source,
                "parameter": param,
                "expected": data["value"],
            },
            "tags": list(tags),
        })
        return

    # Storage-specific branch (ANF/AFS children with value key).
    storage_children = {
        k
        for k in data
        if k in _STORAGE_TYPES
        and isinstance(data.get(k), dict)
        and "value" in data[k]
    }
    if storage_children:
        counter[0] += 1
        param = ".".join(path_parts)
        expected_by_storage = {
            st: data[st]["value"] for st in sorted(storage_children)
        }
        required = any(data[st].get("required") for st in storage_children)
        rules.append({
            "id": f"{id_prefix}-{counter[0]:04d}",
            "name": param,
            "description": f"{section}: {param} (storage-dependent)",
            "category": "ha_cluster",
            "severity": "HIGH" if required else "MEDIUM",
            "applicability": _clean_applicability(applicability),
            "validator": {
                "type": "exact_match",
                "source": source,
                "parameter": param,
                "expected_by_storage": expected_by_storage,
            },
            "tags": list(tags),
        })
        for key, child in data.items():
            if key not in storage_children and key != "required":
                _walk_and_emit(
                    child, path_parts + [key], rules, counter,
                    id_prefix=id_prefix, section=section, source=source,
                    applicability=applicability, tags=tags,
                )
        return

    # Regular container — recurse into children.
    for key, child in data.items():
        if key == "required":
            continue
        _walk_and_emit(
            child, path_parts + [key], rules, counter,
            id_prefix=id_prefix, section=section, source=source,
            applicability=applicability, tags=tags,
        )


def _clean_applicability(appl: dict) -> dict:
    """Remove None values from applicability dict."""
    return {k: v for k, v in appl.items() if v is not None}


# ── Section processors ────────────────────────────────────────────

def _base_applicability(cluster_type: str) -> dict:
    """Build base applicability for a cluster type."""
    appl: dict = {"instance_type": "db" if cluster_type == "db" else "ascs"}
    if cluster_type == "db":
        appl["database_type"] = "HANA"
    return appl


def _process_flat_section(
    data: dict,
    rules: list[dict],
    counter: list[int],
    id_prefix: str,
    cluster_type: str,
    section_name: str,
    source: str,
) -> None:
    """Process flat sections (CRM_CONFIG_DEFAULTS, OP_DEFAULTS, etc.)."""
    _walk_and_emit(
        data,
        path_parts=[],
        rules=rules,
        counter=counter,
        id_prefix=id_prefix,
        section=section_name,
        source=source,
        applicability=_base_applicability(cluster_type),
        tags=["ha_cluster", cluster_type, section_name.lower()],
    )


def _process_valid_configs(
    data: dict,
    rules: list[dict],
    counter: list[int],
    id_prefix: str,
    cluster_type: str,
) -> None:
    """Process VALID_CONFIGS section (OS/variant → property overrides)."""
    for variant, props in data.items():
        if not isinstance(props, dict) or not props:
            continue
        extra = _VARIANT_APPLICABILITY.get(variant, {})
        applicability = {**_base_applicability(cluster_type), **extra}
        _walk_and_emit(
            props,
            path_parts=[],
            rules=rules,
            counter=counter,
            id_prefix=id_prefix,
            section=f"VALID_CONFIGS.{variant}",
            source="crm_config",
            applicability=applicability,
            tags=["ha_cluster", cluster_type, "valid_config", variant.lower()],
        )


def _process_resource_defaults(
    data: dict,
    rules: list[dict],
    counter: list[int],
    id_prefix: str,
    cluster_type: str,
) -> None:
    """Process RESOURCE_DEFAULTS section (OS → resource → attrs)."""
    for os_family, resources in data.items():
        if not isinstance(resources, dict):
            continue
        for resource_name, resource_data in resources.items():
            if not isinstance(resource_data, dict):
                continue

            applicability = {
                **_base_applicability(cluster_type),
                "os_family": [os_family],
            }
            rsc_tags = [
                "ha_cluster", cluster_type, "resource",
                resource_name, os_family.lower(),
            ]

            # Resource-level required → presence rule.
            if resource_data.get("required") is True:
                counter[0] += 1
                rules.append({
                    "id": f"{id_prefix}-{counter[0]:04d}",
                    "name": f"{resource_name}.present",
                    "description": (
                        f"Pacemaker resource '{resource_name}' "
                        f"must be configured ({os_family})"
                    ),
                    "category": "ha_cluster",
                    "severity": "HIGH",
                    "applicability": _clean_applicability(applicability),
                    "validator": {
                        "type": "presence",
                        "source": "cib_resource",
                        "parameter": resource_name,
                    },
                    "tags": rsc_tags,
                })

            # Walk attribute groups.
            for group in (
                "instance_attributes",
                "meta_attributes",
                "operations",
            ):
                group_data = resource_data.get(group)
                if not isinstance(group_data, dict):
                    continue
                _walk_and_emit(
                    group_data,
                    path_parts=[resource_name, group],
                    rules=rules,
                    counter=counter,
                    id_prefix=id_prefix,
                    section=f"RESOURCE_DEFAULTS.{os_family}.{resource_name}",
                    source="cib_resource",
                    applicability=applicability,
                    tags=rsc_tags,
                )


def _process_os_parameters(
    data: dict,
    rules: list[dict],
    counter: list[int],
    id_prefix: str,
    cluster_type: str,
) -> None:
    """Process OS_PARAMETERS section (source → parameter → value)."""
    for _defaults_key, sources in data.items():
        if not isinstance(sources, dict):
            continue
        for source_name, params in sources.items():
            if not isinstance(params, dict):
                continue
            _walk_and_emit(
                params,
                path_parts=[],
                rules=rules,
                counter=counter,
                id_prefix=id_prefix,
                section=f"OS_PARAMETERS.{source_name}",
                source=source_name,
                applicability=_base_applicability(cluster_type),
                tags=[
                    "ha_cluster", cluster_type, "os_parameter", source_name,
                ],
            )


def _process_global_ini(
    data: dict,
    rules: list[dict],
    counter: list[int],
    id_prefix: str,
    cluster_type: str,
) -> None:
    """Process GLOBAL_INI section (OS → ini section → param)."""
    for os_family, sections in data.items():
        if not isinstance(sections, dict):
            continue
        applicability = {
            **_base_applicability(cluster_type),
            "os_family": [os_family],
        }
        _walk_and_emit(
            sections,
            path_parts=[],
            rules=rules,
            counter=counter,
            id_prefix=id_prefix,
            section=f"GLOBAL_INI.{os_family}",
            source="global_ini",
            applicability=applicability,
            tags=[
                "ha_cluster", cluster_type, "global_ini", os_family.lower(),
            ],
        )


# ── Main conversion logic ────────────────────────────────────────

def convert_constants_file(
    yaml_path: Path,
    cluster_type: str,
) -> list[dict]:
    """Convert a constants YAML file to a list of rule dicts.

    :param yaml_path: Path to the constants.yaml file.
    :param cluster_type: ``"db"`` or ``"scs"``.
    :returns: List of rule dicts ready for JSONL serialization.
    """
    data = yaml.safe_load(yaml_path.read_text())
    rules: list[dict] = []
    counter = [0]
    id_prefix = "HA-DB" if cluster_type == "db" else "HA-SCS"

    for section_name, section_data in data.items():
        if not isinstance(section_data, dict):
            continue

        if section_name == "RESOURCE_DEFAULTS":
            _process_resource_defaults(
                section_data, rules, counter, id_prefix, cluster_type,
            )
        elif section_name == "VALID_CONFIGS":
            _process_valid_configs(
                section_data, rules, counter, id_prefix, cluster_type,
            )
        elif section_name == "OS_PARAMETERS":
            _process_os_parameters(
                section_data, rules, counter, id_prefix, cluster_type,
            )
        elif section_name == "GLOBAL_INI":
            _process_global_ini(
                section_data, rules, counter, id_prefix, cluster_type,
            )
        elif section_name in _SECTION_SOURCE_MAP:
            _process_flat_section(
                section_data, rules, counter, id_prefix, cluster_type,
                section_name, _SECTION_SOURCE_MAP[section_name],
            )
        # Unknown sections are silently skipped.

    return rules


def _write_jsonl(rules: list[dict], output_path: Path) -> int:
    """Write rules to a JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        for rule in rules:
            fh.write(json.dumps(rule, ensure_ascii=False) + "\n")
    return len(rules)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert HA cluster constants YAML to JSONL rules.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO_ROOT / "src" / "core" / "knowledge" / "seed" / "rules",
        help="Directory to write the JSONL files.",
    )
    args = parser.parse_args()

    total = 0

    if _DB_CONSTANTS.exists():
        db_rules = convert_constants_file(_DB_CONSTANTS, "db")
        n = _write_jsonl(db_rules, args.output_dir / "ha_db_cluster.jsonl")
        total += n
        print(f"DB constants: {n} rules → {args.output_dir / 'ha_db_cluster.jsonl'}")
    else:
        print(f"WARNING: DB constants not found at {_DB_CONSTANTS}", file=sys.stderr)

    if _SCS_CONSTANTS.exists():
        scs_rules = convert_constants_file(_SCS_CONSTANTS, "scs")
        n = _write_jsonl(scs_rules, args.output_dir / "ha_scs_cluster.jsonl")
        total += n
        print(f"SCS constants: {n} rules → {args.output_dir / 'ha_scs_cluster.jsonl'}")
    else:
        print(f"WARNING: SCS constants not found at {_SCS_CONSTANTS}", file=sys.stderr)

    print(f"Total: {total} rules written.")


if __name__ == "__main__":
    main()
