# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for normalizers — NormalizedData, each normalizer, and the registry."""

import pytest

from src.core.analyzer.normalizers import (
    CibSectionNormalizer,
    CibXmlNormalizer,
    CIB_SOURCES,
    KeyValueNormalizer,
    LogNormalizer,
    Normalizer,
    NormalizedData,
    NormalizerRegistry,
    SysctlNormalizer,
)
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _artifact(content: str, source: str = "") -> EvidenceArtifact:
    """Create a minimal evidence artifact for testing."""
    return EvidenceArtifact(
        evidence_id=f"evi-{source or 'test'}",
        evidence_type=EvidenceType.COMMAND_OUTPUT,
        collector_type=CollectorType.SSH,
        status=CollectionStatus.SUCCESS,
        host="node01",
        command="test-cmd",
        content=content,
        metadata={"source": source} if source else {},
    )


def _cib_artifact(xml: str) -> EvidenceArtifact:
    """Create a CIB XML artifact."""
    return EvidenceArtifact(
        evidence_id="evi-cib",
        evidence_type=EvidenceType.CIB_XML,
        collector_type=CollectorType.SSH,
        status=CollectionStatus.SUCCESS,
        host="node01",
        command="cibadmin --query",
        content=xml,
    )


# ---------------------------------------------------------------------------
# NormalizedData
# ---------------------------------------------------------------------------


class TestNormalizedData:
    """Tests for the NormalizedData dataclass."""

    def test_get_existing_key(self) -> None:
        data = NormalizedData(source="sysctl", values={"a": "1"})
        assert data.get("a") == "1"

    def test_get_missing_key_returns_none(self) -> None:
        data = NormalizedData(source="sysctl", values={"a": "1"})
        assert data.get("b") is None

    def test_has_existing_key(self) -> None:
        data = NormalizedData(source="s", values={"x": "y"})
        assert data.has("x") is True

    def test_has_missing_key(self) -> None:
        data = NormalizedData(source="s", values={})
        assert data.has("z") is False

    def test_empty_values(self) -> None:
        data = NormalizedData(source="s")
        assert data.values == {}
        assert data.get("anything") is None
        assert data.has("anything") is False

    def test_evidence_id_and_host(self) -> None:
        data = NormalizedData(source="sysctl", evidence_id="evi-1", host="node01")
        assert data.evidence_id == "evi-1"
        assert data.host == "node01"


# ---------------------------------------------------------------------------
# SysctlNormalizer
# ---------------------------------------------------------------------------


class TestSysctlNormalizer:
    """Tests for SysctlNormalizer."""

    def test_basic_parsing(self) -> None:
        content = "net.ipv4.tcp_keepalive_time = 300\nvm.swappiness = 10\n"
        result = SysctlNormalizer().normalize(_artifact(content))
        assert result.source == "sysctl"
        assert result.get("net.ipv4.tcp_keepalive_time") == "300"
        assert result.get("vm.swappiness") == "10"

    def test_empty_content(self) -> None:
        result = SysctlNormalizer().normalize(_artifact(""))
        assert result.values == {}

    def test_blank_lines_skipped(self) -> None:
        content = "\n  \nkey = val\n\n"
        result = SysctlNormalizer().normalize(_artifact(content))
        assert len(result.values) == 1
        assert result.get("key") == "val"

    def test_lines_without_equals_skipped(self) -> None:
        content = "this line has no separator\nk = v\n"
        result = SysctlNormalizer().normalize(_artifact(content))
        assert len(result.values) == 1

    def test_whitespace_trimming(self) -> None:
        content = "  key_a  =  value_a  \n"
        result = SysctlNormalizer().normalize(_artifact(content))
        assert result.get("key_a") == "value_a"

    def test_value_with_equals(self) -> None:
        content = "key = val=ue\n"
        result = SysctlNormalizer().normalize(_artifact(content))
        assert result.get("key") == "val=ue"

    def test_evidence_metadata_propagated(self) -> None:
        art = _artifact("k = v", source="sysctl")
        result = SysctlNormalizer().normalize(art)
        assert result.evidence_id == art.evidence_id
        assert result.host == art.host

    def test_protocol_compliance(self) -> None:
        assert isinstance(SysctlNormalizer(), Normalizer)


# ---------------------------------------------------------------------------
# CibXmlNormalizer
# ---------------------------------------------------------------------------


MINIMAL_CIB = """\
<cib>
  <configuration>
    <crm_config>
      <cluster_property_set id="cib-bootstrap-options">
        <nvpair id="stonith-enabled" name="stonith-enabled" value="true"/>
        <nvpair id="stonith-timeout" name="stonith-timeout" value="150"/>
      </cluster_property_set>
    </crm_config>
    <rsc_defaults>
      <meta_attributes id="rsc-options">
        <nvpair id="resource-stickiness" name="resource-stickiness" value="1000"/>
      </meta_attributes>
    </rsc_defaults>
    <op_defaults>
      <meta_attributes id="op-options">
        <nvpair id="timeout" name="timeout" value="600"/>
      </meta_attributes>
    </op_defaults>
    <resources>
      <primitive id="rsc_SAPHana" class="ocf" type="SAPHana">
        <instance_attributes id="rsc_SAPHana-instance">
          <nvpair id="SID" name="SID" value="HDB"/>
          <nvpair id="InstanceNumber" name="InstanceNumber" value="00"/>
        </instance_attributes>
      </primitive>
    </resources>
    <constraints>
      <rsc_location id="loc1" rsc="rsc_SAPHana" score="100" node="node01"/>
      <rsc_colocation id="col1" rsc="rsc_ip" with-rsc="rsc_SAPHana" score="INFINITY"/>
    </constraints>
  </configuration>
</cib>"""


class TestCibXmlNormalizer:
    """Tests for CibXmlNormalizer."""

    def test_cluster_properties(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("crm_config.stonith-enabled") == "true"
        assert result.get("crm_config.stonith-timeout") == "150"

    def test_rsc_defaults(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("rsc_defaults.resource-stickiness") == "1000"

    def test_op_defaults(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("op_defaults.timeout") == "600"

    def test_primitive_resources(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("resource.rsc_SAPHana.class") == "ocf"
        assert result.get("resource.rsc_SAPHana.type") == "SAPHana"
        assert result.get("resource.rsc_SAPHana.SID") == "HDB"
        assert result.get("resource.rsc_SAPHana.InstanceNumber") == "00"

    def test_constraints(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("constraint.loc1.type") == "rsc_location"
        assert result.get("constraint.loc1.rsc") == "rsc_SAPHana"
        assert result.get("constraint.loc1.score") == "100"
        assert result.get("constraint.col1.type") == "rsc_colocation"
        assert result.get("constraint.col1.with-rsc") == "rsc_SAPHana"

    def test_empty_content(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(""))
        assert result.values == {}
        assert result.source == "cib_xml"

    def test_invalid_xml(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact("<not>xml"))
        assert result.values == {}

    def test_malformed_xml(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact("NOT XML AT ALL"))
        assert result.values == {}

    def test_cib_with_no_properties(self) -> None:
        xml = "<cib><configuration></configuration></cib>"
        result = CibXmlNormalizer().normalize(_cib_artifact(xml))
        assert result.values == {}

    def test_source_is_cib_xml(self) -> None:
        result = CibXmlNormalizer().normalize(_cib_artifact(MINIMAL_CIB))
        assert result.source == "cib_xml"

    def test_protocol_compliance(self) -> None:
        assert isinstance(CibXmlNormalizer(), Normalizer)


# ---------------------------------------------------------------------------
# KeyValueNormalizer
# ---------------------------------------------------------------------------


class TestKeyValueNormalizer:
    """Tests for KeyValueNormalizer."""

    def test_equals_separator(self) -> None:
        content = "key1 = val1\nkey2 = val2\n"
        result = KeyValueNormalizer("test", "=").normalize(_artifact(content))
        assert result.get("key1") == "val1"
        assert result.get("key2") == "val2"
        assert result.source == "test"

    def test_colon_separator(self) -> None:
        content = "host: node01\nport: 8080\n"
        result = KeyValueNormalizer("cfg", ":").normalize(_artifact(content))
        assert result.get("host") == "node01"
        assert result.get("port") == "8080"

    def test_empty_content(self) -> None:
        result = KeyValueNormalizer("x").normalize(_artifact(""))
        assert result.values == {}

    def test_lines_without_separator_skipped(self) -> None:
        content = "no-sep-line\nk = v\n"
        result = KeyValueNormalizer("x", "=").normalize(_artifact(content))
        assert len(result.values) == 1

    def test_value_with_separator(self) -> None:
        content = "k = v=alue\n"
        result = KeyValueNormalizer("x", "=").normalize(_artifact(content))
        assert result.get("k") == "v=alue"

    def test_custom_source_name(self) -> None:
        result = KeyValueNormalizer("corosync-cmapctl").normalize(_artifact("a = b"))
        assert result.source == "corosync-cmapctl"

    def test_protocol_compliance(self) -> None:
        assert isinstance(KeyValueNormalizer(), Normalizer)


# ---------------------------------------------------------------------------
# LogNormalizer
# ---------------------------------------------------------------------------


class TestLogNormalizer:
    """Tests for LogNormalizer."""

    def test_basic_parsing(self) -> None:
        content = "line one\nline two\nline three\n"
        result = LogNormalizer().normalize(_artifact(content))
        assert result.get("line_count") == 3
        lines = result.get("lines")
        assert lines == ["line one", "line two", "line three"]

    def test_empty_content(self) -> None:
        result = LogNormalizer().normalize(_artifact(""))
        assert result.get("line_count") == 0
        assert result.get("lines") == []

    def test_blank_lines_skipped(self) -> None:
        content = "\n  \nreal line\n  \n"
        result = LogNormalizer().normalize(_artifact(content))
        assert result.get("line_count") == 1

    def test_raw_preserved(self) -> None:
        content = "hello world"
        result = LogNormalizer().normalize(_artifact(content))
        assert result.get("raw") == content

    def test_source_is_log(self) -> None:
        result = LogNormalizer().normalize(_artifact("x"))
        assert result.source == "log"

    def test_extract_pattern_basic(self) -> None:
        content = "INFO started\nERROR disk full\nINFO done\n"
        matches = LogNormalizer().extract_pattern(_artifact(content), r"ERROR")
        assert len(matches) == 1
        assert "disk full" in matches[0]

    def test_extract_pattern_no_match(self) -> None:
        matches = LogNormalizer().extract_pattern(_artifact("hello"), r"FATAL")
        assert matches == []

    def test_extract_pattern_case_insensitive(self) -> None:
        matches = LogNormalizer().extract_pattern(_artifact("Error: timeout"), r"error")
        assert len(matches) == 1

    def test_protocol_compliance(self) -> None:
        assert isinstance(LogNormalizer(), Normalizer)


# ---------------------------------------------------------------------------
# NormalizerRegistry
# ---------------------------------------------------------------------------


class TestNormalizerRegistry:
    """Tests for NormalizerRegistry."""

    def test_register_and_get(self) -> None:
        reg = NormalizerRegistry()
        n = SysctlNormalizer()
        reg.register("sysctl", n)
        assert reg.get("sysctl") is n

    def test_get_unregistered_returns_none(self) -> None:
        reg = NormalizerRegistry()
        assert reg.get("unknown") is None

    def test_sources_property(self) -> None:
        reg = NormalizerRegistry()
        reg.register("a", SysctlNormalizer())
        reg.register("b", LogNormalizer())
        assert sorted(reg.sources) == ["a", "b"]

    def test_default_has_all_seed_sources(self) -> None:
        reg = NormalizerRegistry.default()
        expected_sources = {
            "sysctl",
            "crm_config",
            "op_defaults",
            "rsc_defaults",
            "constraints",
            "cib_resource",
            "corosync-cmapctl",
            "global_ini",
            "command",
            "azure_lb",
        }
        assert set(reg.sources) == expected_sources

    def test_default_sysctl_normalizer_type(self) -> None:
        reg = NormalizerRegistry.default()
        assert isinstance(reg.get("sysctl"), SysctlNormalizer)

    def test_default_cib_sources_are_section_normalizers(self) -> None:
        reg = NormalizerRegistry.default()
        cib_sources = [
            "crm_config",
            "op_defaults",
            "rsc_defaults",
            "constraints",
            "cib_resource",
        ]
        for src in cib_sources:
            normalizer = reg.get(src)
            assert isinstance(normalizer, CibSectionNormalizer)
            assert normalizer.section == src

    def test_default_cib_sources_form_group(self) -> None:
        reg = NormalizerRegistry.default()
        peers = reg.get_peer_sources("crm_config")
        assert peers == CIB_SOURCES

    def test_default_kv_sources_are_kv_normalizers(self) -> None:
        reg = NormalizerRegistry.default()
        for source in ("corosync-cmapctl", "global_ini", "command", "azure_lb"):
            assert isinstance(reg.get(source), KeyValueNormalizer)

    def test_register_overwrites(self) -> None:
        reg = NormalizerRegistry()
        n1 = SysctlNormalizer()
        n2 = SysctlNormalizer()
        reg.register("s", n1)
        reg.register("s", n2)
        assert reg.get("s") is n2

    def test_get_peer_sources_empty_for_ungrouped(self) -> None:
        reg = NormalizerRegistry()
        reg.register("sysctl", SysctlNormalizer())
        assert reg.get_peer_sources("sysctl") == frozenset()

    def test_register_group_creates_peers(self) -> None:
        reg = NormalizerRegistry()
        normalizers = {"a": SysctlNormalizer(), "b": SysctlNormalizer()}
        reg.register_group(["a", "b"], normalizers)
        assert reg.get_peer_sources("a") == frozenset({"a", "b"})
        assert reg.get_peer_sources("b") == frozenset({"a", "b"})


# ---------------------------------------------------------------------------
# CibSectionNormalizer
# ---------------------------------------------------------------------------


class TestCibSectionNormalizer:
    """Tests for CibSectionNormalizer — strips CIB key prefixes."""

    def test_crm_config_section(self) -> None:
        result = CibSectionNormalizer("crm_config").normalize(_cib_artifact(MINIMAL_CIB))
        assert result.source == "crm_config"
        assert result.get("stonith-enabled") == "true"
        assert result.get("stonith-timeout") == "150"

    def test_rsc_defaults_section(self) -> None:
        result = CibSectionNormalizer("rsc_defaults").normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("resource-stickiness") == "1000"

    def test_op_defaults_section(self) -> None:
        result = CibSectionNormalizer("op_defaults").normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("timeout") == "600"

    def test_cib_resource_section(self) -> None:
        result = CibSectionNormalizer("cib_resource").normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("rsc_SAPHana.class") == "ocf"
        assert result.get("rsc_SAPHana.type") == "SAPHana"
        assert result.get("rsc_SAPHana.SID") == "HDB"

    def test_constraints_section(self) -> None:
        result = CibSectionNormalizer("constraints").normalize(_cib_artifact(MINIMAL_CIB))
        assert result.get("loc1.type") == "rsc_location"
        assert result.get("loc1.rsc") == "rsc_SAPHana"

    def test_empty_xml(self) -> None:
        result = CibSectionNormalizer("crm_config").normalize(_cib_artifact(""))
        assert result.values == {}

    def test_unknown_section_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown CIB section"):
            CibSectionNormalizer("bogus")

    def test_no_keys_for_wrong_section(self) -> None:
        """CIB with only crm_config should produce empty rsc_defaults."""
        xml = """<cib>
          <configuration>
            <crm_config>
              <cluster_property_set id="cps">
                <nvpair id="x" name="stonith-enabled" value="true"/>
              </cluster_property_set>
            </crm_config>
          </configuration>
        </cib>"""
        result = CibSectionNormalizer("rsc_defaults").normalize(_cib_artifact(xml))
        assert result.values == {}

    def test_protocol_compliance(self) -> None:
        assert isinstance(CibSectionNormalizer("crm_config"), Normalizer)
