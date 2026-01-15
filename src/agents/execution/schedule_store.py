# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lightweight JSON-based storage for schedules."""

import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from src.agents.models.schedule import Schedule
from src.agents.observability import get_logger

logger = get_logger(__name__)


class ScheduleStore:
    """JSON file-based storage for schedules.

    Lightweight alternative to database for storing schedule configurations.
    Suitable for small to medium scale deployments (< 1000 schedules).
    """

    def __init__(self, storage_path: Path | str = "data/schedules.json") -> None:
        """Initialize the schedule store.

        :param storage_path: Path to JSON storage file
        :type storage_path: Path | str
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write_schedules([])
            logger.info(f"Initialized schedule storage at {self.storage_path}")

    def _read_schedules(self) -> List[Schedule]:
        """Read all schedules from storage.

        :returns: List of schedules
        :rtype: List[Schedule]
        """
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)

            schedules = []
            for item in data:
                if item.get("next_run_time"):
                    dt_str = item["next_run_time"].replace("Z", "+00:00")
                    item["next_run_time"] = datetime.fromisoformat(dt_str)
                if item.get("last_run_time"):
                    dt_str = item["last_run_time"].replace("Z", "+00:00")
                    item["last_run_time"] = datetime.fromisoformat(dt_str)
                if item.get("created_at"):
                    item["created_at"] = datetime.fromisoformat(item["created_at"])
                if item.get("updated_at"):
                    item["updated_at"] = datetime.fromisoformat(item["updated_at"])

                schedules.append(Schedule(**item))

            return schedules
        except Exception as e:
            logger.error(f"Failed to read schedules: {e}")
            return []

    def _write_schedules(self, schedules: List[Schedule]) -> None:
        """Write schedules to storage.

        :param schedules: List of schedules to persist
        :type schedules: List[Schedule]
        """
        try:
            data = [s.model_dump(mode="json") for s in schedules]

            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)

            logger.debug(f"Wrote {len(schedules)} schedules to storage")
        except Exception as e:
            logger.error(f"Failed to write schedules: {e}")
            raise

    def create(self, schedule: Schedule) -> Schedule:
        """Create a new schedule.

        :param schedule: Schedule to create
        :type schedule: Schedule
        :returns: Created schedule
        :rtype: Schedule
        :raises ValueError: If schedule with same ID already exists
        """
        schedules = self._read_schedules()

        if any(s.id == schedule.id for s in schedules):
            raise ValueError(f"Schedule with ID {schedule.id} already exists")

        schedules.append(schedule)
        self._write_schedules(schedules)

        logger.info(f"Created schedule {schedule.id}: {schedule.name}")
        return schedule

    def get(self, schedule_id: str) -> Optional[Schedule]:
        """Get a schedule by ID.

        :param schedule_id: Schedule ID
        :type schedule_id: str
        :returns: Schedule if found, None otherwise
        :rtype: Optional[Schedule]
        """
        schedules = self._read_schedules()
        return next((s for s in schedules if s.id == schedule_id), None)

    def list(self, enabled_only: bool = False) -> List[Schedule]:
        """List all schedules.

        :param enabled_only: If True, return only enabled schedules
        :type enabled_only: bool
        :returns: List of schedules
        :rtype: List[Schedule]
        """
        schedules = self._read_schedules()

        if enabled_only:
            schedules = [s for s in schedules if s.enabled]

        return schedules

    def update(self, schedule: Schedule) -> Schedule:
        """Update an existing schedule.

        :param schedule: Schedule with updated data
        :type schedule: Schedule
        :returns: Updated schedule
        :rtype: Schedule
        :raises ValueError: If schedule not found
        """
        schedules = self._read_schedules()

        index = next((i for i, s in enumerate(schedules) if s.id == schedule.id), None)
        if index is None:
            raise ValueError(f"Schedule {schedule.id} not found")

        schedule.updated_at = datetime.utcnow()
        schedules[index] = schedule
        self._write_schedules(schedules)

        logger.info(f"Updated schedule {schedule.id}: {schedule.name}")
        return schedule

    def delete(self, schedule_id: str) -> None:
        """Delete a schedule.

        :param schedule_id: Schedule ID
        :type schedule_id: str
        :raises ValueError: If schedule not found
        """
        schedules = self._read_schedules()

        initial_len = len(schedules)
        schedules = [s for s in schedules if s.id != schedule_id]

        if len(schedules) == initial_len:
            raise ValueError(f"Schedule {schedule_id} not found")

        self._write_schedules(schedules)
        logger.info(f"Deleted schedule {schedule_id}")
