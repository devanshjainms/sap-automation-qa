# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Errors raised by CoreApiClient, the typed MCP-to-API HTTP transport (RD-021)."""


class CoreApiError(Exception):
    """Raised when the Core API returns a non-2xx (4xx/5xx) response."""

    def __init__(self, status_code: int, detail: str) -> None:
        """Initialize the error with the response status code and detail.

        :param status_code: HTTP status code returned by the Core API.
        :type status_code: int
        :param detail: Sanitized, bounded description of the failure.
        :type detail: str
        """
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Core API error {status_code}: {detail}")


class CoreApiUnavailableError(Exception):
    """Raised when the Core API cannot be reached (connection failure or timeout)."""

    def __init__(self, detail: str) -> None:
        """Initialize the error with a description of the transport failure.

        :param detail: Human-readable description of the transport failure.
        :type detail: str
        """
        self.detail = detail
        super().__init__(f"Core API unavailable: {detail}")
