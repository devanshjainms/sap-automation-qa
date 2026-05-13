# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""JSONL file loader for seed and learned knowledge."""

import json
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class JsonlLoader:
    """Reads ``*.jsonl`` files and deserializes each line into a Pydantic model.

    Isolated I/O boundary — all filesystem access for knowledge loading
    passes through this class.

    :param base_dir: Root directory containing JSONL files.
    """

    def __init__(self, base_dir: Path | str) -> None:
        """Initialize the loader.

        :param base_dir: Root directory to scan for JSONL files.
        """
        self._base_dir = Path(base_dir)

    @property
    def base_dir(self) -> Path:
        """Root directory this loader reads from."""
        return self._base_dir

    def load_file(self, path: Path | str, model: Type[T]) -> list[T]:
        """Load a single JSONL file into a list of model instances.

        Blank lines are skipped. Invalid lines are skipped with a warning
        logged to stderr (fail-open on individual records, not the file).

        :param path: Path to the JSONL file.
        :param model: Pydantic model class to deserialize into.
        :returns: List of deserialized model instances.
        :raises FileNotFoundError: If the file does not exist.
        """
        file_path = Path(path)
        if not file_path.is_absolute() and not file_path.exists():
            file_path = self._base_dir / file_path

        items: list[T] = []
        with open(file_path, encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                    items.append(model.model_validate(data))
                except (json.JSONDecodeError, ValueError):
                    continue
        return items

    def load_directory(
        self,
        subdir: str,
        model: Type[T],
        pattern: str = "*.jsonl",
    ) -> list[T]:
        """Load all JSONL files matching a glob pattern from a subdirectory.

        :param subdir: Subdirectory relative to base_dir (empty = base_dir itself).
        :param model: Pydantic model class to deserialize into.
        :param pattern: Glob pattern for file matching.
        :returns: Concatenated list of all deserialized records.
        """
        target = self._base_dir / subdir if subdir else self._base_dir
        if not target.is_dir():
            return []

        items: list[T] = []
        for jsonl_file in sorted(target.glob(pattern)):
            items.extend(self.load_file(jsonl_file, model))
        return items
