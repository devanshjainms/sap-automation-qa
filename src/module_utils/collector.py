# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Collectors for data collection in SAP Automation QA
"""
from abc import ABC, abstractmethod
import logging
from typing import Any
from dataclasses import dataclass

try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA


class Collector(ABC):
    """
    Base class for data collection
    """

    def __init__(self, parent: SapAutomationQA):
        """
        Initialize with parent module for logging

        :param parent: Parent module with logging capability
        :type parent: SapAutomationQA
        """
        self.parent = parent

    @abstractmethod
    def collect(self, check, context) -> Any:
        """
        Collect data for validation

        :param check: Check object
        :type check: Check
        :param context: Context object
        :type context: Context
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def substitute_context_vars(self, command: str, context: dict) -> str:
        """
        Substitute context variables in the command string.

        :param command: Command string with placeholders
        :type command: str
        :param context: Context variables to substitute
        :type context: dict
        :return: Command string with substituted values
        :rtype: str
        """
        self.parent.log(logging.INFO, f"Substituting context variables in command {command}")
        for key, value in context.items():
            placeholder = "{{ CONTEXT." + key + " }}"
            if placeholder in command:
                self.parent.log(
                    logging.INFO,
                    f"Substituting {placeholder} with {value} in command: {command}",
                )
                command = command.replace(placeholder, str(value))
        return command


class CommandCollector(Collector):
    """Collects data by executing shell commands"""

    def collect(self, check, context) -> str:
        """
        Execute a command and return the output.

        :param check: _Description of the check to be performed_
        :type check: Check
        :param context: Context variables to substitute in the command
        :type context: Dict[str, Any]
        :return: The output of the command
        :rtype: str
        """
        try:
            command = check.collector_args.get("command", "")
            user = check.collector_args.get("user", "")
            if not command:
                return ""

            command = self.substitute_context_vars(command, context)
            check.command = command
            if user and user != "root":
                command = f"sudo -u {user} {command}"

            return self.parent.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.parent.handle_error(ex)
            return ""


class AzureDataCollector(Collector):
    """Collects data from Azure resources"""

    def collect(self, check, context) -> Any:
        """
        Collect data from Azure resources using the Azure Python Client.

        :param check: Check object containing collector arguments
        :type check: Check
        :param context: Context object containing variables to substitute in the command
        :type context: Dict[str, Any]
        :raises ValueError: If the query type is unsupported
        :return: The output of the Azure Python Client
        :rtype: Any
        """
        try:
            command = check.collector_args.get("command", "")
            if not command:
                return ""

            command = self.substitute_context_vars(command, context)
            check.command = command

            return self.parent.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.parent.handle_error(ex)


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
