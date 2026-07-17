# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health models"""

from typing import Dict, Optional
from dataclasses import dataclass, field
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: str
    version: str
    services: Dict[str, bool] = Field(default_factory=dict)
    storage_backend: Optional[str] = None
    workspace_backend: Optional[str] = None


@dataclass
class HealthState:
    """Mutable health state updated by application lifecycle events."""

    services: Dict[str, bool] = field(default_factory=dict)
    storage_backend: Optional[str] = None
    workspace_backend: Optional[str] = None
