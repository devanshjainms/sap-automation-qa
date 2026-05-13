# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for JsonlLoader."""

import json
from pathlib import Path

import pytest
from src.core.knowledge.loader import JsonlLoader
from src.core.models.knowledge import Playbook, Rule


class TestJsonlLoader:
    """Unit tests for JSONL file loading."""

    def _write_jsonl(self, path: Path, records: list[dict]) -> Path:
        """Helper: write records to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
        return path

    def test_load_file_single_record(self, tmp_path: Path) -> None:
        """Verify loading a single-record JSONL file."""
        path = self._write_jsonl(
            tmp_path / "rules.jsonl",
            [{"id": "R-001", "name": "test_rule"}],
        )
        loader = JsonlLoader(tmp_path)
        rules = loader.load_file(path, Rule)
        assert len(rules) == 1
        assert rules[0].id == "R-001"

    def test_load_file_multiple_records(self, tmp_path: Path) -> None:
        """Verify loading multiple records from a JSONL file."""
        records = [{"id": f"R-{i:03d}", "name": f"rule_{i}"} for i in range(5)]
        path = self._write_jsonl(tmp_path / "rules.jsonl", records)
        loader = JsonlLoader(tmp_path)
        rules = loader.load_file(path, Rule)
        assert len(rules) == 5

    def test_load_file_skips_blank_lines(self, tmp_path: Path) -> None:
        """Verify blank lines in JSONL are skipped."""
        path = tmp_path / "rules.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "R-001", "name": "a"}) + "\n")
            fh.write("\n")
            fh.write("   \n")
            fh.write(json.dumps({"id": "R-002", "name": "b"}) + "\n")
        loader = JsonlLoader(tmp_path)
        rules = loader.load_file(path, Rule)
        assert len(rules) == 2

    def test_load_file_skips_malformed_lines(self, tmp_path: Path) -> None:
        """Verify malformed JSON lines are skipped, not fatal."""
        path = tmp_path / "rules.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "R-001", "name": "good"}) + "\n")
            fh.write("this is not json\n")
            fh.write(json.dumps({"id": "R-002", "name": "also good"}) + "\n")
        loader = JsonlLoader(tmp_path)
        rules = loader.load_file(path, Rule)
        assert len(rules) == 2

    def test_load_file_not_found(self, tmp_path: Path) -> None:
        """Verify FileNotFoundError for missing files."""
        loader = JsonlLoader(tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_file(tmp_path / "missing.jsonl", Rule)

    def test_load_file_relative_path(self, tmp_path: Path) -> None:
        """Verify relative paths resolve against base_dir."""
        self._write_jsonl(
            tmp_path / "data.jsonl",
            [{"id": "R-001", "name": "rel"}],
        )
        loader = JsonlLoader(tmp_path)
        rules = loader.load_file("data.jsonl", Rule)
        assert len(rules) == 1

    def test_load_directory_all_files(self, tmp_path: Path) -> None:
        """Verify loading all JSONL files from a directory."""
        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        self._write_jsonl(seed_dir / "a.jsonl", [{"id": "R-001", "name": "a"}])
        self._write_jsonl(seed_dir / "b.jsonl", [{"id": "R-002", "name": "b"}])
        loader = JsonlLoader(tmp_path)
        rules = loader.load_directory("seed", Rule)
        assert len(rules) == 2

    def test_load_directory_empty(self, tmp_path: Path) -> None:
        """Verify empty directory returns empty list."""
        (tmp_path / "empty").mkdir()
        loader = JsonlLoader(tmp_path)
        rules = loader.load_directory("empty", Rule)
        assert rules == []

    def test_load_directory_missing(self, tmp_path: Path) -> None:
        """Verify missing directory returns empty list."""
        loader = JsonlLoader(tmp_path)
        rules = loader.load_directory("nonexistent", Rule)
        assert rules == []

    def test_load_directory_different_model(self, tmp_path: Path) -> None:
        """Verify loading playbooks from JSONL."""
        self._write_jsonl(
            tmp_path / "pbs.jsonl",
            [
                {
                    "id": "PB-001",
                    "name": "Takeover failure",
                    "symptoms": ["Secondary stays SOK"],
                    "source": "seed",
                }
            ],
        )
        loader = JsonlLoader(tmp_path)
        playbooks = loader.load_file("pbs.jsonl", Playbook)
        assert len(playbooks) == 1
        assert playbooks[0].symptoms == ["Secondary stays SOK"]

    def test_base_dir_property(self, tmp_path: Path) -> None:
        """Verify base_dir property returns the configured path."""
        loader = JsonlLoader(tmp_path)
        assert loader.base_dir == tmp_path
