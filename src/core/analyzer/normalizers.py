# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Normalizers — turn raw evidence artifact content into structured key-value data.

Each normalizer handles one evidence source type (sysctl output, CIB XML,
key=value config, log lines). The ``NormalizerRegistry`` maps source names
to normalizer instances so the analyzer can dispatch automatically.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from src.core.models.evidence import EvidenceArtifact

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NormalizedData — the output of every normalizer
# ---------------------------------------------------------------------------


@dataclass
class NormalizedData:
    """Structured key-value data extracted from raw evidence.

    :param source: Which normalizer produced this data.
    :param values: Parameter name → value mapping.
    :param evidence_id: ID of the source artifact.
    :param host: Host the evidence came from.
    """

    source: str
    values: dict[str, Any] = field(default_factory=dict)
    evidence_id: str = ""
    host: str = ""

    def get(self, parameter: str) -> Optional[Any]:
        """Retrieve a value by parameter name.

        :param parameter: The parameter to look up.
        :returns: The value, or None if not present.
        """
        return self.values.get(parameter)

    def has(self, parameter: str) -> bool:
        """Check whether a parameter exists in the normalized data.

        :param parameter: The parameter to check.
        :returns: True if present.
        """
        return parameter in self.values


# ---------------------------------------------------------------------------
# Normalizer protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Normalizer(Protocol):
    """Protocol for an evidence normalizer.

    Turns raw artifact content into structured ``NormalizedData``.
    """

    def normalize(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Extract structured data from the artifact content.

        :param artifact: The evidence artifact to normalize.
        :returns: Structured key-value data.
        """
        ...


# ---------------------------------------------------------------------------
# SysctlNormalizer — parses `sysctl -a` output
# ---------------------------------------------------------------------------


class SysctlNormalizer:
    """Parses ``sysctl -a`` or ``sysctl <param>`` output.

    Expected format: ``key = value`` per line.
    """

    def normalize(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Parse sysctl key=value output.

        :param artifact: Artifact containing sysctl output.
        :returns: NormalizedData with parameter → value mapping.
        """
        values: dict[str, Any] = {}
        for line in artifact.content.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
        return NormalizedData(
            source="sysctl",
            values=values,
            evidence_id=artifact.evidence_id,
            host=artifact.host,
        )


# ---------------------------------------------------------------------------
# CibXmlNormalizer — parses Pacemaker CIB XML
# ---------------------------------------------------------------------------


class CibXmlNormalizer:
    """Parses Pacemaker CIB XML (``cibadmin --query`` output).

    Extracts cluster properties, resource defaults, operation defaults,
    resources (primitives, clones, groups), and constraints.
    """

    def normalize(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Parse CIB XML into structured data.

        :param artifact: Artifact containing CIB XML.
        :returns: NormalizedData with flattened CIB properties and resources.
        """
        values: dict[str, Any] = {}
        content = artifact.content.strip()
        if not content:
            return self._empty(artifact)

        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            logger.warning("CIB XML parse error: %s", exc)
            return self._empty(artifact)

        self._extract_cluster_properties(root, values)
        self._extract_rsc_defaults(root, values)
        self._extract_op_defaults(root, values)
        self._extract_resources(root, values)
        self._extract_constraints(root, values)

        return NormalizedData(
            source="cib_xml",
            values=values,
            evidence_id=artifact.evidence_id,
            host=artifact.host,
        )

    def _empty(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Return empty NormalizedData for this artifact."""
        return NormalizedData(
            source="cib_xml",
            evidence_id=artifact.evidence_id,
            host=artifact.host,
        )

    def _extract_cluster_properties(self, root: ET.Element, values: dict[str, Any]) -> None:
        """Extract crm_config cluster properties."""
        for nvpair in root.iter("nvpair"):
            parent = self._find_parent(root, nvpair)
            if parent is not None and parent.tag == "cluster_property_set":
                name = nvpair.get("name", "")
                if name:
                    values[f"crm_config.{name}"] = nvpair.get("value", "")

    def _extract_rsc_defaults(self, root: ET.Element, values: dict[str, Any]) -> None:
        """Extract rsc_defaults meta attributes."""
        for rsc_defaults in root.iter("rsc_defaults"):
            for nvpair in rsc_defaults.iter("nvpair"):
                name = nvpair.get("name", "")
                if name:
                    values[f"rsc_defaults.{name}"] = nvpair.get("value", "")

    def _extract_op_defaults(self, root: ET.Element, values: dict[str, Any]) -> None:
        """Extract op_defaults meta attributes."""
        for op_defaults in root.iter("op_defaults"):
            for nvpair in op_defaults.iter("nvpair"):
                name = nvpair.get("name", "")
                if name:
                    values[f"op_defaults.{name}"] = nvpair.get("value", "")

    def _extract_resources(self, root: ET.Element, values: dict[str, Any]) -> None:
        """Extract primitive resources with their attributes."""
        for primitive in root.iter("primitive"):
            rsc_id = primitive.get("id", "")
            rsc_class = primitive.get("class", "")
            rsc_type = primitive.get("type", "")
            if rsc_id:
                values[f"resource.{rsc_id}.class"] = rsc_class
                values[f"resource.{rsc_id}.type"] = rsc_type
                for nvpair in primitive.iter("nvpair"):
                    name = nvpair.get("name", "")
                    if name:
                        values[f"resource.{rsc_id}.{name}"] = nvpair.get("value", "")

    def _extract_constraints(self, root: ET.Element, values: dict[str, Any]) -> None:
        """Extract location and colocation constraints."""
        for tag in ("rsc_location", "rsc_colocation", "rsc_order"):
            for elem in root.iter(tag):
                cid = elem.get("id", "")
                if cid:
                    values[f"constraint.{cid}.type"] = tag
                    for attr_name, attr_val in elem.attrib.items():
                        if attr_name != "id":
                            values[f"constraint.{cid}.{attr_name}"] = attr_val

    def _find_parent(self, root: ET.Element, target: ET.Element) -> Optional[ET.Element]:
        """Find the parent of a target element in the tree."""
        for parent in root.iter():
            if target in parent:
                return parent
        return None


# ---------------------------------------------------------------------------
# CibSectionNormalizer — extracts one CIB section, strips key prefixes
# ---------------------------------------------------------------------------

_CIB_SECTION_PREFIXES: dict[str, str] = {
    "crm_config": "crm_config",
    "op_defaults": "op_defaults",
    "rsc_defaults": "rsc_defaults",
    "constraints": "constraint",
    "cib_resource": "resource",
}

CIB_SOURCES: frozenset[str] = frozenset(_CIB_SECTION_PREFIXES.keys())


class CibSectionNormalizer:
    """Extracts one section from CIB XML and strips key prefixes.

    Wraps ``CibXmlNormalizer`` to produce section-specific
    ``NormalizedData`` where parameter keys match rule definitions
    directly — no prefix needed in the validator.

    :param section: CIB section name (crm_config, cib_resource, etc.).
    """

    def __init__(self, section: str) -> None:
        if section not in _CIB_SECTION_PREFIXES:
            raise ValueError(f"Unknown CIB section: {section}")
        self._section = section
        self._prefix = _CIB_SECTION_PREFIXES[section]
        self._parser = CibXmlNormalizer()

    @property
    def section(self) -> str:
        """The CIB section this normalizer extracts."""
        return self._section

    def normalize(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Parse CIB XML and return only this section's parameters.

        Keys are stripped of their section prefix so they match
        rule parameter names directly.

        :param artifact: Artifact containing CIB XML.
        :returns: Section-specific NormalizedData with unprefixed keys.
        """
        full = self._parser.normalize(artifact)
        prefix_dot = f"{self._prefix}."
        values = {
            key[len(prefix_dot) :]: val
            for key, val in full.values.items()
            if key.startswith(prefix_dot)
        }
        return NormalizedData(
            source=self._section,
            values=values,
            evidence_id=full.evidence_id,
            host=full.host,
        )


# ---------------------------------------------------------------------------
# KeyValueNormalizer — generic key=value or key: value parser
# ---------------------------------------------------------------------------


class KeyValueNormalizer:
    """Parses generic key-value output (corosync-cmapctl, global.ini, etc.).

    Handles both ``key = value`` and ``key: value`` separators.

    :param source_name: Name to tag the normalized data with.
    :param separator: The separator character(s) to split on.
    """

    def __init__(self, source_name: str = "key_value", separator: str = "=") -> None:
        self._source_name = source_name
        self._separator = separator

    def normalize(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Parse key-value lines from artifact content.

        :param artifact: Artifact containing key-value output.
        :returns: NormalizedData with parameter → value mapping.
        """
        values: dict[str, Any] = {}
        for line in artifact.content.splitlines():
            line = line.strip()
            if not line or self._separator not in line:
                continue
            key, _, value = line.partition(self._separator)
            values[key.strip()] = value.strip()
        return NormalizedData(
            source=self._source_name,
            values=values,
            evidence_id=artifact.evidence_id,
            host=artifact.host,
        )


# ---------------------------------------------------------------------------
# LogNormalizer — extracts structured entries from log lines
# ---------------------------------------------------------------------------


class LogNormalizer:
    """Parses log output (e.g., /var/log/messages grep output).

    Extracts log entries and indexes them by line for search.
    Can also extract specific patterns via ``extract_pattern``.
    """

    def normalize(self, artifact: EvidenceArtifact) -> NormalizedData:
        """Parse log lines into indexed entries.

        :param artifact: Artifact containing log output.
        :returns: NormalizedData with ``lines`` list and ``line_count``.
        """
        lines = [line.strip() for line in artifact.content.splitlines() if line.strip()]
        values: dict[str, Any] = {
            "lines": lines,
            "line_count": len(lines),
            "raw": artifact.content,
        }
        return NormalizedData(
            source="log",
            values=values,
            evidence_id=artifact.evidence_id,
            host=artifact.host,
        )

    def extract_pattern(self, artifact: EvidenceArtifact, pattern: str) -> list[str]:
        """Extract lines matching a regex pattern.

        :param artifact: Artifact containing log output.
        :param pattern: Regex to match against each line.
        :returns: Matching lines.
        """
        compiled = re.compile(pattern, re.IGNORECASE)
        return [
            line.strip() for line in artifact.content.splitlines() if compiled.search(line.strip())
        ]


# ---------------------------------------------------------------------------
# NormalizerRegistry — maps source names to normalizer instances
# ---------------------------------------------------------------------------


class NormalizerRegistry:
    """Registry mapping validator source names to normalizer instances.

    Provides a ``default()`` factory with standard mappings for all
    known evidence source types in the seed rules.
    """

    def __init__(self) -> None:
        self._normalizers: dict[str, Normalizer] = {}
        self._groups: dict[str, frozenset[str]] = {}

    def register(self, source: str, normalizer: Normalizer) -> None:
        """Register a normalizer for a given source name.

        :param source: The validator source name (e.g. ``sysctl``).
        :param normalizer: The normalizer instance.
        """
        self._normalizers[source] = normalizer

    def register_group(
        self,
        sources: list[str],
        normalizers: dict[str, Normalizer],
    ) -> None:
        """Register normalizers for a group of related sources.

        Sources in the same group share the same raw evidence.
        When one source is normalized, the analyzer can fan out
        to all peer sources in the group.

        :param sources: List of related source names.
        :param normalizers: Mapping of source name → normalizer.
        """
        group = frozenset(sources)
        for source in sources:
            self._normalizers[source] = normalizers[source]
            self._groups[source] = group

    def get_peer_sources(self, source: str) -> frozenset[str]:
        """Get all sources in the same group as the given source.

        :param source: A source name.
        :returns: All peer source names (including the given source),
                  or an empty set if the source is not in a group.
        """
        return self._groups.get(source, frozenset())

    def get(self, source: str) -> Optional[Normalizer]:
        """Get the normalizer for a given source.

        :param source: The validator source name.
        :returns: The normalizer, or None if not registered.
        """
        return self._normalizers.get(source)

    @property
    def sources(self) -> list[str]:
        """List all registered source names."""
        return list(self._normalizers.keys())

    @classmethod
    def default(cls) -> "NormalizerRegistry":
        """Create a registry with standard normalizers.

        Maps all known validator source types from seed rules:
        ``sysctl``, ``crm_config``, ``op_defaults``, ``rsc_defaults``,
        ``constraints``, ``cib_resource``, ``corosync-cmapctl``,
        ``global_ini``, ``command``, ``azure_lb``.

        :returns: A populated NormalizerRegistry.
        """
        registry = cls()

        registry.register("sysctl", SysctlNormalizer())

        cib_normalizers = {section: CibSectionNormalizer(section) for section in CIB_SOURCES}
        registry.register_group(list(CIB_SOURCES), cib_normalizers)

        registry.register("corosync-cmapctl", KeyValueNormalizer("corosync-cmapctl", "="))
        registry.register("global_ini", KeyValueNormalizer("global_ini", "="))

        registry.register("command", KeyValueNormalizer("command", "="))
        registry.register("azure_lb", KeyValueNormalizer("azure_lb", "="))

        return registry
