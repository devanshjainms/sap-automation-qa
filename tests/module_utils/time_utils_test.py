# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for the time_utils module.
"""

import pytest
from src.module_utils.time_utils import elapsed_time_str


class TestElapsedTimeStr:
    """Tests for the elapsed_time_str helper function."""

    @pytest.mark.parametrize(
        "start, end, expected",
        [
            # zero elapsed
            (0.0, 0.0, "0s"),
            # seconds only
            (0.0, 1.0, "1s"),
            (100.0, 145.0, "45s"),
            (0.0, 59.0, "59s"),
            # exactly one minute
            (0.0, 60.0, "1m"),
            # minutes and seconds
            (0.0, 135.0, "2m 15s"),
            (1000.0, 1075.0, "1m 15s"),
            # exactly one hour
            (0.0, 3600.0, "1h"),
            # hours, minutes, seconds
            (0.0, 3661.0, "1h 1m 1s"),
            (0.0, 7384.0, "2h 3m 4s"),
            # large value
            (0.0, 86400.0, "24h"),
            # fractional seconds are truncated
            (0.0, 135.9, "2m 15s"),
            # negative elapsed is treated as zero
            (10.0, 5.0, "0s"),
        ],
    )
    def test_elapsed_time_str(self, start: float, end: float, expected: str) -> None:
        """Verify elapsed_time_str returns the expected human-readable string.

        :param start: Start timestamp.
        :param end: End timestamp.
        :param expected: Expected output string.
        """
        assert elapsed_time_str(start, end) == expected
