#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Convert existing YAML configuration-check rules to JSONL format.

Reads the Ansible-style YAML rule files under
``src/roles/configuration_checks/tasks/files/*.yml``, resolves YAML anchors,
maps fields to the ``Rule`` Pydantic model schema, and writes one JSONL file
per source domain (hana.jsonl, db2.jsonl, etc.) into the seed directory.

Usage::

    python scripts/yaml_to_jsonl.py [--input-dir DIR] [--output-dir DIR]

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


# ── Field mapping from YAML rule schema → Rule JSONL schema ──────

# YAML validator_type → Rule.ValidatorSpec.type  (Section 7 enum values)
_VALIDATOR_MAP: dict[str, str] = {
    "string": "exact_match",
    "list": "exact_match",
    "range": "range",
    "check_support": "custom",
}

# YAML applicability keys → Applicability model fields
_APPLICABILITY_MAP: dict[str, str] = {
    "os_type": "os_family",
    "database_type": "database_type",
    "storage_type": "storage_type",
    "role": "instance_type",
    "high_availability": "hana_topology",
    "high_availability_agent": "hsr_provider",
    "hardware_type": "hardware_type",
    "os_version": "os_version",
}

# Keys dropped from the YAML (not part of the Rule model)
_DROPPED_KEYS = {"workload", "report", "collector_args", "collector_type"}


def _build_applicability(yaml_app: dict) -> dict:
    """Convert YAML applicability block to Applicability model fields.

    The Applicability model uses single strings for database_type,
    storage_type, scs_type, instance_type but lists for os_family,
    hana_topology, hsr_provider. YAML data may have lists for all.

    :param yaml_app: Raw applicability dict from YAML.
    :returns: Dict matching the Applicability dataclass fields.
    """
    result: dict = {}

    # Fields that are lists of strings in the Applicability model
    list_fields = {"os_family", "hana_topology", "hsr_provider"}

    for yaml_key, model_key in _APPLICABILITY_MAP.items():
        if yaml_key not in yaml_app:
            continue
        val = yaml_app[yaml_key]

        # Skip booleans (e.g. high_availability: true) — not a valid
        # topology string or list
        if isinstance(val, bool):
            continue

        if model_key in list_fields:
            # Normalise scalars to list, flatten nested lists
            if isinstance(val, str):
                val = [val]
            elif isinstance(val, list):
                flat: list[str] = []
                for item in val:
                    if isinstance(item, list):
                        flat.extend(str(i) for i in item)
                    else:
                        flat.append(str(item))
                val = flat
            result[model_key] = val
        else:
            # Scalar fields — if YAML has a list, skip "all" values and
            # store None (matches any) when multiple values present
            if isinstance(val, list):
                # Filter out generic "all" values
                filtered = [v for v in val if v not in ("all",)]
                if len(filtered) == 1:
                    result[model_key] = filtered[0]
                # Multiple values → leave as None (matches any system)
            elif val != "all":
                result[model_key] = val

    return result


def _build_validator(check: dict) -> dict | None:
    """Convert YAML validator fields to a ValidatorSpec dict.

    :param check: Full YAML check dict.
    :returns: ValidatorSpec-compatible dict, or None.
    """
    vtype = check.get("validator_type")
    if not vtype or vtype not in _VALIDATOR_MAP:
        return None

    spec: dict = {"type": _VALIDATOR_MAP[vtype]}

    vargs = check.get("validator_args", {})
    if vtype == "string":
        spec["expected"] = vargs.get("expected_output")
    elif vtype == "list":
        spec["expected"] = vargs.get("valid_list")
    elif vtype == "range":
        spec["min_value"] = vargs.get("min")
        spec["max_value"] = vargs.get("max")
    elif vtype == "check_support":
        spec["custom_function"] = "check_support"

    # Source is the command from collector_args
    cargs = check.get("collector_args", {})
    if "command" in cargs:
        spec["source"] = "command"
        spec["parameter"] = check.get("name", "")

    return spec


def _build_references(refs: dict | None) -> list[str]:
    """Convert YAML references dict to list of URL/ID strings.

    Handles both flat values (``{"sap": "1410736"}``) and nested dicts
    (``{"microsoft": {"url": "https://..."}}``) seen in package rules.

    :param refs: Dict like {"sap": "1410736", "microsoft": "https://..."}.
    :returns: List of reference strings.
    """
    if not refs:
        return []
    result: list[str] = []
    for key, val in refs.items():
        if isinstance(val, dict):
            # Nested dict — extract URL if present
            url = val.get("url", "")
            if url:
                result.append(str(url))
        elif key == "sap":
            result.append(f"SAP Note {val}")
        elif key == "microsoft":
            result.append(str(val))
        else:
            result.append(f"{key}: {val}")
    return result


def _build_tags(check: dict, source_file: str) -> list[str]:
    """Generate tags from the check metadata.

    :param check: YAML check dict.
    :param source_file: Source file stem (e.g. "hana").
    :returns: Tag list.
    """
    tags: list[str] = [source_file]
    category = check.get("category", "")
    if category:
        tags.append(category.lower().replace(" ", "_"))
    app = check.get("applicability", {})
    for db_type in app.get("database_type", []):
        if isinstance(db_type, str) and db_type.lower() not in tags:
            tags.append(db_type.lower())
    return tags


def convert_check(check: dict, source_file: str) -> dict:
    """Convert a single YAML check to Rule JSONL dict.

    :param check: Resolved YAML check dict.
    :param source_file: Source file stem for tagging.
    :returns: Rule-compatible dict ready for JSON serialization.
    """
    rule: dict = {
        "id": check["id"],
        "name": check.get("name", ""),
        "description": check.get("description", ""),
        "category": check.get("category", ""),
        "severity": check.get("severity", "MEDIUM"),
    }

    app = check.get("applicability")
    if app:
        rule["applicability"] = _build_applicability(app)

    validator = _build_validator(check)
    if validator:
        rule["validator"] = validator

    rule["references"] = _build_references(check.get("references"))
    rule["tags"] = _build_tags(check, source_file)

    return rule


def convert_file(input_path: Path) -> list[dict]:
    """Convert all checks in a YAML file to Rule dicts.

    :param input_path: Path to YAML file.
    :returns: List of Rule dicts.
    """
    with open(input_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    checks = data.get("checks", [])
    source = input_path.stem
    rules: list[dict] = []
    for check in checks:
        rules.append(convert_check(check, source))
    return rules


def main() -> None:
    """Entry point: convert YAML rule files to JSONL seed data."""
    parser = argparse.ArgumentParser(
        description="Convert YAML configuration check rules to JSONL format."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("src/roles/configuration_checks/tasks/files"),
        help="Directory containing YAML rule files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("src/core/knowledge/seed/rules"),
        help="Output directory for JSONL files.",
    )
    args = parser.parse_args()

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    if not input_dir.is_dir():
        sys.exit(f"Input directory not found: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    yaml_files = sorted(input_dir.glob("*.yml"))
    if not yaml_files:
        sys.exit(f"No YAML files found in {input_dir}")

    total = 0
    for yaml_file in yaml_files:
        rules = convert_file(yaml_file)
        if not rules:
            continue

        out_path = output_dir / f"{yaml_file.stem}.jsonl"
        with open(out_path, "w", encoding="utf-8") as fh:
            for rule in rules:
                fh.write(json.dumps(rule, ensure_ascii=False) + "\n")

        total += len(rules)
        print(f"  {yaml_file.name} → {out_path.name} ({len(rules)} rules)")

    print(f"\nConverted {total} rules from {len(yaml_files)} files → {output_dir}")


if __name__ == "__main__":
    main()
