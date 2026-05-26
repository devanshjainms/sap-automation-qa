# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for the format_duration helper.
"""

import pytest
from src.module_utils.format_duration import format_duration


class TestFormatDuration:
    """
    Test cases for duration formatting.
    """

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (0, "0s"),
            (59, "59s"),
            (60, "1m"),
            (61, "1m 1s"),
            (3600, "1h"),
            (3661, "1h 1m 1s"),
            (7320, "2h 2m"),
        ],
    )
    def test_format_duration(self, seconds, expected):
        """
        Ensure durations are converted to compact human-readable output.

        :param seconds: Input duration in seconds.
        :type seconds: int
        :param expected: Expected formatted value.
        :type expected: str
        """
        assert format_duration(seconds) == expected

    def test_format_duration_negative_seconds(self):
        """
        Ensure negative values are rejected.
        """
        with pytest.raises(ValueError, match="seconds must be non-negative"):
            format_duration(-1)
