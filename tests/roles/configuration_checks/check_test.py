# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import pytest
import yaml


class TestConfigurationChecks:
    """
    Test class for configuration checks.
    """

    @pytest.fixture
    def check_file_content(self):
        """
        Fixture to load the check files.

        :return: List of check files.
        :rtype: list
        """
        check_file_content = {}
        check_files = [
            "app.yml",
            "ascs.yml",
            "hana.yml",
            "hardware.yml",
            "sap.yml",
            "package.yml",
        ]
        for file in check_files:
            with open(
                f"src/roles/configuration_checks/tasks/files/{file}", "r", encoding="utf-8"
            ) as f:
                yaml_content = yaml.safe_load(f)
                check_file_content[file] = yaml_content
        return check_file_content

    def test_no_duplicate_check_id(self, check_file_content):
        """
        Test to ensure there are no duplicate check IDs in the check files.

        :param check_file_content: Content of the check files.
        :type check_file_content: dict
        """
        seen_ids = set()
        checks = []
        for _, yaml_content in check_file_content.items():
            if isinstance(yaml_content, dict) and "checks" in yaml_content:
                checks = yaml_content["checks"]
            for check in checks:
                check_id = check.get("id")
                assert check_id not in seen_ids, f"Duplicate check ID found: {check_id}"
                seen_ids.add(check_id)
