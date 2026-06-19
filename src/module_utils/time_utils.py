# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Utility helpers for time and duration formatting.
"""


def elapsed_time_str(start: float, end: float) -> str:
    """Return a human-readable string for the elapsed time between *start* and *end*.

    Both *start* and *end* are Unix timestamps (seconds since the epoch) as
    returned by :func:`time.time`.  The result is formatted as ``Xh Ym Zs``,
    omitting leading zero components except that a zero-second result is
    rendered as ``0s``.

    Examples::

        elapsed_time_str(0.0, 135.0)   # "2m 15s"
        elapsed_time_str(0.0, 0.0)     # "0s"
        elapsed_time_str(0.0, 3661.0)  # "1h 1m 1s"

    :param start: Start timestamp in seconds.
    :type start: float
    :param end: End timestamp in seconds.
    :type end: float
    :return: Human-readable elapsed-time string.
    :rtype: str
    """
    total_seconds = max(int(end - start), 0)

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)
