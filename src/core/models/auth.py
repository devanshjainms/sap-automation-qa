# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthenticatedUser:
    """Immutable value object representing an authenticated caller.

    :param oid: Azure AD object ID of the user or service principal.
    :param name: Display name (may be empty for service principals).
    :param email: User principal name or email.
    :param tenant_id: Azure AD tenant ID from the token.
    :param roles: Application roles assigned to the caller.
    :param raw_claims: Full set of decoded JWT claims.
    """

    oid: str
    name: str
    email: str
    tenant_id: str
    roles: tuple[str, ...]
    raw_claims: dict[str, Any]
