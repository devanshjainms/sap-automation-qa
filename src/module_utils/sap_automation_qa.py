"""
This module is used to setup the context for the test cases
and setup base variables for the test case running in the sap-automation-qa
"""

from abc import ABC, abstractmethod
from enum import Enum
import sys
import logging
import subprocess
import yaml
from typing import Optional, Dict, Any
import xml.etree.ElementTree as ET


class Severity(Enum):
    """
    Enum for the severity of the test case/step.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class TelemetryDataDestination(Enum):
    """
    Enum for the destination of the telemetry data.
    """

    KUSTO = "azuredataexplorer"
    LOG_ANALYTICS = "azureloganalytics"


class TestStatus(Enum):
    """
    Enum for the status of the test case/step.
    """

    SUCCESS = "PASSED"
    ERROR = "ERROR"
    FAILED = "FAILED"
    WARNING = "WARNING"
    INFO = "INFO"
    NOT_STARTED = "NOT_STARTED"
    SKIPPED = "SKIPPED"


class Parameters:
    """
    This class is used to store the parameters for the test case
    """

    def __init__(self, category, id, name, value, expected_value, status):
        self.category = category
        self.id = id
        self.name = name
        self.value = value
        self.expected_value = expected_value
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        """
        This method is used to convert the parameters to a dictionary

        :return: Dictionary containing the parameters
        :rtype: Dict[str, Any]
        """
        return {
            "category": self.category,
            "id": self.id,
            "name": self.name,
            "value": self.value,
            "expected_value": self.expected_value,
            "status": self.status,
        }


class SapAutomationQA(ABC):
    """
    This class is used to setup the context for the test cases
    and setup base variables for the test case running in the sap-automation-qa
    """

    def __init__(self):
        self.logger = self.setup_logger()
        self.result = {
            "status": TestStatus.NOT_STARTED.value,
            "message": "",
            "details": [],
            "logs": [],
            "changed": False,
        }

    def setup_logger(self) -> logging.Logger:
        """
        This method is used to setup the logger for the test case

        :return: Configured logger instance
        :rtype: logging.Logger
        """
        logger = logging.getLogger("sap-automation-qa")
        logger.setLevel(logging.INFO)
        log_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(log_format)
        logger.addHandler(stream_handler)
        return logger

    def log(self, level: int, message: str):
        """
        Logs a message and adds it to the result logs.

        :param level: Logging level (e.g., logging.INFO, logging.ERROR)
        :type level: int
        :param message: Message to log
        :type message: str
        """
        self.logger.log(level, message)
        message.replace("\n", " ")
        self.result["logs"].append(message)

    def handle_error(self, exception: Exception, stderr: str = None):
        """
        Handles command execution errors by logging and updating the result dictionary.

        :param exception: Exception raised during command execution
        :type exception: Exception
        :param stderr: Standard error output from the command
        :type stderr: str
        """
        error_message = f"Error executing command: {exception}."
        if stderr:
            error_message += f" More errors: {stderr}"
        error_message.replace("'", "")
        self.log(logging.ERROR, error_message)
        self.result["status"] = TestStatus.ERROR.value
        self.result["message"] = error_message
        self.result["logs"].append(error_message)

    def execute_command_subprocess(self, command: str, shell_command: bool = False) -> str:
        """
        Executes a shell command using subprocess with a timeout and logs output or errors.

        :param command: Shell command to execute
        :type command: str
        :param shell_command: Whether the command is a shell command
        :type shell_command: bool
        :return: Standard output from the command
        :rtype: str
        """
        command_string = command if isinstance(command, str) else " ".join(command).replace("'", "")
        self.log(
            logging.INFO,
            f"Executing command: {command_string}",
        )
        try:
            command_output = subprocess.run(
                command,
                timeout=30,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell_command,
            )
            stdout = command_output.stdout.decode("utf-8")
            stderr = command_output.stderr.decode("utf-8")
            return stdout if not stderr else stderr
        except subprocess.TimeoutExpired as ex:
            self.handle_error(ex, "Command timed out")
        except subprocess.CalledProcessError as ex:
            self.handle_error(ex, ex.stderr.decode("utf-8").strip())
        except Exception as ex:
            self.handle_error(ex, "")
        return ""

    def parse_xml_output(self, xml_output: str) -> Optional[ET.Element]:
        """
        Parses the XML output and returns the root element.

        :param xml_output: XML output to parse
        :type xml_output: str
        :return: The root element of the XML output
        :rtype: Optional[ET.Element]
        """
        if xml_output.startswith("<"):
            return ET.fromstring(xml_output)
        return None

    def get_result(self) -> Dict[str, Any]:
        """
        Returns the result dictionary.

        :return: The result dictionary containing the status, message, details, and logs.
        :rtype: Dict[str, Any]
        """
        return self.result

    def parse_yaml_from_content(self, yaml_content: str) -> Optional[Dict[str, Any]]:
        """
        Parses a YAML file and returns its content as a dictionary.

        :param yaml_content: Content of the YAML file
        :type yaml_content: str
        :return: Content of the YAML file as a dictionary
        :rtype: Optional[Dict[str, Any]]
        """
        try:
            return yaml.safe_load(yaml_content)
        except yaml.YAMLError as ex:
            self.log(logging.ERROR, f"Error parsing YAML content: {ex}")
            return None
