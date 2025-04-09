# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Collectors for data collection in SAP Automation QA
"""
try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA

from abc import ABC, abstractmethod
import logging
from typing import Any


class Collector(SapAutomationQA, ABC):
    """
    Base class for data collection
    """

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
        for key, value in context.items():
            placeholder = "{{ CONTEXT." + key + " }}"
            if placeholder in command:
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
            if user and user != "root":
                command = f"sudo -u {user} {command}"

            return self.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.hanlde_error(ex)


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

            return self.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.hanlde_error(ex)
