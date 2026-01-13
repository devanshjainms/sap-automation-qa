# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Troubleshooting Plugin for SAP QA Framework.

Provides complete troubleshooting capabilities including:
- Autonomous investigation of cluster issues
- Metadata-driven investigation guidance
- Log analysis and correlation
- Configuration validation
- Remediation suggestions

Uses ExecutionPlugin for data collection (commands, logs).
"""

import json
import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Annotated

from semantic_kernel.functions import kernel_function

from src.agents.workspace.workspace_store import WorkspaceStore
from src.module_utils.enums import Check
from src.agents.observability import get_logger

if TYPE_CHECKING:
    from src.agents.plugins.execution import ExecutionPlugin

logger = get_logger(__name__)


class TroubleshootingPlugin:
    """
    Semantic Kernel plugin for SAP HA troubleshooting.

    Provides complete troubleshooting workflows including autonomous investigation,
    metadata-driven guidance, and remediation suggestions.

    High-Level Tools (autonomous operations):
        - investigate_cluster_issue(): Complete investigation with root cause
        - run_health_check(): Proactive diagnostics

    Metadata Functions (guidance):
        - suggest_relevant_checks(): Pattern-based check recommendations
        - get_expected_configuration(): SAP HA best practices
        - list_available_checks(): Available check capabilities

    Requires ExecutionPlugin for data collection (commands, logs).
    """

    def __init__(
        self, workspace_store: WorkspaceStore, execution_plugin: Optional["ExecutionPlugin"] = None
    ):
        """Initialize troubleshooting plugin.

        :param workspace_store: Workspace storage instance
        :type workspace_store: WorkspaceStore
        :param execution_plugin: ExecutionPlugin for running commands/logs
        :type execution_plugin: Optional[ExecutionPlugin]
        """
        self._workspace_store = workspace_store
        self._execution = execution_plugin
        self._check_metadata_cache: Optional[Dict[str, Check]] = None
        self._constants_cache: Dict[str, Dict] = {}
        self._patterns_cache: Optional[Dict] = None
        self._src_root = Path(__file__).parent.parent.parent
        self._checks_dir = self._src_root / "roles" / "configuration_checks" / "tasks" / "files"
        self._patterns_file = self._src_root / "agents" / "config" / "investigation_patterns.yaml"

        logger.info("TroubleshootingPlugin initialized")

    def parse_check_files(self, force_reload: bool = False) -> Dict[str, Check]:
        """Parse Ansible check YAML files to extract metadata.

        Extracts check capabilities from all YAML files in configuration_checks
        directory. Caches results for performance.

        :param force_reload: Force reload from disk instead of using cache
        :type force_reload: bool
        :returns: Dictionary mapping check_id to Check
        :rtype: Dict[str, Check]
        :raises FileNotFoundError: If checks directory doesn't exist
        :raises yaml.YAMLError: If YAML parsing fails
        """
        if self._check_metadata_cache is not None and not force_reload:
            logger.debug(
                f"Returning cached check metadata ({len(self._check_metadata_cache)} checks)"
            )
            return self._check_metadata_cache

        if not self._checks_dir.exists():
            error_msg = f"Checks directory not found: {self._checks_dir}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        capabilities: Dict[str, Check] = {}
        check_files = list(self._checks_dir.glob("*.yml"))

        if not check_files:
            logger.warning(f"No YAML check files found in {self._checks_dir}")
            return capabilities

        logger.info(f"Parsing {len(check_files)} check files from {self._checks_dir}")

        for check_file in check_files:
            try:
                checks = self._parse_single_check_file(check_file, check_file.stem)
                capabilities.update(checks)
                logger.debug(f"Parsed {len(checks)} checks from {check_file.name}")
            except yaml.YAMLError as e:
                logger.error(f"YAML parsing error in {check_file.name}: {e}", exc_info=e)
                continue
            except Exception as e:
                logger.error(f"Error parsing {check_file.name}: {e}", exc_info=e)
                continue

        self._check_metadata_cache = capabilities
        logger.info(f"Successfully parsed {len(capabilities)} check capabilities")
        return capabilities

    def _parse_single_check_file(self, file_path: Path, category: str) -> Dict[str, Check]:
        """Parse a single Ansible check YAML file.

        :param file_path: Path to YAML file
        :type file_path: Path
        :param category: Check category (derived from filename)
        :type category: str
        :returns: Dictionary of Check objects
        :rtype: Dict[str, Check]
        """
        capabilities = {}

        with open(file_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        if not content:
            logger.warning(f"Empty YAML content in {file_path.name}")
            return capabilities
        tasks = content if isinstance(content, list) else [content]

        for idx, task in enumerate(tasks):
            if not isinstance(task, dict):
                continue
            name = task.get("name", f"unnamed_task_{idx}")
            tags = task.get("tags", [])
            module = self._extract_module_name(task)
            primary_tag = tags[0] if tags else category
            check_id = f"{category}.{primary_tag}.{idx}"
            description = name
            if module:
                description += f" (uses {module})"

            capability = Check(
                id=check_id,
                name=name,
                description=description,
                category=category,
                workload="SAP",
                tags=tags if isinstance(tags, list) else [tags],
                collector_type="command",
            )

            capabilities[check_id] = capability

        return capabilities

    def _extract_module_name(self, task: Dict) -> str:
        """Extract Ansible module name from task definition.

        :param task: Ansible task dictionary
        :type task: Dict
        :returns: Module name (e.g., 'command', 'shell', 'assert')
        :rtype: str
        """
        module_keys = [
            "command",
            "shell",
            "assert",
            "debug",
            "fail",
            "set_fact",
            "include_vars",
            "service",
            "systemd",
            "lineinfile",
            "copy",
            "template",
            "file",
            "stat",
            "get_url",
            "uri",
        ]

        for key in module_keys:
            if key in task:
                return key
        for key in task.keys():
            if "." in key and key != "name":
                return key.split(".")[-1]

        return "unknown"

    def parse_constants_yaml(self, ha_type: str, force_reload: bool = False) -> Dict:
        """Parse SAP HA best practice constants YAML file.

        :param ha_type: HA type ('scs' or 'db_hana')
        :type ha_type: str
        :param force_reload: Force reload from disk instead of using cache
        :type force_reload: bool
        :returns: Dictionary of expected configuration values
        :rtype: Dict
        :raises FileNotFoundError: If constants file doesn't exist
        :raises yaml.YAMLError: If YAML parsing fails
        :raises ValueError: If ha_type is invalid
        """
        if ha_type not in ["scs", "db_hana"]:
            raise ValueError(f"Invalid ha_type: {ha_type}. Must be 'scs' or 'db_hana'")

        if ha_type in self._constants_cache and not force_reload:
            logger.debug(f"Returning cached constants for {ha_type}")
            return self._constants_cache[ha_type]
        role_name = f"ha_{ha_type}" if ha_type != "scs" else "ha_scs"
        constants_path = self._src_root / "roles" / role_name / "tasks" / "files" / "constants.yaml"

        if not constants_path.exists():
            error_msg = f"Constants file not found: {constants_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        logger.info(f"Parsing constants from {constants_path}")

        try:
            with open(constants_path, "r", encoding="utf-8") as f:
                constants = yaml.safe_load(f)

            if not constants:
                logger.warning(f"Empty constants file: {constants_path}")
                return {}

            self._constants_cache[ha_type] = constants
            logger.info(f"Successfully parsed {len(constants)} constant sections for {ha_type}")
            return constants

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {constants_path}: {e}", exc_info=e)
            raise
        except Exception as e:
            logger.error(f"Error reading constants file {constants_path}: {e}", exc_info=e)
            raise

    def load_investigation_patterns(self, force_reload: bool = False) -> Dict:
        """Load hints-based investigation patterns from YAML.

        :param force_reload: Force reload from disk instead of using cache
        :type force_reload: bool
        :returns: Dictionary of investigation patterns and hints
        :rtype: Dict
        :raises FileNotFoundError: If patterns file doesn't exist
        :raises yaml.YAMLError: If YAML parsing fails
        """
        if self._patterns_cache is not None and not force_reload:
            logger.debug("Returning cached investigation patterns")
            return self._patterns_cache

        if not self._patterns_file.exists():
            error_msg = f"Investigation patterns file not found: {self._patterns_file}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        logger.info(f"Loading investigation patterns from {self._patterns_file}")

        try:
            with open(self._patterns_file, "r", encoding="utf-8") as f:
                patterns = yaml.safe_load(f)

            if not patterns:
                logger.warning(f"Empty patterns file: {self._patterns_file}")
                return {"investigation_hints": {}, "baseline_checks": {"minimal": []}}
            if "investigation_hints" not in patterns:
                logger.warning("Missing 'investigation_hints' section in patterns file")
                patterns["investigation_hints"] = {}

            if "baseline_checks" not in patterns:
                logger.warning("Missing 'baseline_checks' section in patterns file")
                patterns["baseline_checks"] = {"minimal": []}

            self._patterns_cache = patterns
            logger.info(
                f"Successfully loaded {len(patterns.get('investigation_hints', {}))} investigation patterns"
            )
            return patterns

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {self._patterns_file}: {e}", exc_info=e)
            raise
        except Exception as e:
            logger.error(f"Error reading patterns file {self._patterns_file}: {e}", exc_info=e)
            raise

    def match_problem_to_patterns(
        self, problem_description: str, min_confidence: float = 0.3
    ) -> Tuple[Optional[str], Dict, float]:
        """Match problem description to investigation patterns.

        Uses keyword matching with confidence scoring to identify relevant
        investigation patterns.

        :param problem_description: User's problem description
        :type problem_description: str
        :param min_confidence: Minimum confidence threshold (0.0-1.0)
        :type min_confidence: float
        :returns: Tuple of (pattern_name, pattern_data, confidence_score)
        :rtype: Tuple[Optional[str], Dict, float]
        """
        if not problem_description:
            logger.warning("Empty problem description provided")
            return None, {}, 0.0

        hints = self.load_investigation_patterns().get("investigation_hints", {})
        if not hints:
            logger.warning("No investigation hints available")
            return None, {}, 0.0

        problem_lower = problem_description.lower()
        best_match: Optional[str] = None
        best_pattern: Dict = {}
        best_score: float = 0.0

        logger.debug(f"Matching problem to {len(hints)} patterns")

        for pattern_name, pattern_data in hints.items():
            keywords = pattern_data.get("keywords", [])
            if not keywords:
                continue
            score = (
                (sum(1 for keyword in keywords if keyword.lower() in problem_lower)) / len(keywords)
                if keywords
                else 0.0
            )
            if pattern_name.lower().replace("_", " ") in problem_lower:
                score = min(score + 0.3, 1.0)

            if score > best_score:
                best_score = score
                best_match = pattern_name
                best_pattern = pattern_data

        if best_score >= min_confidence:
            logger.info(
                f"Matched problem to pattern '{best_match}' with confidence {best_score:.2f}"
            )
            return best_match, best_pattern, best_score
        else:
            logger.info(
                f"No pattern match above threshold (best: {best_score:.2f}, required: {min_confidence})"
            )
            return None, {}, best_score

    @kernel_function(
        name="list_available_checks",
        description="List all available configuration check capabilities with their metadata",
    )
    def list_available_checks(self, category: str = "") -> str:
        """List available check capabilities.

        :param category: Optional filter by category (e.g., 'high_availability', 'network')
        :type category: str
        :returns: JSON-formatted string of available checks
        :rtype: str
        """
        try:
            capabilities = self.parse_check_files()

            if category:
                capabilities = {k: v for k, v in capabilities.items() if v.category == category}
                logger.info(f"Filtered to {len(capabilities)} checks in category '{category}'")
            grouped: Dict[str, List[Dict]] = {}
            for cap in capabilities.values():
                if cap.category not in grouped:
                    grouped[cap.category] = []

                grouped[cap.category].append(
                    {
                        "check_id": cap.id,
                        "name": cap.name,
                        "tags": cap.tags,
                        "description": cap.description,
                        "category": cap.category,
                    }
                )

            result = {
                "total_checks": len(capabilities),
                "categories": list(grouped.keys()),
                "checks_by_category": grouped,
            }

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error listing available checks: {e}", exc_info=e)
            return f"Error: {str(e)}"

    @kernel_function(
        name="suggest_relevant_checks",
        description="Suggest relevant configuration checks, logs, and search patterns based on problem description",
    )
    def suggest_relevant_checks(self, problem_description: str) -> str:
        """Suggest relevant checks, logs, and investigation guidance for a problem.

        :param problem_description: Description of the problem to investigate
        :type problem_description: str
        :returns: JSON-formatted string with comprehensive investigation metadata
        :rtype: str
        """
        try:
            pattern_name, pattern_data, confidence = self.match_problem_to_patterns(
                problem_description
            )

            if not pattern_name:
                patterns = self.load_investigation_patterns()
                result = {
                    "matched_pattern": None,
                    "confidence": 0.0,
                    "recommended_check_tags": patterns.get("baseline_checks", {}).get(
                        "standard", []
                    ),
                    "category_hints": ["general"],
                    "relevant_logs": ["messages", "syslog"],
                    "search_patterns": ["error", "fail", "critical"],
                    "explanation": "No specific pattern matched. Recommending baseline checks and system logs.",
                }
            else:
                recommended_tags = pattern_data.get("recommended_check_tags", [])
                category_hints = pattern_data.get("category_hints", [])
                relevant_logs = self._get_relevant_logs_for_categories(category_hints)
                search_patterns = pattern_data.get("keywords", [])

                result = {
                    "matched_pattern": pattern_name,
                    "confidence": round(confidence, 2),
                    "severity": pattern_data.get("severity", "unknown"),
                    "recommended_check_tags": recommended_tags,
                    "category_hints": category_hints,
                    "relevant_logs": relevant_logs,
                    "search_patterns": search_patterns,
                    "explanation": f"Problem matches '{pattern_name}' pattern. "
                    f"Recommend: (1) Run checks tagged {', '.join(recommended_tags)}, "
                    f"(2) Analyze logs {', '.join(relevant_logs)} with patterns {', '.join(search_patterns[:3])}",
                }

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error suggesting checks: {e}", exc_info=e)
            return json.dumps({"error": str(e)}, indent=2)

    def _get_relevant_logs_for_categories(self, categories: list[str]) -> list[str]:
        """Map category hints to relevant log types.

        :param categories: List of category hints
        :type categories: list[str]
        :returns: List of relevant log types
        :rtype: list[str]
        """
        log_mapping = {
            "high_availability": ["messages", "syslog"],
            "hana": ["hana_trace", "hana_alert", "messages"],
            "sap": ["sap_log", "messages"],
            "ascs": ["sap_log", "messages"],
            "network": ["messages", "syslog"],
            "azure": ["messages", "syslog"],
        }

        logs = set()
        for category in categories:
            logs.update(log_mapping.get(category.lower(), ["messages"]))
        if not logs:
            logs = {"messages", "syslog"}

        return sorted(list(logs))

    @kernel_function(
        name="get_expected_configuration",
        description="Get expected SAP HA configuration values from Microsoft best practices",
    )
    def get_expected_configuration(self, ha_type: str, configuration_section: str = "") -> str:
        """Get expected configuration values.

        :param ha_type: HA type ('scs' or 'db_hana')
        :type ha_type: str
        :param configuration_section: Optional specific section (e.g., 'CRM_CONFIG_DEFAULTS')
        :type configuration_section: str
        :returns: JSON-formatted string of expected configuration
        :rtype: str
        """
        try:
            constants = self.parse_constants_yaml(ha_type)

            if configuration_section:
                if configuration_section in constants:
                    result = {
                        "ha_type": ha_type,
                        "section": configuration_section,
                        "expected_values": constants[configuration_section],
                    }
                else:
                    available = list(constants.keys())
                    result = {
                        "error": f"Section '{configuration_section}' not found",
                        "available_sections": available,
                    }
            else:
                result = {
                    "ha_type": ha_type,
                    "available_sections": list(constants.keys()),
                    "all_constants": constants,
                }

            return json.dumps(result, indent=2)

        except ValueError as e:
            logger.error(f"Invalid ha_type: {e}")
            return f"Error: {str(e)}. Valid values: 'scs', 'db_hana'"
        except Exception as e:
            logger.error(f"Error getting expected configuration: {e}", exc_info=e)
            return f"Error: {str(e)}"

    @kernel_function(
        name="get_baseline_health_status",
        description="Get cached baseline health status for a workspace or recommend baseline checks to run",
    )
    def get_baseline_health_status(self, workspace_id: str) -> str:
        """Get baseline health status from cache or recommend checks.

        :param workspace_id: Workspace identifier (e.g., 'T02')
        :type workspace_id: str
        :returns: JSON-formatted string with cached baseline or recommendations
        :rtype: str
        """
        try:
            cached = self._workspace_store.get_baseline_cache(workspace_id)

            if cached:
                result = {
                    "cached": True,
                    "workspace_id": workspace_id,
                    "baseline_status": cached["data"],
                    "age_seconds": cached["age_seconds"],
                    "cached_at": cached["cached_at"],
                    "checks_executed": cached["check_tags"],
                }
                logger.info(f"Returned cached baseline for {workspace_id}")
            else:
                patterns = self.load_investigation_patterns()
                result = {
                    "cached": False,
                    "workspace_id": workspace_id,
                    "recommendation": "No baseline cached. Run baseline checks first.",
                    "recommended_check_tags": patterns.get("baseline_checks", {}).get(
                        "standard", []
                    ),
                    "cache_ttl_seconds": 300,
                }
                logger.info(f"No cached baseline for {workspace_id}, returning recommendations")

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Error getting baseline health status: {e}", exc_info=e)
            return f"Error: {str(e)}"

    @kernel_function(
        name="cache_baseline_results",
        description="Store baseline health check results in cache for future investigations",
    )
    def cache_baseline_results(self, workspace_id: str, results_json: str, check_tags: str) -> str:
        """Cache baseline check results.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :param results_json: JSON string of check results
        :type results_json: str
        :param check_tags: Comma-separated list of check tags that were executed
        :type check_tags: str
        :returns: Confirmation message
        :rtype: str
        """
        try:
            tags_list = [tag.strip() for tag in check_tags.split(",")]

            self._workspace_store.set_baseline_cache(
                workspace_id, json.loads(results_json), tags_list
            )

            logger.info(f"Cached baseline for {workspace_id} with {len(tags_list)} checks")
            return f"Baseline results cached successfully for workspace {workspace_id}"

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in results: {e}")
            return f"Error: Invalid JSON format in results"
        except Exception as e:
            logger.error(f"Error caching baseline results: {e}", exc_info=e)
            return f"Error: {str(e)}"

    @kernel_function(
        name="invalidate_baseline_cache",
        description="Invalidate cached baseline for a workspace (use after configuration changes)",
    )
    def invalidate_baseline_cache(self, workspace_id: str) -> str:
        """Invalidate baseline cache for a workspace.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        :returns: Confirmation message
        :rtype: str
        """
        try:
            self._workspace_store.invalidate_baseline_cache(workspace_id)
            return f"Baseline cache invalidated for workspace {workspace_id}"
        except Exception as e:
            logger.error(f"Error invalidating baseline cache: {e}", exc_info=e)
            return f"Error: {str(e)}"
