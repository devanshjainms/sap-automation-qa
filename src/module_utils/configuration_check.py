"""
This module is used to setup the context for the test cases
and setup base variables for the test case running in the sap-automation-qa
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Type
from datetime import datetime

try:
    from ansible.module_utils.sap_automation_qa import TestStatus, Severity, SapAutomationQA
    from ansible.module_utils.collector import Collector, CommandCollector, AzureDataCollector
except ImportError:
    from src.module_utils.sap_automation_qa import TestStatus, Severity, SapAutomationQA
    from src.module_utils.collector import Collector, CommandCollector, AzureDataCollector


@dataclass
class ApplicabilityRule:
    """Rules that determine if a check applies to a target"""

    property: str
    value: Any

    def is_applicable(self, context_value: Any) -> bool:
        """
        Check if the rule applies to the given context value
        :param context_value: Value from the context to check against
        :type context_value: Any
        :return: True if applicable, False otherwise
        :rtype: bool
        """
        if isinstance(self.value, list):
            if isinstance(context_value, list):
                return any(val in context_value for val in self.value)
            return context_value in self.value

        if isinstance(self.value, bool):
            return context_value == self.value

        return context_value == self.value


@dataclass
class Check:
    """Represents a configuration validation check"""

    id: str
    name: str
    description: str
    category: str
    workload: str
    severity: Severity = Severity.WARNING
    collector_type: str = "command"
    collector_args: Dict[str, Any] = field(default_factory=dict)
    validator_type: str = "string"
    validator_args: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    applicability: List[ApplicabilityRule] = field(default_factory=list)
    references: Dict[str, str] = field(default_factory=dict)
    report: Optional[str] = "check"

    def is_applicable(self, context: Dict[str, Any]) -> bool:
        """Check if this check is applicable to the given context"""
        for rule in self.applicability:
            if rule.property not in context:
                return False

            context_value = context[rule.property]
            if not rule.is_applicable(context_value):
                return False

        return True


@dataclass
class CheckResult:
    """Represents the result of executing a check"""

    check: Check
    status: TestStatus
    hostname: str
    collected_data: Any
    expected_value: Any
    actual_value: Any
    execution_time: float
    timestamp: datetime = field(default_factory=datetime.now)
    details: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConfigurationCheck(SapAutomationQA):
    """
    This class is used to setup the context for the configuration checks
    and setup base variables for the configuration check running in the sap-automation-qa
    """

    def __init__(self):
        super().__init__()
        self.checks: List[Check] = []
        self.result.update(
            {
                "check_results": [],
            }
        )
        self.hostname: Optional[str] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.context: Dict[str, Any] = {}
        self._collectors: Dict[str, Type[Collector]] = {
            "command": CommandCollector,
            "azure": AzureDataCollector,
        }
        self._validators = {
            "string": self.validate_string,
            "range": self.validate_numeric_range,
            "list": self.validate_list,
        }

    def register_collector(self, collector_type: str, collector_class: Type[Collector]) -> None:
        """
        Register a custom collector implementation

        :param collector_type: Identifier for the collector type
        :type collector_type: str
        :param collector_class: Class implementing the Collector interface
        :type collector_class: Type[Collector]
        """
        self._collectors[collector_type] = collector_class

    def register_validator(self, validator_type: str, validator_func):
        """Register a new validator function"""
        self._validators[validator_type] = validator_func

    def is_check_applicable(self, check: Check) -> bool:
        """Determine if a check is applicable to the current context"""
        return check.is_applicable(self.context)

    def set_context(self, context: Dict[str, Any]) -> None:
        """
        Set execution context for checks

        :param context: Dictionary containing context variables like OS, version, etc.
        :type context: Dict[str, Any]
        """
        self.context = context
        self.hostname = context.get("hostname")

    def load_checks(self, raw_file_content: str) -> None:
        """
        Load checks from a YAML file.
        Validates the structure and initializes Check objects based on applicability rules.

        :param raw_file_content: Check file content as a string or dictionary
        :type raw_file_content: str or dict
        """
        check_file_content = None

        if isinstance(raw_file_content, str):
            check_file_content = self.parse_yaml_from_content(raw_file_content)

        if not check_file_content:
            self.log(logging.ERROR, "YAML parsing failed: No content found.")
            return

        if "checks" in check_file_content:
            checks = check_file_content.get("checks", [])
        else:
            checks = check_file_content
        if not checks:
            self.log(logging.ERROR, "No checks found in the file.")
            return
        for check in checks:
            if not isinstance(check, dict):
                self.log(logging.ERROR, f"Invalid check format. {check}")
                continue

            applicability_rules = []
            if "applicability" in check and isinstance(check["applicability"], dict):
                for property_name, property_value in check["applicability"].items():
                    applicability_rules.append(
                        ApplicabilityRule(property=property_name, value=property_value)
                    )

            self.checks.append(
                Check(
                    id=check.get("id", "unknown"),
                    name=check.get("name", "Unnamed Check"),
                    description=check.get("description", ""),
                    category=check.get("category", "General"),
                    workload=check.get("workload", "SAP"),
                    severity=Severity(check.get("severity", "WARNING")),
                    collector_type=check.get("collector_type", "command"),
                    collector_args=check.get("collector_args", {}),
                    validator_type=check.get("validator_type", "string"),
                    validator_args=check.get("validator_args", {}),
                    tags=check.get("tags", []),
                    applicability=applicability_rules,
                    references=check.get("references", {}),
                )
            )
        self.log(
            logging.INFO,
            f"Loaded {len(self.checks)} checks from the configuration file.",
        )

    def validate_string(self, check: Check, collected_data: str) -> Dict[str, Any]:
        """
        Validate string data against expected values

        :param check: The check definition
        :type check: Check
        :param collected_data: Collected string data
        :type collected_data: str
        :return: Validation result
        :rtype: Dict[str, Any]
        """
        expected = check.validator_args.get("expected_output", "")
        collected = str(collected_data).strip() if collected_data is not None else ""

        # Apply transforms if specified
        if check.validator_args.get("strip_whitespace", True):
            expected = str(expected).strip()

        if check.validator_args.get("case_insensitive", False):
            expected = expected.lower()
            collected = collected.lower()

        is_equal = collected == expected

        if is_equal:
            return {
                "status": TestStatus.SUCCESS.value,
                "message": "Value matches expected result",
                "actual_value": collected,
            }
        else:
            # Determine severity of failure based on check
            if check.severity == Severity.INFO:
                status = TestStatus.INFO.value
            elif check.severity == Severity.LOW:
                status = TestStatus.WARNING.value
            else:
                status = TestStatus.FAILED.value

            return {
                "status": status,
                "message": "Value does not match expected result",
                "actual_value": collected,
                "difference": f"Expected: '{expected}', Got: '{collected}'",
            }

    def validate_numeric_range(self, check: Check, collected_data: str) -> Dict[str, Any]:
        """
        Validate numeric data against expected range

        :param check: The check definition
        :type check: Check
        :param collected_data: Collected numeric data as string
        :type collected_data: str
        :return: Validation result
        :rtype: Dict[str, Any]
        """
        try:
            value = float(str(collected_data).strip())
            min_val = float(check.validator_args.get("min", "-inf"))
            max_val = float(check.validator_args.get("max", "inf"))

            within_range = min_val <= value <= max_val

            if within_range:
                return {
                    "status": TestStatus.SUCCESS.value,
                    "message": f"Value {value} is within range [{min_val}, {max_val}]",
                    "actual_value": value,
                }
            else:
                if check.severity == Severity.INFO:
                    status = TestStatus.INFO.value
                elif check.severity == Severity.LOW:
                    status = TestStatus.WARNING.value
                else:
                    status = TestStatus.FAILED.value

                return {
                    "status": status,
                    "message": f"Value {value} is outside range [{min_val}, {max_val}]",
                    "actual_value": value,
                    "min": min_val,
                    "max": max_val,
                }
        except ValueError:
            return {
                "status": TestStatus.ERROR.value,
                "message": f'Cannot convert "{collected_data}" to a numeric value',
                "actual_value": collected_data,
            }

    def validate_list(self, check: Check, collected_data: str) -> Dict[str, Any]:
        # Validate if the collected data is in the expected list
        """
        Validate collected data against expected list (contains)

        :param check: Check
        :type check: Check
        :param collected_data: Data collected from system
        :type collected_data: str
        :return: Validation result dictionary
        :rtype: Dict[str, Any]
        """
        expected_list = check.validator_args.get("expected_output", [])
        collected_list = str(collected_data).strip().split(",") if collected_data else []
        collected_list = [item.strip() for item in collected_list]
        is_in_list = any(item in expected_list for item in collected_list)
        if is_in_list:
            return {
                "status": TestStatus.SUCCESS.value,
                "message": "Value is in the expected list",
                "actual_value": collected_list,
            }
        else:
            # Determine severity of failure based on check
            if check.severity == Severity.INFO:
                status = TestStatus.INFO.value
            elif check.severity == Severity.LOW:
                status = TestStatus.WARNING.value
            else:
                status = TestStatus.FAILED.value

            return {
                "status": status,
                "message": "Value is not in the expected list",
                "actual_value": collected_list,
                "expected_list": expected_list,
            }

    def validate_result(self, check: Check, collected_data: Any) -> Dict[str, Any]:
        """
        Validate collected data based on the validator type

        :param check: Check definition
        :type check: Check
        :param collected_data: Data collected from system
        :type collected_data: Any
        :return: Validation result dictionary
        :rtype: Dict[str, Any]
        """
        validator = self._validators.get(check.validator_type)
        if validator:
            return validator(check, collected_data)
        else:
            return {
                "status": TestStatus.ERROR.value,
                "message": f"Unknown validator type: {check.validator_type}",
                "actual_value": None,
            }

    def execute_check(self, check: Check) -> CheckResult:
        """
        Execute a single check against the current context

        :param check: Check to execute
        :type check: Check
        :return: Result of the check execution
        :rtype: CheckResult
        """

        def create_result(
            status: TestStatus,
            collected_data=None,
            actual_value=None,
            execution_time=0,
            details=None,
            metadata=None,
        ) -> CheckResult:
            return CheckResult(
                check=check,
                status=status,
                hostname=self.hostname or "unknown",
                collected_data=collected_data,
                expected_value=check.validator_args.get("expected_output"),
                actual_value=actual_value,
                execution_time=execution_time,
                details=details,
                metadata=metadata or {},
                timestamp=datetime.now(),
            )

        if not self.is_check_applicable(check):
            return create_result(TestStatus.SKIPPED.value, details="Check not applicable")

        # Find appropriate collector
        collector_class = self._collectors.get(check.collector_type)
        if not collector_class:
            return create_result(
                status=TestStatus.ERROR.value,
                details=f"No collector found for type: {check.collector_type}",
            )

        collector = collector_class()

        start_time = time.time()
        try:
            # Collect data
            collected_data = collector.collect(check, self.context)

            # Validate data
            validation_result = self.validate_result(check, collected_data)

            execution_time = time.time() - start_time

            result = create_result(
                status=validation_result["status"],
                collected_data=collected_data,
                actual_value=validation_result.get("actual_value"),
                execution_time=execution_time,
                details=validation_result.get("message"),
                metadata=validation_result,
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            self.log(logging.ERROR, f"Error executing check {check.id}: {str(e)}")

            return create_result(
                status=TestStatus.ERROR.value,
                collected_data=None,
                actual_value=None,
                execution_time=execution_time,
                details=f"Error: {str(e)}",
                metadata={"exception": str(e)},
            )

    def execute_checks(
        self, filter_tags: Optional[List[str]] = None, filter_categories: Optional[List[str]] = None
    ) -> List[CheckResult]:
        """
        Execute all loaded checks, optionally filtered by tags or categories

        :param filter_tags: Optional list of tags to filter checks by
        :type filter_tags: Optional[List[str]]
        :param filter_categories: Optional list of categories to filter checks by
        :type filter_categories: Optional[List[str]]
        :return: List of check results
        :rtype: List[CheckResult]
        """
        checks_to_run = self.checks

        # Filter by tags if specified
        if filter_tags:
            tag_set = set(filter_tags)
            checks_to_run = [c for c in checks_to_run if any(tag in tag_set for tag in c.tags)]

        # Filter by categories if specified
        if filter_categories:
            category_set = set(filter_categories)
            checks_to_run = [c for c in checks_to_run if c.category in category_set]

        if not checks_to_run:
            self.log(
                logging.WARNING,
                f"No checks match the specified filters: tags={filter_tags}, categories={filter_categories}",
            )
            return []

        self.start_time = datetime.now()
        self.log(logging.INFO, f"Starting execution of {len(checks_to_run)} checks")

        results = []
        for check in checks_to_run:
            result = self.execute_check(check)
            results.append(result)
            self.result["check_results"].append(result)

        self.end_time = datetime.now()

        summary = self.get_results_summary()

        duration = (self.end_time - self.start_time).total_seconds()
        self.log(
            logging.INFO,
            f"Check execution complete. Duration: {duration:.2f}s. "
            f"PASSED: {summary['passed']}, FAILED: {summary['failed']}, "
            f"WARNING: {summary['warnings']}, ERROR: {summary['errors']}, "
            f"SKIPPED: {summary['skipped']}",
        )

        self.result.update(
            {
                "status": (
                    TestStatus.SUCCESS.value if summary["failed"] == 0 else TestStatus.FAILED.value
                ),
                "message": f"Check execution completed with {summary['failed']} failures",
                "summary": summary,
                "check_results": results,
            }
        )

    def get_results_summary(self) -> Dict[str, int]:
        """
        Get summary statistics for check results

        :return: Dictionary with result summaries
        :rtype: Dict[str, int]
        """
        if not self.result["check_results"]:
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "warnings": 0,
                "errors": 0,
                "skipped": 0,
                "info": 0,
            }

        return {
            "total": len(self.result["check_results"]),
            "passed": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.SUCCESS.value
            ),
            "failed": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.FAILED.value
            ),
            "warnings": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.WARNING.value
            ),
            "errors": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.ERROR.value
            ),
            "skipped": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.SKIPPED.value
            ),
            "info": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.INFO.value
            ),
        }

    def clear_results(self) -> None:
        """
        Clear all stored results
        """
        self.result["check_results"] = []
        self.start_time = None
        self.end_time = None

    def get_results_by_category(self) -> Dict[str, List[CheckResult]]:
        """
        Group results by check workload category

        :return: Dictionary with results grouped by workload
        :rtype: Dict[str, List[CheckResult]]
        """
        categories = {}
        for result in self.result["check_results"]:
            workload = result.check.workload
            if workload not in categories:
                categories[workload] = []
            categories[workload].append(result)
        return categories
