# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Collectors for data collection in SAP Automation QA
"""
from abc import ABC, abstractmethod
import logging
import re
import shlex
from typing import Any

try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
    from ansible.module_utils.commands import DANGEROUS_COMMANDS
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA
    from src.module_utils.commands import DANGEROUS_COMMANDS


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

    def sanitize_command(self, command: str) -> str:
        """
        Sanitize command to prevent injection attacks

        :param command: Raw command string
        :type command: str
        :return: Sanitized command or None if dangerous
        :rtype: str
        :raises ValueError: If command contains dangerous patterns
        """

        for pattern in DANGEROUS_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                self.parent.log(logging.ERROR, f"Dangerous command pattern detected: {pattern}")
                raise ValueError(f"Command contains potentially dangerous pattern: {pattern}")
        if len(command) > 1000:
            self.parent.log(logging.ERROR, f"Command too long: {len(command)} chars")
            raise ValueError("Command exceeds maximum length of 1000 characters")

        return command

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
                return "ERROR: No command specified"
            try:
                command = self.sanitize_command(command)
            except ValueError as e:
                self.parent.log(logging.ERROR, f"Command sanitization failed: {e}")
                return f"ERROR: Command sanitization failed: {e}"
            command = self.substitute_context_vars(command, context)
            try:
                command = self.sanitize_command(command)
            except ValueError as e:
                self.parent.log(
                    logging.ERROR, f"Command sanitization failed after substitution: {e}"
                )
                return f"ERROR: Command sanitization failed after substitution: {e}"

            check.command = command
            if user and user != "root":
                if not re.match(r"^[a-zA-Z0-9_-]+$", user):
                    self.parent.log(logging.ERROR, f"Invalid user parameter: {user}")
                    return f"ERROR: Invalid user parameter: {user}"
                command = f"sudo -u {shlex.quote(user)} {command}"

            return self.parent.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.parent.handle_error(ex)
            return f"ERROR: Command execution failed: {str(ex)}"


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
                return "ERROR: No Azure command specified"
            try:
                command = self.sanitize_command(command)
            except ValueError as e:
                self.parent.log(logging.ERROR, f"Azure command sanitization failed: {e}")
                return f"ERROR: Azure command sanitization failed: {e}"

            command = self.substitute_context_vars(command, context)
            try:
                command = self.sanitize_command(command)
            except ValueError as e:
                self.parent.log(
                    logging.ERROR, f"Azure command sanitization failed after substitution: {e}"
                )
                return f"ERROR: Azure command sanitization failed after substitution: {e}"

            check.command = command

            return self.parent.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.parent.handle_error(ex)
            return f"ERROR: Azure command execution failed: {str(ex)}"
