# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Utility helpers for formatting durations.
"""


def format_duration(seconds: int) -> str:
    """
    Convert a duration in seconds to a human-readable format.

    :param seconds: Duration in seconds.
    :type seconds: int
    :return: Human-readable duration.
    :rtype: str
    :raises ValueError: If seconds is negative.
    """
    if seconds < 0:
        raise ValueError("seconds must be non-negative")

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)
