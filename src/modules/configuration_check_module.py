# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Ansible Python module to check the configuration of the workload system running on Azure
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Type
from datetime import datetime
from ansible.module_utils.basic import AnsibleModule

try:
    from ansible.module_utils.sap_automation_qa import TestStatus, Severity, SapAutomationQA
    from ansible.module_utils.collector import Collector, CommandCollector, AzureDataCollector
except ImportError:
    from src.module_utils.sap_automation_qa import TestStatus, Severity, SapAutomationQA
    from src.module_utils.collector import Collector, CommandCollector, AzureDataCollector


@dataclass
class ApplicabilityRule:
    """
    Represents a rule to determine if a check is applicable based on context properties

    :param property: The property to check against
    :type property: str
    :param value: The expected value of the property
    :type value: Any
    """

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
        if isinstance(context_value, str):
            context_value = context_value.strip()
            if self.property == "os_version" and self.value == "all":
                return True

            if context_value.lower() == "true":
                context_value = True
            elif context_value.lower() == "false":
                context_value = False

        if isinstance(self.value, list):
            if isinstance(context_value, list):
                return bool(set(self.value).intersection(set(context_value)))
            if self.property == "storage_type":
                return any(val in context_value for val in self.value) or any(
                    context_value in val for val in self.value
                )
            return context_value in self.value

        if isinstance(self.value, bool):
            return context_value == self.value

        return context_value == self.value


@dataclass
class Check:
    """
    Represents a configuration check

    :param id: Unique identifier for the check
    :type id: str
    :param name: Name of the check
    :type name: str
    :param description: Description of the check
    :type description: str
    :param category: Category of the check
    :type category: str
    :param workload: Workload type (e.g., SAP, Non-SAP)
    :type workload: str
    :param severity: Severity level of the check
    :type severity: Severity
    :param collector_type: Type of collector to use (e.g., command, azure)
    :type collector_type: str
    :param collector_args: Arguments for the collector
    :type collector_args: Dict[str, Any]
    :param validator_type: Type of validator to use (e.g., string, range)
    :type validator_type: str
    :param validator_args: Arguments for the validator
    :type validator_args: Dict[str, Any]
    :param tags: Tags associated with the check
    :type tags: List[str]
    :param applicability: List of applicability rules
    :type applicability: List[ApplicabilityRule]
    :param references: References for the check
    :type references: Dict[str, str]
    :param report: Report type (e.g., check, section)
    :type report: Optional[str]
    """

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
        """
        Check if the check is applicable based on the context

        :param context: Context dictionary containing properties
        :type context: Dict[str, Any]
        :return: True if applicable, False otherwise
        :rtype: bool
        """

        for rule in self.applicability:
            context_value = context[rule.property]
            if not rule.is_applicable(context_value):
                return False

        return True


@dataclass
class CheckResult:
    """
    Represents the result of a check execution

    :param check: The check that was executed
    :type check: Check
    :param status: Status of the check execution
    :type status: TestStatus
    :param hostname: Hostname of the system where the check was executed
    :type hostname: str
    :param expected_value: Expected value from the check
    :type expected_value: Any
    :param actual_value: Actual value collected during the check
    :type actual_value: Any
    :param execution_time: Time taken to execute the check
    :type execution_time: float
    :param timestamp: Timestamp of the check execution
    :type timestamp: datetime
    :param details: Additional details about the check execution
    :type details: Optional[str]
    """

    check: Check
    status: TestStatus
    hostname: str
    expected_value: Any
    actual_value: Any
    execution_time: float
    timestamp: datetime = field(default_factory=datetime.now)
    details: Optional[str] = None


class ConfigurationCheckModule(SapAutomationQA):
    """
    Class to handle configuration checks using the ConfigurationCheck class.
    """

    def __init__(self, module):
        self.module = module
        self.module_params = module.params
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
            "check_support": self.validate_vm_support,
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
        """
        Register a custom validator function

        :param validator_type: Identifier for the validator type
        :type validator_type: str
        :param validator_func: Function implementing the validation logic
        :type validator_func: Callable
        """
        self._validators[validator_type] = validator_func

    def is_check_applicable(self, check: Check) -> bool:
        """
        Check if a check is applicable based on its applicability rules and the current context

        :param check: The check to evaluate
        :type check: Check
        :return: True if applicable, False otherwise
        :rtype: bool
        """
        self.log(
            logging.DEBUG,
            f"Checking applicability for check {check.applicability} with context: {self.context}",
        )
        for rule in check.applicability:
            context_value = self.context.get(rule.property)
            if not rule.is_applicable(context_value):
                self.log(
                    logging.DEBUG,
                    f"Check {check.id} not applicable: Rule for '{rule.property}' with value "
                    + f"'{rule.value}' doesn't match context value '{context_value}'",
                )
                return False

        return True

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
                    report=check.get("report", "check"),
                )
            )
        self.log(
            logging.INFO,
            f"Loaded {len(self.checks)} checks from the configuration file.",
        )

    def _create_validation_result(self, severity: Severity, is_success: bool) -> TestStatus:
        """
        Create a validation result based on severity and success status

        :param severity: Severity of the check
        :type severity: Severity
        :param is_success: Whether the check was successful
        :type is_success: bool
        """
        if is_success:
            return TestStatus.SUCCESS.value

        severity_map = {
            Severity.INFO: TestStatus.INFO.value,
            Severity.LOW: TestStatus.WARNING.value,
            Severity.WARNING: TestStatus.WARNING.value,
            Severity.CRITICAL: TestStatus.ERROR.value,
        }
        return severity_map.get(severity, TestStatus.ERROR.value)

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

        if check.validator_args.get("strip_whitespace", True):
            expected = str(expected).strip()

        if check.validator_args.get("case_insensitive", False):
            expected = expected.lower()
            collected = collected.lower()

        return {
            "status": self._create_validation_result(check.severity, collected == expected),
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

            return {
                "status": self._create_validation_result(
                    check.severity, min_val <= value <= max_val
                ),
            }
        except ValueError:
            return {
                "status": TestStatus.ERROR.value,
            }

    def validate_list(self, check: Check, collected_data: str) -> Dict[str, Any]:
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
        return {
            "status": self._create_validation_result(
                check.severity, any(item in expected_list for item in collected_list)
            ),
        }

    def validate_vm_support(self, check: Check, collected_data: str) -> Dict[str, Any]:
        """
        Validates if a VM SKU is supported for the given role and database type

        :param check: Check definition
        :type check: Check
        :param collected_data: VM SKU from metadata service
        :type collected_data: str
        :return: Validation result
        :rtype: Dict[str, Any]
        """
        try:
            value = collected_data.strip()
            role = self.context.get("role", "")
            database_type = self.context.get("database_type", "")
            validation_rules = check.validator_args.get("validation_rules", {})
            supported_configurations = self.context.get("supported_configurations", {}).get(
                validation_rules, {}
            )

            if not value or not supported_configurations or not role:
                return {
                    "status": TestStatus.ERROR.value,
                }

            if "VMs" in validation_rules:
                if database_type not in supported_configurations.get(value, {}).get(role, {}).get(
                    "SupportedDB", []
                ):
                    return {
                        "status": TestStatus.ERROR.value,
                    }

            elif "OSDB" in validation_rules:
                if role not in supported_configurations.get(
                    database_type, {}
                ) or value.upper() not in supported_configurations.get(database_type, {}).get(
                    role, []
                ):
                    return {
                        "status": TestStatus.ERROR.value,
                    }

            return {
                "status": TestStatus.SUCCESS.value,
            }

        except Exception:
            return {
                "status": TestStatus.ERROR.value,
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
            actual_value=None,
            execution_time=0,
            details=None,
        ) -> CheckResult:
            """
            Create a CheckResult object

            :param status: Status of the check execution
            :type status: TestStatus
            :param actual_value: Actual value collected during the check, defaults to None
            :type actual_value: str, optional
            :param execution_time: Time taken to execute the check, defaults to 0
            :type execution_time: int, optional
            :param details: Additional details about the check execution, defaults to None
            :type details: str, optional
            :return: CheckResult object
            :rtype: CheckResult
            """
            return CheckResult(
                check=check,
                status=status,
                hostname=self.hostname or "unknown",
                expected_value=check.validator_args.get("expected_output"),
                actual_value=actual_value,
                execution_time=execution_time,
                timestamp=datetime.now(),
                details=details,
            )

        if not self.is_check_applicable(check):
            return create_result(TestStatus.SKIPPED.value, details="Check not applicable")

        collector_class = self._collectors.get(check.collector_type)
        if not collector_class:
            return create_result(
                status=TestStatus.ERROR.value,
                details=f"No collector found for type: {check.collector_type}",
            )

        collector = collector_class()

        start_time = time.time()
        try:
            collected_data = collector.collect(check, self.context)
            validation_result = self.validate_result(check, collected_data)

            execution_time = time.time() - start_time

            result = create_result(
                status=validation_result["status"],
                actual_value=collected_data,
                execution_time=execution_time,
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            self.log(logging.ERROR, f"Error executing check {check.id}: {str(e)}")

            return create_result(
                status=TestStatus.ERROR.value,
                actual_value=None,
                execution_time=execution_time,
                details=f"Error: {str(e)}",
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

        if filter_tags:
            tag_set = set(filter_tags)
            checks_to_run = [c for c in checks_to_run if any(tag in tag_set for tag in c.tags)]

        if filter_categories:
            category_set = set(filter_categories)
            checks_to_run = [c for c in checks_to_run if c.category in category_set]

        if not checks_to_run:
            self.log(
                logging.WARNING,
                f"No checks match the specified filters: tags={filter_tags}, "
                + f"categories={filter_categories}",
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
            f"WARNING: {summary['warnings']},"
            f"SKIPPED: {summary['skipped']}",
        )

        self.result.update(
            {
                "status": (
                    TestStatus.SUCCESS.value if summary["failed"] == 0 else TestStatus.ERROR.value
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
                "skipped": 0,
                "info": 0,
            }

        return {
            "total": len(self.result["check_results"]),
            "passed": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.SUCCESS.value
            ),
            "failed": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.ERROR.value
            ),
            "warnings": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.WARNING.value
            ),
            "skipped": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.SKIPPED.value
            ),
            "info": sum(
                1 for r in self.result["check_results"] if r.status == TestStatus.INFO.value
            ),
        }

    def format_results_for_html_report(self):
        """
        Reformat results for HTML report
        """
        serialized_results = []
        for check_result in self.result["check_results"]:
            result_dict = {
                "check": {
                    "id": check_result.check.id,
                    "name": check_result.check.name,
                    "description": check_result.check.description,
                    "category": check_result.check.category,
                    "workload": check_result.check.workload,
                    "severity": (
                        check_result.check.severity.value
                        if hasattr(check_result.check.severity, "value")
                        else str(check_result.check.severity)
                    ),
                    "collector_type": check_result.check.collector_type,
                    "collector_args": check_result.check.collector_args,
                    "validator_type": check_result.check.validator_type,
                    "validator_args": check_result.check.validator_args,
                    "tags": check_result.check.tags,
                    "references": check_result.check.references,
                    "report": check_result.check.report,
                },
                "status": (
                    check_result.status.value
                    if hasattr(check_result.status, "value")
                    else str(check_result.status)
                ),
                "hostname": check_result.hostname,
                "expected_value": check_result.expected_value,
                "actual_value": check_result.actual_value,
                "execution_time": check_result.execution_time,
                "timestamp": (
                    check_result.timestamp.isoformat()
                    if hasattr(check_result.timestamp, "isoformat")
                    else str(check_result.timestamp)
                ),
                "details": check_result.details,
            }
            serialized_results.append(result_dict)
        self.result["check_results"] = serialized_results

    def run(self):
        """
        Run the module
        """
        try:
            context = self.module_params["context"]
            custom_hostname = self.module_params["hostname"]

            if custom_hostname:
                context["hostname"] = custom_hostname

            self.set_context(context)
            self.load_checks(raw_file_content=self.module_params["check_file_content"])
            self.execute_checks(
                self.module_params["filter_tags"], self.module_params["filter_categories"]
            )
            self.format_results_for_html_report()
            result = dict(self.result)

            if "summary" in result:
                summary = dict(result["summary"])
                result["summary"] = summary
            self.module.exit_json(**result)
        except Exception as e:
            self.module.fail_json(msg=f"Error: {str(e)}")


def main():
    """
    Main function to run the Ansible module
    """
    module_args = dict(
        check_file_content=dict(type="str", required=True),
        context=dict(type="dict", required=True),
        filter_tags=dict(type="list", elements="str", required=False, default=None),
        filter_categories=dict(type="list", elements="str", required=False, default=None),
        workspace_directory=dict(type="str", required=True),
        hostname=dict(type="str", required=False, default=None),
        test_group_invocation_id=dict(type="str", required=True),
        test_group_name=dict(type="str", required=True),
    )
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    runner = ConfigurationCheckModule(module)
    runner.run()


if __name__ == "__main__":
    main()
