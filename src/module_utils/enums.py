"""
This module defines various enumerations used throughout the Ansible module.
"""

from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any


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
    ERROR = "FAILED"
    WARNING = "WARNING"
    INFO = "INFO"
    NOT_STARTED = "NOT_STARTED"


class OperatingSystemFamily(Enum):
    """
    Enum for the operating system family.
    """

    REDHAT = "REDHAT"
    SUSE = "SUSE"


class HanaSRProvider(Enum):
    """
    Enum for the SAP HANA SR provider type.
    """

    SAPHANASR = "SAPHanaSR"
    ANGI = "SAPHanaSR-angi"


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


@dataclass
class Result:
    """
    This class is used to store the result of the test case
    """

    status: str = TestStatus.NOT_STARTED.value
    message: str = ""
    details: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the result to a dictionary.

        :return: Dictionary containing the result.
        :rtype: Dict[str, Any]
        """
        return asdict(self)
